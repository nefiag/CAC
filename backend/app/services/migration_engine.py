import io
import pandas as pd
from decimal import Decimal, InvalidOperation
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import ChartOfAccount, Voucher, VoucherEntry
from ..schemas import VoucherCreate, VoucherEntryIn
from .ledger_service import create_voucher


def inspect_xiaokuaiji_excel(content: bytes) -> dict:
    errors, warnings = [], []
    try:
        xls = pd.ExcelFile(io.BytesIO(content))
    except Exception as exc:
        return {"valid": False, "errors": [f"无法读取 Excel：{exc}"], "warnings": [], "sheets": [], "account_rows": 0, "voucher_rows": 0, "voucher_count": 0}
    sheets = xls.sheet_names
    if "会计科目表" not in sheets: errors.append("缺少“会计科目表”工作表")
    account_rows = voucher_rows = voucher_count = 0
    account_codes = set()
    if "会计科目表" in sheets:
        df = pd.read_excel(xls, sheet_name="会计科目表")
        required = {"科目编码", "科目名称"}
        if not required.issubset(df.columns): errors.append("会计科目表缺少科目编码或科目名称列")
        else:
            clean = df.dropna(subset=["科目编码", "科目名称"])
            account_rows = len(clean); codes = clean["科目编码"].astype(str).str.strip()
            account_codes = set(codes)
            dup = sorted(codes[codes.duplicated()].unique())
            if dup: errors.append(f"科目编码重复：{', '.join(dup[:10])}")
    if "记账凭证" not in sheets:
        warnings.append("未包含“记账凭证”工作表，将只导入科目")
    else:
        df = pd.read_excel(xls, sheet_name="记账凭证")
        required = {"日期","凭证字","凭证号","摘要","科目编码","借方金额","贷方金额"}
        missing = required - set(df.columns)
        if missing: errors.append(f"记账凭证缺少列：{', '.join(sorted(missing))}")
        else:
            clean = df.dropna(subset=["日期","凭证号","科目编码"]); voucher_rows = len(clean)
            unknown = sorted(set(clean["科目编码"].astype(str).str.strip()) - account_codes)
            if unknown: errors.append(f"凭证使用了科目表中不存在的编码：{', '.join(unknown[:10])}")
            groups = clean.groupby(["日期","凭证字","凭证号"], dropna=False); voucher_count = len(groups)
            for key, group in groups:
                debit = pd.to_numeric(group["借方金额"], errors="coerce").fillna(0).sum()
                credit = pd.to_numeric(group["贷方金额"], errors="coerce").fillna(0).sum()
                if abs(float(debit-credit)) > .005 or float(debit) <= 0:
                    errors.append(f"凭证 {key[1]}-{key[2]}（{key[0]}）借贷不平衡")
                    if len(errors) >= 30: break
    return {"valid": not errors, "errors": errors, "warnings": warnings, "sheets": sheets,
            "account_rows": account_rows, "voucher_rows": voucher_rows, "voucher_count": voucher_count}


async def export_xiaokuaiji_compatible_excel(
    db: AsyncSession, account_set_id: str, period: str
) -> bytes:
    acc_res = await db.execute(
        select(ChartOfAccount)
        .where(ChartOfAccount.account_set_id == account_set_id)
        .order_by(ChartOfAccount.code)
    )
    accounts = acc_res.scalars().all()

    v_res = await db.execute(
        select(Voucher)
        .where(Voucher.account_set_id == account_set_id, Voucher.period == period)
        .order_by(Voucher.voucher_no)
    )
    vouchers = v_res.scalars().all()

    acc_rows = [
        {
            "科目编码": a.code,
            "科目名称": a.name,
            "科目类别": a.category,
            "余额方向": "借" if a.balance_direction == "DEBIT" else "贷",
            "辅助核算": ",".join(a.aux_types or []),
        }
        for a in accounts
    ]

    v_rows = []
    for v in vouchers:
        e_res = await db.execute(
            select(VoucherEntry)
            .where(VoucherEntry.voucher_id == v.id)
            .order_by(VoucherEntry.line_no)
        )
        for e in e_res.scalars().all():
            v_rows.append(
                {
                    "日期": v.voucher_date.strftime("%Y-%m-%d"),
                    "凭证字": v.voucher_word,
                    "凭证号": v.voucher_no,
                    "摘要": e.summary,
                    "科目编码": e.account_code,
                    "借方金额": float(e.debit_amount),
                    "贷方金额": float(e.credit_amount),
                }
            )

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame(acc_rows).to_excel(writer, sheet_name="会计科目表", index=False)
        pd.DataFrame(v_rows).to_excel(writer, sheet_name="记账凭证", index=False)
    buf.seek(0)
    return buf.read()


