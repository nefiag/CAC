import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from backend.app.models import Voucher, VoucherEntry, AccountBalance
from backend.app.schemas import VoucherCreate, VoucherEntryIn
from backend.app.services.ledger_service import transition_voucher
from backend.app.services.migration_engine import inspect_xiaokuaiji_excel


class Result:
    def __init__(self, values): self.values = values
    def scalars(self): return self
    def all(self): return self.values
    def scalar_one_or_none(self): return self.values[0] if self.values else None


class FakeSession:
    def __init__(self, entries, balances): self.entries=entries; self.balances=balances; self.calls=0; self.commits=0
    async def execute(self, _query):
        self.calls += 1
        if self.calls == 1: return Result(self.entries)
        return Result([self.balances[self.calls - 2]])
    async def commit(self): self.commits += 1
    async def refresh(self, _obj): pass


@pytest.mark.asyncio
async def test_voucher_post_and_unpost_are_balance_reversible():
    voucher = Voucher(id='v1', account_set_id='s1', period='2026-11', voucher_word='记', voucher_no=1, voucher_date=date(2026,11,1), status='AUDITED')
    entries = [
        VoucherEntry(voucher_id='v1', line_no=1, account_code='1001', debit_amount=Decimal('100'), credit_amount=Decimal('0'), aux_hash=''),
        VoucherEntry(voucher_id='v1', line_no=2, account_code='4001', debit_amount=Decimal('0'), credit_amount=Decimal('100'), aux_hash=''),
    ]
    balances = [
        AccountBalance(account_set_id='s1', period='2026-11', account_code='1001', aux_hash='', period_debit=Decimal('0'), period_credit=Decimal('0')),
        AccountBalance(account_set_id='s1', period='2026-11', account_code='4001', aux_hash='', period_debit=Decimal('0'), period_credit=Decimal('0')),
    ]
    db = FakeSession(entries, balances)
    await transition_voucher(db, voucher, 'POST')
    assert voucher.status == 'POSTED'
    assert balances[0].period_debit == Decimal('100')
    assert balances[1].period_credit == Decimal('100')
    db.calls = 0
    await transition_voucher(db, voucher, 'UNPOST')
    assert voucher.status == 'AUDITED'
    assert balances[0].period_debit == Decimal('0')
    assert balances[1].period_credit == Decimal('0')


def workbook_bytes(voucher_credit=100):
    wb=openpyxl.Workbook(); ws=wb.active; ws.title='会计科目表'
    ws.append(['科目编码','科目名称','科目类别','余额方向']); ws.append(['1001','库存现金','资产','借']); ws.append(['4001','实收资本','权益','贷'])
    vp=wb.create_sheet('记账凭证'); vp.append(['日期','凭证字','凭证号','摘要','科目编码','借方金额','贷方金额'])
    vp.append(['2026-11-01','记',1,'投入','1001',100,0]); vp.append(['2026-11-01','记',1,'投入','4001',0,voucher_credit])
    buf=io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_migration_inspection_accepts_balanced_workbook():
    report=inspect_xiaokuaiji_excel(workbook_bytes())
    assert report['valid'] is True
    assert report['account_rows'] == 2 and report['voucher_count'] == 1 and report['voucher_rows'] == 2


def test_migration_inspection_rejects_unbalanced_workbook():
    report=inspect_xiaokuaiji_excel(workbook_bytes(90))
    assert report['valid'] is False
    assert any('借贷不平衡' in error for error in report['errors'])


def test_new_voucher_defaults_to_draft():
    payload = VoucherCreate(
        account_set_id="s1",
        period="2026-11",
        voucher_date=date(2026, 11, 1),
        entries=[VoucherEntryIn(summary="test", account_code="1001")],
    )
    assert payload.status == "DRAFT"
