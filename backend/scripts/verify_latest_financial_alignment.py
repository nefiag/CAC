"""Prove that the latest source statements and CAC report output align exactly.

This is a read-only release gate.  It compares the canonical workbook, active
database snapshot and report-service response for every legal entity and each
of the three financial statement types.  Any hash, row or cent-level mismatch
causes a non-zero exit status.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import openpyxl
from sqlalchemy import select

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database import AsyncSessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    FinancialBalanceSnapshot,
    FinancialImportBatch,
    FinancialReportSnapshotRow,
)
from app.services.financial_import import _money, _text, inspect_financial_workbook  # noqa: E402
from app.services.report_service import (  # noqa: E402
    build_balance_sheet,
    build_category_summary,
    build_income_statement,
)
from scripts.rebuild_financial_baseline import canonical_workbooks  # noqa: E402

REPORT_TYPES = ("TRIAL_BALANCE", "INCOME_STATEMENT", "BALANCE_SHEET")
MONEY_KEYS = {
    "TRIAL_BALANCE": (
        "opening_debit", "opening_credit", "period_debit", "period_credit",
        "ytd_debit", "ytd_credit", "closing_debit", "closing_credit",
    ),
    "INCOME_STATEMENT": ("ytd_amount", "month_amount"),
    "BALANCE_SHEET": ("asset_close", "asset_open", "liab_close", "liab_open"),
}


def source_rows(path: Path, document_type: str) -> list[dict[str, Any]]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [list(row) for row in wb.active.iter_rows(values_only=True)]
    if document_type == "TRIAL_BALANCE":
        result = []
        for row_no, row in enumerate(rows[4:], 5):
            code = _text(row[0] if row else None)
            if not code or code == "合计":
                continue
            values = [_money(row[i] if i < len(row) else None) for i in range(2, 10)]
            result.append({
                "row_no": row_no, "code": code, "name": _text(row[1]),
                **dict(zip(MONEY_KEYS[document_type], values)),
            })
        return result
    if document_type == "INCOME_STATEMENT":
        return [{
            "row_no": row_no, "item": _text(row[0]), "line_no": _text(row[1]),
            "ytd_amount": _money(row[2]), "month_amount": _money(row[3]),
        } for row_no, row in enumerate(rows[3:], 4)]
    return [{
        "row_no": row_no,
        "asset_item": _text(row[0]), "asset_line_no": _text(row[1]),
        "asset_close": _money(row[2]), "asset_open": _money(row[3]),
        "liab_item": _text(row[4]), "liab_line_no": _text(row[5]),
        "liab_close": _money(row[6]), "liab_open": _money(row[7]),
    } for row_no, row in enumerate(rows[3:], 4)]


def normalize_value(key: str, value: Any) -> Any:
    if key in {item for values in MONEY_KEYS.values() for item in values}:
        return _money(value)
    return _text(value)


def compare_rows(expected: list[dict], actual: list[dict], keys: tuple[str, ...]) -> list[dict]:
    mismatches: list[dict] = []
    if len(expected) != len(actual):
        mismatches.append({"kind": "row_count", "source": len(expected), "system": len(actual)})
    for index in range(max(len(expected), len(actual))):
        if index >= len(expected) or index >= len(actual):
            mismatches.append({"kind": "missing_row", "index": index + 1,
                               "source": index < len(expected), "system": index < len(actual)})
            continue
        for key in keys:
            left, right = normalize_value(key, expected[index].get(key)), normalize_value(key, actual[index].get(key))
            if left != right:
                mismatches.append({"kind": "field", "index": index + 1, "field": key,
                                   "source": str(left), "system": str(right)})
    return mismatches


async def verify(source: Path) -> dict:
    selected, duplicates = canonical_workbooks(source)
    candidates: dict[tuple[str, str], tuple[Path, dict]] = {}
    for path in selected:
        info = inspect_financial_workbook(path.name, path.read_bytes())
        if info["document_type"] not in REPORT_TYPES:
            continue
        key = (info["account_set_id"], info["document_type"])
        if key not in candidates or info["period"] > candidates[key][1]["period"]:
            candidates[key] = (path, info)

    checks, all_mismatches = [], []
    async with AsyncSessionLocal() as db:
        for (account_set_id, document_type), (path, info) in sorted(candidates.items()):
            batch = (await db.execute(select(FinancialImportBatch).where(
                FinancialImportBatch.account_set_id == account_set_id,
                FinancialImportBatch.period == info["period"],
                FinancialImportBatch.document_type == document_type,
                FinancialImportBatch.is_active == True,  # noqa: E712
                FinancialImportBatch.status == "VALIDATED",
            ))).scalar_one_or_none()
            mismatches = []
            if batch is None:
                mismatches.append({"kind": "missing_active_batch"})
                db_rows, api_rows, source_snapshot = [], [], False
            else:
                if batch.source_sha256 != info["sha256"]:
                    mismatches.append({"kind": "sha256", "source": info["sha256"], "system": batch.source_sha256})
                if document_type == "TRIAL_BALANCE":
                    stored = (await db.execute(select(FinancialBalanceSnapshot).where(
                        FinancialBalanceSnapshot.batch_id == batch.id
                    ).order_by(FinancialBalanceSnapshot.source_row_no))).scalars().all()
                    db_rows = [{"row_no": x.source_row_no, "code": x.account_code, "name": x.account_name,
                                **{key: getattr(x, key) for key in MONEY_KEYS[document_type]}} for x in stored]
                    api = await build_category_summary(db, account_set_id, info["period"])
                    api_rows, source_snapshot = api["rows"], api.get("source_snapshot", False)
                    keys = ("code", "name", *MONEY_KEYS[document_type])
                else:
                    stored = (await db.execute(select(FinancialReportSnapshotRow).where(
                        FinancialReportSnapshotRow.batch_id == batch.id
                    ).order_by(FinancialReportSnapshotRow.row_no))).scalars().all()
                    db_rows = [{"row_no": x.row_no, **x.values} for x in stored]
                    api = (await build_income_statement(db, account_set_id, info["period"])) if document_type == "INCOME_STATEMENT" else (await build_balance_sheet(db, account_set_id, info["period"]))
                    api_rows = api["lines"] if document_type == "INCOME_STATEMENT" else api["rows"]
                    source_snapshot = api.get("source_snapshot", False)
                    keys = (("item", "line_no", *MONEY_KEYS[document_type]) if document_type == "INCOME_STATEMENT"
                            else ("asset_item", "asset_line_no", *MONEY_KEYS[document_type][:2],
                                  "liab_item", "liab_line_no", *MONEY_KEYS[document_type][2:]))
                expected = source_rows(path, document_type)
                mismatches.extend({"layer": "database", **item} for item in compare_rows(expected, db_rows, keys))
                mismatches.extend({"layer": "report_service", **item} for item in compare_rows(expected, api_rows, keys))
                if not source_snapshot:
                    mismatches.append({"kind": "report_not_using_source_snapshot"})
            check = {"company": info["company_name"], "account_set_id": account_set_id,
                     "period": info["period"], "document_type": document_type,
                     "source_file": str(path.relative_to(source)), "source_sha256": info["sha256"],
                     "source_rows": len(source_rows(path, document_type)), "database_rows": len(db_rows),
                     "report_rows": len(api_rows), "mismatch_count": len(mismatches), "mismatches": mismatches}
            checks.append(check)
            all_mismatches.extend(mismatches)
    expected_check_count = len({key[0] for key in candidates}) * len(REPORT_TYPES)
    if len(checks) != expected_check_count:
        all_mismatches.append({"kind": "missing_latest_statement_type", "expected": expected_check_count, "actual": len(checks)})
    return {"status": "PASS" if not all_mismatches else "FAIL", "acceptance": "latest statements align exactly",
            "canonical_workbooks": len(selected), "logical_duplicates_excluded": len(duplicates),
            "checks": checks, "total_mismatches": len(all_mismatches), "gate_passed": not all_mismatches}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = asyncio.run(verify(args.source.resolve()))
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    raise SystemExit(0 if result["gate_passed"] else 1)


if __name__ == "__main__":
    main()
