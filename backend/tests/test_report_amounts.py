from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.app.services import report_service


def account(code, direction, category="资产"):
    return SimpleNamespace(code=code, name=code, balance_direction=direction, category=category, is_leaf=True)


def balance(code, opening_debit=0, opening_credit=0, debit=0, credit=0):
    return SimpleNamespace(
        account_code=code,
        opening_debit=Decimal(str(opening_debit)),
        opening_credit=Decimal(str(opening_credit)),
        period_debit=Decimal(str(debit)),
        period_credit=Decimal(str(credit)),
    )


async def no_snapshot(*_args):
    return []


@pytest.mark.asyncio
async def test_income_statement_net_profit_amount(monkeypatch):
    coa = [account("5101", "CREDIT", "损益"), account("5401", "DEBIT", "损益"), account("5502", "DEBIT", "损益")]
    current = {
        "5101": balance("5101", credit=1000),
        "5401": balance("5401", debit=400),
        "5502": balance("5502", debit=100),
    }
    async def load(*_args):
        return coa, current, {}, {"5401": 400, "5502": 100}, {"5101": 1000}
    monkeypatch.setattr(report_service, "_snapshot_report", no_snapshot)
    monkeypatch.setattr(report_service, "_load_coa_and_balances", load)
    result = await report_service.build_income_statement(None, "set-a", "2026-11")
    net_profit = next(row for row in result["lines"] if row["line_no"] == 15)
    assert net_profit["month_amount"] == 500.0
    assert net_profit["ytd_amount"] == 500.0


@pytest.mark.asyncio
async def test_balance_sheet_assets_equal_liabilities_and_equity(monkeypatch):
    coa = [account("1001", "DEBIT"), account("3101", "CREDIT", "权益")]
    current = {
        "1001": balance("1001", opening_debit=100, debit=25),
        "3101": balance("3101", opening_credit=100, credit=25),
    }
    async def load(*_args):
        return coa, current, current, {"1001": 25}, {"3101": 25}
    monkeypatch.setattr(report_service, "_snapshot_report", no_snapshot)
    monkeypatch.setattr(report_service, "_load_coa_and_balances", load)
    result = await report_service.build_balance_sheet(None, "set-a", "2026-11")
    assert result["check"]["total_assets_close"] == 125.0
    assert result["check"]["total_liab_eq_close"] == 125.0
    assert result["check"]["is_balanced"] is True


@pytest.mark.asyncio
async def test_category_summary_debit_credit_totals_balance(monkeypatch):
    snapshot_rows = [
        SimpleNamespace(account_code="1001", account_name="现金", opening_debit=100, opening_credit=0,
                        period_debit=25, period_credit=0, ytd_debit=25, ytd_credit=0,
                        closing_debit=125, closing_credit=0),
        SimpleNamespace(account_code="3101", account_name="实收资本", opening_debit=0, opening_credit=100,
                        period_debit=0, period_credit=25, ytd_debit=0, ytd_credit=25,
                        closing_debit=0, closing_credit=125),
    ]
    class Result:
        def scalars(self): return self
        def all(self): return snapshot_rows
    class DB:
        async def execute(self, _query): return Result()
    result = await report_service.build_category_summary(DB(), "set-a", "2026-11")
    assert result["totals"]["closing_debit"] == 125
    assert result["totals"]["closing_credit"] == 125
    assert result["totals"]["is_balanced"] is True
