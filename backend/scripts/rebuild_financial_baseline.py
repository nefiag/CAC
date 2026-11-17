"""Rebuild the production financial baseline from the audited Boshite source set.

The command is dry-run by default.  ``--apply`` performs one database transaction:
business-finance rows are cleared and the validated baseline is inserted.  Auth,
sessions, user/account-set permissions, and account-set settings are never cleared.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.models import (  # noqa: E402
    AccountSet, BankAccount, ChartOfAccount, FinancialImportBatch,
    FinancialSourceRow, ReaEvent, Voucher, VoucherEntry, gen_uuid,
)
from app.services.financial_import import (  # noqa: E402
    BSTER_SET_ID, YT_SET_ID, _category_and_direction,
    import_financial_workbook, inspect_financial_workbook,
)

YT_BANK_ID = "00000000-0000-0000-0000-000000000020"
FINANCE_TABLES = (
    "financial_report_snapshot_rows", "financial_balance_snapshots",
    "financial_source_rows", "financial_import_batches", "contract_plans",
    "contracts", "voucher_entries", "bank_statements", "vouchers",
    "account_balances", "bank_accounts", "rea_events", "rea_agents",
    "rea_resources", "chart_of_accounts",
)


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def split_account(value: str) -> tuple[str, str]:
    code, _, name = value.partition("-")
    return code.strip(), name.strip()


def leaf_lines(lines: list[dict], side: str) -> list[dict]:
    amount_key = "debit" if side == "debit" else "credit"
    selected = [line for line in lines if money(line.get(amount_key)) != 0]
    codes = [split_account(line["account"])[0] for line in selected]
    return [line for line in selected if not any(
        other != split_account(line["account"])[0]
        and other.startswith(split_account(line["account"])[0]) for other in codes
    )]


def canonical_workbooks(source: Path) -> tuple[list[Path], list[dict]]:
    candidates: dict[tuple[str, str, str], list[tuple[Path, dict]]] = defaultdict(list)
    for path in sorted(source.rglob("*.xlsx")):
        info = inspect_financial_workbook(path.name, path.read_bytes())
        if not info.get("valid"):
            raise ValueError(f"{path}: {info.get('errors')}")
        key = (info["account_set_id"], info["period"], info["document_type"])
        candidates[key].append((path, info))
    selected, duplicates = [], []
    for key, items in sorted(candidates.items()):
        # Prefer the named original, then the shortest relative path.
        items.sort(key=lambda item: (item[0].name.startswith("副本"), len(str(item[0].relative_to(source))), str(item[0])))
        selected.append(items[0][0])
        for path, info in items[1:]:
            duplicates.append({"file": str(path.relative_to(source)), "canonical": str(items[0][0].relative_to(source)),
                               "logical_key": list(key), "sha256": info["sha256"]})
    return selected, duplicates


def preflight(source: Path, analysis: Path) -> dict:
    selected, duplicates = canonical_workbooks(source)
    vouchers = json.loads((analysis / "vouchers.json").read_text(encoding="utf-8"))
    bad = []
    leaf_entry_count = 0
    accounts: dict[str, str] = {}
    for voucher in vouchers:
        debit = leaf_lines(voucher["lines"], "debit")
        credit = leaf_lines(voucher["lines"], "credit")
        d = sum((money(x["debit"]) for x in debit), Decimal())
        c = sum((money(x["credit"]) for x in credit), Decimal())
        # Historical red-letter entries are represented as negative amounts on
        # one side, so a valid voucher may net to zero on both sides.
        if d != c or not (debit or credit):
            bad.append({"date": voucher["date"], "voucher": voucher["voucher"], "debit": str(d), "credit": str(c)})
        for line in debit + credit:
            code, name = split_account(line["account"])
            accounts[code] = name
        leaf_entry_count += len(debit) + len(credit)
    if bad:
        raise ValueError(f"{len(bad)} vouchers fail leaf-level balancing: {bad[:3]}")
    pdfs = sorted(source.rglob("*.pdf"))
    return {
        "source_files": sum(1 for item in source.rglob("*") if item.is_file()), "selected_workbooks": len(selected),
        "logical_duplicates_excluded": len(duplicates), "pdf_statements": len(pdfs),
        "vouchers": len(vouchers), "voucher_entries": leaf_entry_count,
        "voucher_accounts": len(accounts), "selected": [str(p.relative_to(source)) for p in selected],
        "duplicates": duplicates,
    }


async def ensure_account_sets(db):
    specs = (
        (BSTER_SET_ID, "博士特电子科技（昆山）有限公司", "2018-01"),
        (YT_SET_ID, "昆山宇天新能源科技有限公司", "2023-04"),
    )
    for set_id, name, start in specs:
        item = await db.get(AccountSet, set_id)
        if item is None:
            item = AccountSet(id=set_id, company_name=name)
            db.add(item)
        item.company_name, item.start_period, item.current_period = name, start, "2026-10"
    await db.flush()


async def import_vouchers(db, analysis: Path):
    records = json.loads((analysis / "vouchers.json").read_text(encoding="utf-8"))
    account_names: dict[str, str] = {}
    prepared = []
    for record in records:
        lines = leaf_lines(record["lines"], "debit") + leaf_lines(record["lines"], "credit")
        for line in lines:
            code, name = split_account(line["account"])
            account_names[code] = name
        prepared.append((record, lines))

    all_codes = sorted(account_names)
    existing = set((await db.execute(select(ChartOfAccount.code).where(
        ChartOfAccount.account_set_id == BSTER_SET_ID))).scalars())
    for code in all_codes:
        if code in existing:
            continue
        parents = [candidate for candidate in all_codes if candidate != code and code.startswith(candidate)]
        category, direction = _category_and_direction(code)
        db.add(ChartOfAccount(account_set_id=BSTER_SET_ID, code=code, name=account_names[code],
                              parent_code=max(parents, key=len) if parents else None,
                              level=1 + len(parents), category=category, balance_direction=direction,
                              is_leaf=not any(candidate != code and candidate.startswith(code) for candidate in all_codes)))
    await db.flush()

    for record, lines in prepared:
        voucher_date = date.fromisoformat(record["date"][:10])
        match = re.search(r"(.+?)-(\d+)$", record["voucher"])
        if not match:
            raise ValueError(f"Invalid voucher number: {record['voucher']}")
        fingerprint = hashlib.sha256(
            f"BSTER|{record['date']}|{record['voucher']}".encode("utf-8")
        ).hexdigest()
        event = ReaEvent(id=gen_uuid(), account_set_id=BSTER_SET_ID, event_type="HISTORICAL_VOUCHER",
                         event_date=voucher_date, source_doc_type="SUBSIDIARY_LEDGER",
                         raw_payload={"baseline_fingerprint": fingerprint, "summaries": record["summaries"],
                                      "source": "2018-2026 audited subsidiary ledgers"})
        db.add(event)
        voucher = Voucher(id=gen_uuid(), account_set_id=BSTER_SET_ID, period=voucher_date.strftime("%Y-%m"),
                          voucher_word=match.group(1), voucher_no=int(match.group(2)),
                          voucher_date=voucher_date, status="POSTED", rea_event_id=event.id)
        db.add(voucher)
        for number, line in enumerate(lines, 1):
            code, _ = split_account(line["account"])
            aux = {k: line[k] for k in ("customer", "supplier") if line.get(k)}
            db.add(VoucherEntry(id=gen_uuid(), voucher_id=voucher.id, line_no=number, summary=line["summary"],
                                account_code=code, debit_amount=money(line["debit"]),
                                credit_amount=money(line["credit"]), aux_dimensions=aux,
                                aux_hash=hashlib.sha256(json.dumps(aux, ensure_ascii=False, sort_keys=True).encode()).hexdigest() if aux else ""))
    await db.flush()


async def import_pdf_index(db, source: Path, analysis: Path):
    summaries = {}
    with (analysis / "statement-summaries.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            summaries[row["file"].replace("\\", "/")] = row
    for path in sorted(source.rglob("*.pdf")):
        relative = str(path.relative_to(source)).replace("\\", "/")
        content = path.read_bytes()
        summary = summaries.get(relative, {})
        period_match = re.search(r"(20\d{2})[^0-9]*(\d{1,2})", path.name)
        period = f"{period_match.group(1)}-{int(period_match.group(2)):02d}" if period_match else "UNKNOWN"
        batch = FinancialImportBatch(id=gen_uuid(), account_set_id=YT_SET_ID, period=period,
            source_filename=relative, source_sha256=hashlib.sha256(content).hexdigest(),
            document_type="BANK_STATEMENT_PDF", sheet_name="PDF", status="SOURCE_ARCHIVED",
            validation_summary={"source_size": len(content), "summary": summary,
                                "posting_policy": "baseline evidence only; no duplicate voucher posting"}, is_active=True)
        db.add(batch)
        db.add(FinancialSourceRow(id=gen_uuid(), batch_id=batch.id, sheet_name="PDF_INDEX", row_no=1,
                                  row_kind="SOURCE_SUMMARY", values=[summary]))
    db.add(BankAccount(id=YT_BANK_ID, account_set_id=YT_SET_ID,
                       bank_name="宁波银行", account_no="75090122000494642",
                       linked_account_code="100201"))
    await db.flush()


async def database_counts(db) -> dict:
    names = ["chart_of_accounts", "vouchers", "voucher_entries", "financial_import_batches",
             "financial_source_rows", "financial_balance_snapshots", "financial_report_snapshot_rows",
             "bank_accounts", "bank_statements"]
    return {name: int((await db.execute(text(f'SELECT count(*) FROM "{name}"'))).scalar_one()) for name in names}


async def rebuild(source: Path, analysis: Path, apply: bool) -> dict:
    report = preflight(source, analysis)
    if not apply:
        return {"mode": "DRY_RUN", **report}
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    selected, _ = canonical_workbooks(source)
    async with AsyncSessionLocal() as db:
        async with db.begin():
            before = await database_counts(db)
            await db.execute(text("TRUNCATE " + ", ".join(FINANCE_TABLES) + " CASCADE"))
            await ensure_account_sets(db)
            for path in selected:
                result = await import_financial_workbook(
                    db, str(path.relative_to(source)), path.read_bytes(),
                    commit=False, allow_formal_admin=True,
                )
                if result["status"] != "IMPORTED":
                    raise ValueError(f"Workbook import failed: {path}: {result}")
            await import_vouchers(db, analysis)
            await import_pdf_index(db, source, analysis)
            # Database-level voucher balance gate.
            bad = (await db.execute(text("""
                SELECT count(*) FROM (
                  SELECT v.id FROM vouchers v JOIN voucher_entries e ON e.voucher_id=v.id
                  GROUP BY v.id HAVING round(sum(e.debit_amount),2) <> round(sum(e.credit_amount),2)
                ) q
            """))).scalar_one()
            if bad:
                raise ValueError(f"Database contains {bad} unbalanced vouchers")
            after = await database_counts(db)
        return {"mode": "APPLIED", "before": before, "after": after, **report}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = asyncio.run(rebuild(args.source.resolve(), args.analysis.resolve(), args.apply))
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
