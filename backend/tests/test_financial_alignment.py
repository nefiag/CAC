from decimal import Decimal

from backend.scripts.verify_latest_financial_alignment import compare_rows


def test_compare_rows_treats_equivalent_money_as_equal():
    source = [{"code": "1001", "opening_debit": Decimal("1.20")}]
    system = [{"code": "1001", "opening_debit": 1.2}]

    assert compare_rows(source, system, ("code", "opening_debit")) == []


def test_compare_rows_reports_field_and_row_count_mismatches():
    source = [
        {"item": "收入", "month_amount": Decimal("100.00")},
        {"item": "成本", "month_amount": Decimal("20.00")},
    ]
    system = [{"item": "收入", "month_amount": 99.99}]

    result = compare_rows(source, system, ("item", "month_amount"))

    assert result[0] == {"kind": "row_count", "source": 2, "system": 1}
    assert any(item.get("field") == "month_amount" for item in result)
    assert any(item.get("kind") == "missing_row" for item in result)
