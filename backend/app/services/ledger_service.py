import hashlib
import json
import calendar
from datetime import date
from decimal import Decimal
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import (
    ChartOfAccount,
    Voucher,
    VoucherEntry,
    AccountBalance,
    ReaEvent,
)
from ..schemas import VoucherCreate, VoucherEntryIn


def compute_aux_hash(aux_dimensions: dict) -> str:
    if not aux_dimensions:
        return ""
    canonical = json.dumps(aux_dimensions, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


async def create_voucher(
    db: AsyncSession, payload: VoucherCreate, rea_event_id: str | None = None
) -> Voucher:
    total_debit = sum((e.debit_amount for e in payload.entries), Decimal("0.00"))
    total_credit = sum((e.credit_amount for e in payload.entries), Decimal("0.00"))
    if total_debit != total_credit or total_debit == Decimal("0.00"):
        raise ValueError(f"凭证借贷不平衡或金额为零: 借={total_debit}, 贷={total_credit}")

    res = await db.execute(
        select(func.coalesce(func.max(Voucher.voucher_no), 0)).where(
            Voucher.account_set_id == payload.account_set_id,
            Voucher.period == payload.period,
            Voucher.voucher_word == payload.voucher_word,
        )
    )
    next_no = res.scalar_one() + 1

    if not rea_event_id:
        event = ReaEvent(
            account_set_id=payload.account_set_id,
            event_type="MANUAL_JOURNAL",
            event_date=payload.voucher_date,
            source_doc_type="MANUAL_VOUCHER",
            raw_payload={"summary": payload.entries[0].summary if payload.entries else ""},
        )
        db.add(event)
        await db.flush()
        rea_event_id = event.id

    if payload.status not in {"DRAFT", "AUDITED", "POSTED"}:
        raise ValueError("凭证初始状态必须为 DRAFT、AUDITED 或 POSTED")

    voucher = Voucher(
        account_set_id=payload.account_set_id,
        period=payload.period,
        voucher_word=payload.voucher_word,
        voucher_no=next_no,
        voucher_date=payload.voucher_date,
        attachment_count=payload.attachment_count,
        status=payload.status,
        rea_event_id=rea_event_id,
    )
    db.add(voucher)
    await db.flush()

    for idx, item in enumerate(payload.entries, start=1):
        aux_hash = compute_aux_hash(item.aux_dimensions)
        entry = VoucherEntry(
            voucher_id=voucher.id,
            line_no=idx,
            summary=item.summary,
            account_code=item.account_code,
            debit_amount=item.debit_amount,
            credit_amount=item.credit_amount,
            aux_dimensions=item.aux_dimensions,
            aux_hash=aux_hash,
        )
        db.add(entry)
        if payload.status == "POSTED":
            await _update_account_balance(
                db, payload.account_set_id, payload.period, item.account_code,
                aux_hash, item.debit_amount, item.credit_amount,
            )

    await db.commit()
    await db.refresh(voucher)
    return voucher


async def transition_voucher(db: AsyncSession, voucher: Voucher, action: str) -> Voucher:
    transitions = {
        ("DRAFT", "AUDIT"): "AUDITED",
        ("AUDITED", "UNAUDIT"): "DRAFT",
        ("AUDITED", "POST"): "POSTED",
        ("POSTED", "UNPOST"): "AUDITED",
    }
    target = transitions.get((voucher.status, action.upper()))
    if not target:
        labels = {"DRAFT": "草稿", "AUDITED": "已审核", "POSTED": "已记账"}
        raise ValueError(f"{labels.get(voucher.status, voucher.status)}状态不能执行此操作")

    entries = (
        await db.execute(
            select(VoucherEntry).where(VoucherEntry.voucher_id == voucher.id)
            .order_by(VoucherEntry.line_no)
        )
    ).scalars().all()
    if action.upper() in {"POST", "UNPOST"}:
        sign = Decimal("1.00") if action.upper() == "POST" else Decimal("-1.00")
        for entry in entries:
            await _update_account_balance(
                db, voucher.account_set_id, voucher.period, entry.account_code,
                entry.aux_hash, entry.debit_amount * sign, entry.credit_amount * sign,
            )
    voucher.status = target
    await db.commit()
    await db.refresh(voucher)
    return voucher


async def _update_account_balance(
    db: AsyncSession,
    account_set_id: str,
    period: str,
    account_code: str,
    aux_hash: str,
    debit: Decimal,
    credit: Decimal,
):
    res = await db.execute(
        select(AccountBalance).where(
            AccountBalance.account_set_id == account_set_id,
            AccountBalance.period == period,
            AccountBalance.account_code == account_code,
            AccountBalance.aux_hash == aux_hash,
        )
    )
    bal = res.scalar_one_or_none()
    if not bal:
        bal = AccountBalance(
            account_set_id=account_set_id,
            period=period,
            account_code=account_code,
            aux_hash=aux_hash,
            opening_debit=Decimal("0.00"),
            opening_credit=Decimal("0.00"),
            period_debit=Decimal("0.00"),
            period_credit=Decimal("0.00"),
        )
        db.add(bal)
    bal.period_debit += debit
    bal.period_credit += credit


async def get_trial_balance(db: AsyncSession, account_set_id: str, period: str) -> list[dict]:
    accounts_res = await db.execute(
        select(ChartOfAccount)
        .where(ChartOfAccount.account_set_id == account_set_id)
        .order_by(ChartOfAccount.code)
    )
    accounts = accounts_res.scalars().all()

    bal_res = await db.execute(
        select(
            AccountBalance.account_code,
            func.sum(AccountBalance.opening_debit).label("od"),
            func.sum(AccountBalance.opening_credit).label("oc"),
            func.sum(AccountBalance.period_debit).label("pd"),
            func.sum(AccountBalance.period_credit).label("pc"),
        )
        .where(
            AccountBalance.account_set_id == account_set_id,
            AccountBalance.period == period,
        )
        .group_by(AccountBalance.account_code)
    )
    bal_map = {row.account_code: row for row in bal_res.all()}

    rows = []
    for acc in accounts:
        od = oc = pd = pc = Decimal("0.00")
        for code, b in bal_map.items():
            if code.startswith(acc.code):
                od += b.od or Decimal("0.00")
                oc += b.oc or Decimal("0.00")
                pd += b.pd or Decimal("0.00")
                pc += b.pc or Decimal("0.00")

        net = (od - oc) + (pd - pc)
        closing_debit = net if net > 0 else Decimal("0.00")
        closing_credit = -net if net < 0 else Decimal("0.00")

        rows.append(
            {
                "code": acc.code,
                "name": acc.name,
                "level": acc.level,
                "category": acc.category,
                "direction": acc.balance_direction,
                "opening_debit": float(od),
                "opening_credit": float(oc),
                "period_debit": float(pd),
                "period_credit": float(pc),
                "closing_debit": float(closing_debit),
                "closing_credit": float(closing_credit),
            }
        )
    return rows


async def carry_forward_pnl(db: AsyncSession, account_set_id: str, period: str) -> Voucher:
    """期末结转损益：将损益类科目余额结转至本年利润，生成一张平衡的"转"字凭证"""
    y, m = map(int, period.split("-"))
    voucher_date = date(y, m, calendar.monthrange(y, m)[1])

    # 幂等保护：本期已存在结转凭证则不再重复生成
    dup_res = await db.execute(
        select(VoucherEntry)
        .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
        .where(
            Voucher.account_set_id == account_set_id,
            Voucher.period == period,
            Voucher.voucher_word == "转",
            VoucherEntry.summary == "结转本期损益",
        )
    )
    if dup_res.scalars().first():
        raise ValueError("本期损益已结转，请勿重复操作")

    # 损益类末级科目当期余额
    coa_res = await db.execute(
        select(ChartOfAccount).where(
            ChartOfAccount.account_set_id == account_set_id,
            ChartOfAccount.category == "损益",
            ChartOfAccount.is_leaf == True,  # noqa: E712
        )
    )
    pnl_accounts = coa_res.scalars().all()

    bal_res = await db.execute(
        select(
            AccountBalance.account_code,
            func.sum(AccountBalance.opening_debit).label("od"),
            func.sum(AccountBalance.opening_credit).label("oc"),
            func.sum(AccountBalance.period_debit).label("pd"),
            func.sum(AccountBalance.period_credit).label("pc"),
        )
        .where(
            AccountBalance.account_set_id == account_set_id,
            AccountBalance.period == period,
        )
        .group_by(AccountBalance.account_code)
    )
    bal_map = {row.account_code: row for row in bal_res.all()}

    entries_in = []
    income_total = Decimal("0.00")   # 收入类净贷方（结转时借记）
    expense_total = Decimal("0.00")  # 费用类净借方（结转时贷记）

    for acc in pnl_accounts:
        b = bal_map.get(acc.code)
        if not b:
            continue
        net = (b.od or Decimal("0.00")) - (b.oc or Decimal("0.00")) + (b.pd or Decimal("0.00")) - (
            b.pc or Decimal("0.00")
        )
        if abs(net) < Decimal("0.01"):
            continue
        if net > 0:
            # 借方余额（费用）：贷记结转
            entries_in.append(
                VoucherEntryIn(summary=f"结转{acc.name}", account_code=acc.code, credit_amount=net)
            )
            expense_total += net
        else:
            # 贷方余额（收入）：借记结转
            entries_in.append(
                VoucherEntryIn(summary=f"结转{acc.name}", account_code=acc.code, debit_amount=-net)
            )
            income_total += -net

    net_profit = income_total - expense_total
    if not entries_in:
        raise ValueError("当期没有需要结转的损益发生额")

    # 本年利润科目：优先 4103，其次 3131
    coa_all = (
        await db.execute(
            select(ChartOfAccount.code).where(ChartOfAccount.account_set_id == account_set_id)
        )
    ).scalars().all()
    profit_code = "4103" if "4103" in coa_all else "3131"

    if net_profit >= 0:
        entries_in.append(
            VoucherEntryIn(summary="结转本期损益", account_code=profit_code, credit_amount=net_profit)
        )
    else:
        entries_in.append(
            VoucherEntryIn(
                summary="结转本期损益", account_code=profit_code, debit_amount=-net_profit
            )
        )

    payload = VoucherCreate(
        account_set_id=account_set_id,
        period=period,
        voucher_word="转",
        voucher_date=voucher_date,
        entries=entries_in,
    )
    return await create_voucher(db, payload, rea_event_id=None)
