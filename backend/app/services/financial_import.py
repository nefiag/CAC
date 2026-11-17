from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from decimal import Decimal
from typing import Any

import openpyxl
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from .ledger_environment import require_trial_ledger

from ..models import (
    AccountBalance,
    AccountSet,
    ChartOfAccount,
    FinancialBalanceSnapshot,
    FinancialImportBatch,
    FinancialReportSnapshotRow,
    FinancialSourceRow,
)

BSTER_SET_ID = "00000000-0000-0000-0000-000000000001"
YT_SET_ID = "00000000-0000-0000-0000-000000000002"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _money(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _json_value(value: Any):
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _detect_identity(filename: str, rows: list[list[Any]]) -> tuple[str, str]:
    probe = filename + " " + " ".join(_text(v) for row in rows[:4] for v in row)
    if "昆山宇天新能源科技有限公司" in probe:
        return YT_SET_ID, "昆山宇天新能源科技有限公司"
    if "博士特电子科技" in probe:
        return BSTER_SET_ID, "博士特电子科技（昆山）有限公司"
    raise ValueError("无法从工作簿内容识别法人主体")


def _detect_period(filename: str, rows: list[list[Any]]) -> str:
    probe = filename + " " + " ".join(_text(v) for row in rows[:4] for v in row)
    matches = re.findall(r"(20\d{2})[^0-9]{0,3}(\d{1,2})(?:期|月|[-月]\d{1,2}日)", probe)
    if not matches:
        compact = re.search(r"(20\d{2})(\d{2})", probe)
        if compact:
            return f"{compact.group(1)}-{compact.group(2)}"
        raise ValueError("无法识别会计期间")
    year, month = matches[-1]
    return f"{year}-{int(month):02d}"


def inspect_financial_workbook(filename: str, content: bytes) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        return {"valid": False, "errors": [f"无法读取工作簿：{exc}"], "sha256": digest}
    ws = wb.active
    rows = [list(row) for row in ws.iter_rows(values_only=True)]
    try:
        account_set_id, company_name = _detect_identity(filename, rows)
        period = _detect_period(filename, rows)
    except ValueError as exc:
        return {"valid": False, "errors": [str(exc)], "sha256": digest}
    title = _text(rows[0][0]) if rows and rows[0] else ""
    doc_type = {"科目余额表": "TRIAL_BALANCE", "资产负债表": "BALANCE_SHEET", "利润表": "INCOME_STATEMENT", "总账": "GENERAL_LEDGER"}.get(title)
    if title.startswith("明细账"):
        doc_type = "SUBSIDIARY_LEDGER"
    if not doc_type:
        return {"valid": False, "errors": [f"不支持的工作表类型：{title or ws.title}"], "sha256": digest}
    errors, checks = [], {}
    if doc_type == "TRIAL_BALANCE" and len(rows) >= 5:
        total = rows[-1]
        pairs = ((2, 3, "opening"), (4, 5, "period"), (6, 7, "ytd"), (8, 9, "closing"))
        for left, right, name in pairs:
            diff = _money(total[left]) - _money(total[right])
            checks[f"{name}_difference"] = float(diff)
            if abs(diff) > Decimal("0.01"):
                errors.append(f"科目余额表{name}借贷不平，差额 {diff}")
    elif doc_type == "BALANCE_SHEET" and len(rows) >= 35:
        total = rows[-1]
        close_diff = _money(total[2]) - _money(total[6])
        open_diff = _money(total[3]) - _money(total[7])
        checks.update({"closing_difference": float(close_diff), "opening_difference": float(open_diff)})
        if abs(close_diff) > Decimal("0.01") or abs(open_diff) > Decimal("0.01"):
            errors.append("资产负债表不平衡")
    return {
        "valid": not errors, "errors": errors, "sha256": digest, "document_type": doc_type,
        "company_name": company_name, "account_set_id": account_set_id, "period": period,
        "sheet_name": ws.title, "row_count": len(rows), "checks": checks,
    }


def _category_and_direction(code: str) -> tuple[str, str]:
    first = code[:1]
    if first == "1": return "资产", "DEBIT"
    if first == "2": return "负债", "CREDIT"
    if first in {"3", "4"}: return "权益", "CREDIT"
    if first == "5":
        is_income = code.startswith(("500", "505", "510", "520", "530"))
        return "损益", "CREDIT" if is_income else "DEBIT"
    return "其他", "DEBIT"


async def import_financial_workbook(
    db: AsyncSession, filename: str, content: bytes, *, commit: bool = True,
    target_account_set_id: str | None = None, allow_formal_admin: bool = False,
) -> dict:
    info = inspect_financial_workbook(filename, content)
    if not info["valid"]:
        return {"status": "INVALID", **info}
    detected_account_set_id = info["account_set_id"]
    if target_account_set_id:
        await require_trial_ledger(db, target_account_set_id)
        info["detected_formal_account_set_id"] = detected_account_set_id
        info["account_set_id"] = target_account_set_id
    elif not allow_formal_admin:
        await require_trial_ledger(db, info["account_set_id"])
    duplicate = (await db.execute(select(FinancialImportBatch).where(
        FinancialImportBatch.account_set_id == info["account_set_id"],
        FinancialImportBatch.source_sha256 == info["sha256"],
    ))).scalar_one_or_none()
    if duplicate:
        return {"status": "DUPLICATE", "batch_id": duplicate.id, **info}

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = [list(row) for row in ws.iter_rows(values_only=True)]
    await db.execute(update(FinancialImportBatch).where(
        FinancialImportBatch.account_set_id == info["account_set_id"],
        FinancialImportBatch.period == info["period"],
        FinancialImportBatch.document_type == info["document_type"],
    ).values(is_active=False))
    batch = FinancialImportBatch(
        account_set_id=info["account_set_id"], period=info["period"], source_filename=filename,
        source_sha256=info["sha256"], document_type=info["document_type"], sheet_name=ws.title,
        status="VALIDATED", validation_summary={"checks": info["checks"], "row_count": len(rows)}, is_active=True,
    )
    db.add(batch)
    await db.flush()
    for index, row in enumerate(rows, 1):
        db.add(FinancialSourceRow(batch_id=batch.id, sheet_name=ws.title, row_no=index,
            row_kind="HEADER" if index <= 4 else "DATA", values=[_json_value(v) for v in row]))

    if info["document_type"] == "TRIAL_BALANCE":
        codes = [_text(row[0]) for row in rows[4:] if row and _text(row[0])]
        account_map = {item.code: item for item in (await db.execute(
            select(ChartOfAccount).where(ChartOfAccount.account_set_id == info["account_set_id"])
        )).scalars().all()}
        balance_map = {item.account_code: item for item in (await db.execute(
            select(AccountBalance).where(
                AccountBalance.account_set_id == info["account_set_id"],
                AccountBalance.period == info["period"],
                AccountBalance.aux_hash == "SOURCE_SNAPSHOT",
            )
        )).scalars().all()}
        for index, row in enumerate(rows[4:], 5):
            code = _text(row[0])
            if not code or code == "合计":
                continue
            name = _text(row[1])
            values = [_money(row[i] if i < len(row) else None) for i in range(2, 10)]
            snap = FinancialBalanceSnapshot(
                batch_id=batch.id, account_set_id=info["account_set_id"], period=info["period"],
                source_row_no=index, account_code=code, account_name=name,
                opening_debit=values[0], opening_credit=values[1], period_debit=values[2], period_credit=values[3],
                ytd_debit=values[4], ytd_credit=values[5], closing_debit=values[6], closing_credit=values[7],
            )
            db.add(snap)
            category, direction = _category_and_direction(code)
            account = account_map.get(code)
            is_leaf = not any(other != code and other.startswith(code) for other in codes)
            parent_candidates = [other for other in codes if code != other and code.startswith(other)]
            parent = max(parent_candidates, key=len) if parent_candidates else None
            if not account:
                account = ChartOfAccount(account_set_id=info["account_set_id"], code=code, name=name,
                    level=1 + len(parent_candidates), parent_code=parent, category=category,
                    balance_direction=direction, is_leaf=is_leaf)
                db.add(account)
                account_map[code] = account
            else:
                account.name, account.parent_code, account.category = name, parent, category
                account.balance_direction, account.is_leaf = direction, is_leaf
            if is_leaf:
                bal = balance_map.get(code)
                if not bal:
                    bal = AccountBalance(account_set_id=info["account_set_id"], period=info["period"],
                        account_code=code, aux_hash="SOURCE_SNAPSHOT")
                    db.add(bal)
                    balance_map[code] = bal
                bal.opening_debit, bal.opening_credit = values[0], values[1]
                bal.period_debit, bal.period_credit = values[2], values[3]

    elif info["document_type"] == "BALANCE_SHEET":
        for index, row in enumerate(rows[3:], 4):
            values = {
                "asset_item": _text(row[0]), "asset_line_no": _text(row[1]),
                "asset_close": float(_money(row[2])), "asset_open": float(_money(row[3])),
                "liab_item": _text(row[4]), "liab_line_no": _text(row[5]),
                "liab_close": float(_money(row[6])), "liab_open": float(_money(row[7])),
            }
            db.add(FinancialReportSnapshotRow(batch_id=batch.id, account_set_id=info["account_set_id"],
                period=info["period"], report_type="BALANCE_SHEET", row_no=index, values=values))
    elif info["document_type"] == "INCOME_STATEMENT":
        for index, row in enumerate(rows[3:], 4):
            values = {"item": _text(row[0]), "line_no": _text(row[1]),
                      "ytd_amount": float(_money(row[2])), "month_amount": float(_money(row[3]))}
            db.add(FinancialReportSnapshotRow(batch_id=batch.id, account_set_id=info["account_set_id"],
                period=info["period"], report_type="INCOME_STATEMENT", row_no=index, values=values))

    account_set = (await db.execute(select(AccountSet).where(AccountSet.id == info["account_set_id"]))).scalar_one()
    if info["period"] > account_set.current_period:
        account_set.current_period = info["period"]
    if commit:
        await db.commit()
    else:
        await db.flush()
    return {"status": "IMPORTED", "batch_id": batch.id, **info}


async def list_financial_imports(db: AsyncSession, account_set_id: str) -> list[dict]:
    batches = (await db.execute(select(FinancialImportBatch).where(
        FinancialImportBatch.account_set_id == account_set_id).order_by(FinancialImportBatch.period.desc(),
        FinancialImportBatch.imported_at.desc()))).scalars().all()
    return [{"id": b.id, "period": b.period, "source_filename": b.source_filename,
             "source_sha256": b.source_sha256, "document_type": b.document_type,
             "status": b.status, "is_active": b.is_active,
             "validation_summary": b.validation_summary, "imported_at": b.imported_at.isoformat()} for b in batches]
