from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class VoucherEntryIn(BaseModel):
    summary: str
    account_code: str
    debit_amount: Decimal = Decimal("0.00")
    credit_amount: Decimal = Decimal("0.00")
    aux_dimensions: Dict[str, Any] = Field(default_factory=dict)


class VoucherCreate(BaseModel):
    account_set_id: str
    period: str
    voucher_word: str = "记"
    voucher_date: date
    attachment_count: int = 0
    status: str = "DRAFT"
    entries: List[VoucherEntryIn]


class VoucherStatusUpdate(BaseModel):
    action: str


class AccountSetSettingsUpdate(BaseModel):
    voucher_rules: Dict[str, Any] = Field(default_factory=dict)
    display_rules: Dict[str, Any] = Field(default_factory=dict)
    backup_rules: Dict[str, Any] = Field(default_factory=dict)


class ContractIn(BaseModel):
    account_set_id: str
    contract_no: str
    name: str
    counterparty_name: str = ""
    direction: str = "RECEIVABLE"
    amount: Decimal = Decimal("0.00")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str = "ACTIVE"
    note: str = ""


class ContractPlanIn(BaseModel):
    due_date: date
    amount: Decimal
    settled_amount: Decimal = Decimal("0.00")
    note: str = ""


class StatementTagUpdate(BaseModel):
    suggested_account_code: Optional[str] = None
    matched_agent_id: Optional[str] = None
    counterparty_name: Optional[str] = None
    normalized_summary: Optional[str] = None
    status: Optional[str] = None


class ReverseVoucherRequest(BaseModel):
    account_set_id: str
    statement_ids: List[str]
    merge_mode: str = "ONE_TO_ONE"
    voucher_word: str = "记"
    voucher_date_strategy: str = "TX_DATE"
    overwrite_existing: bool = False