async def import_xiaokuaiji_excel(
    db: AsyncSession, account_set_id: str, content: bytes
) -> dict:
    inspection = inspect_xiaokuaiji_excel(content)
    if not inspection["valid"]:
        return {"status": "INVALID", **inspection}
    xls = pd.ExcelFile(io.BytesIO(content))
    imported_accounts = 0
    imported_vouchers = 0
    skipped_vouchers = 0

    if "会计科目表" in xls.sheet_names:
        df_acc = pd.read_excel(xls, sheet_name="会计科目表").dropna(subset=["科目编码", "科目名称"])
        for _, row in df_acc.iterrows():
            code = str(row["科目编码"]).strip()
            name = str(row["科目名称"]).strip()
            exist = await db.execute(
                select(ChartOfAccount).where(
                    ChartOfAccount.account_set_id == account_set_id,
                    ChartOfAccount.code == code,
                )
            )
            if not exist.scalar_one_or_none():
                direction = "DEBIT" if str(row.get("余额方向", "借")).strip() == "借" else "CREDIT"
                db.add(
                    ChartOfAccount(
                        account_set_id=account_set_id,
                        code=code,
                        name=name,
                        level=1 if len(code) == 4 else 2,
                        category=str(row.get("科目类别", "资产")).strip(),
                        balance_direction=direction,
                        is_leaf=True,
                    )
                )
                imported_accounts += 1

    await db.commit()
    if "记账凭证" in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name="记账凭证").dropna(subset=["日期", "凭证号", "科目编码"])
        for (raw_date, word, number), group in df.groupby(["日期", "凭证字", "凭证号"], dropna=False):
            voucher_date = pd.to_datetime(raw_date).date()
            period = voucher_date.strftime("%Y-%m")
            duplicate = (await db.execute(select(Voucher).where(
                Voucher.account_set_id == account_set_id, Voucher.period == period,
                Voucher.voucher_word == str(word).strip(), Voucher.voucher_no == int(number),
            ))).scalar_one_or_none()
            if duplicate:
                skipped_vouchers += 1; continue
            entries = []
            for _, row in group.iterrows():
                debit = pd.to_numeric(row.get("借方金额", 0), errors="coerce")
                credit = pd.to_numeric(row.get("贷方金额", 0), errors="coerce")
                entries.append(VoucherEntryIn(
                    summary=str(row.get("摘要", "")), account_code=str(row["科目编码"]).strip(),
                    debit_amount=Decimal(str(0 if pd.isna(debit) else debit)),
                    credit_amount=Decimal(str(0 if pd.isna(credit) else credit)),
                ))
            # 导入凭证保留待复核状态；原凭证号通过分组顺序可追溯，系统号避免并发冲突。
            await create_voucher(db, VoucherCreate(account_set_id=account_set_id, period=period,
                voucher_word=str(word).strip(), voucher_date=voucher_date, status="DRAFT", entries=entries))
            imported_vouchers += 1
    return {"status": "SUCCESS", "imported_accounts": imported_accounts,
            "imported_vouchers": imported_vouchers, "skipped_vouchers": skipped_vouchers, **inspection}
