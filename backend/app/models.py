import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Numeric,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def gen_uuid():
    return str(uuid.uuid4())


class AccountSet(Base):
    __tablename__ = "tenants_account_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    taxpayer_type: Mapped[str] = mapped_column(String(20), default="GENERAL")
    accounting_standard: Mapped[str] = mapped_column(String(30), default="SMALL_ENT_2013")
    start_period: Mapped[str] = mapped_column(String(7), default="2026-01")
    current_period: Mapped[str] = mapped_column(String(7), default="2026-11")
    code_rule: Mapped[str] = mapped_column(String(32), default="4-2-2-2")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AccountSetEnvironment(Base):
    """Separates immutable formal ledgers from writable trial ledgers.

    Kept in a companion table so existing production databases can be upgraded
    with ``create_all`` without altering the audited account-set table.
    """
    __tablename__ = "account_set_environments"

    account_set_id: Mapped[str] = mapped_column(
        ForeignKey("tenants_account_sets.id", ondelete="CASCADE"), primary_key=True
    )
    environment: Mapped[str] = mapped_column(String(16), default="FORMAL", index=True)
    parent_account_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants_account_sets.id"), nullable=True, index=True
    )
    write_policy: Mapped[str] = mapped_column(String(32), default="PROMOTION_ONLY")
    baseline_period: Mapped[str] = mapped_column(String(7), default="")
    baseline_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class LedgerBackupRecord(Base):
    """Auditable record for a physical backup made before a ledger mutation."""
    __tablename__ = "ledger_backup_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str | None] = mapped_column(
        ForeignKey("tenants_account_sets.id"), nullable=True, index=True
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    row_counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    restore_command: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="VERIFIED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LedgerChangeBatch(Base):
    """A versioned batch applied to a trial ledger and awaiting approval."""
    __tablename__ = "ledger_change_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(
        ForeignKey("tenants_account_sets.id"), index=True
    )
    batch_type: Mapped[str] = mapped_column(String(32), default="TRIAL_IMPORT")
    source_fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    evidence_manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    validation_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    backup_id: Mapped[str | None] = mapped_column(
        ForeignKey("ledger_backup_records.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LedgerPromotionRequest(Base):
    """Explicit two-step approval gate from trial to formal."""
    __tablename__ = "ledger_promotion_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    trial_account_set_id: Mapped[str] = mapped_column(
        ForeignKey("tenants_account_sets.id"), index=True
    )
    formal_account_set_id: Mapped[str] = mapped_column(
        ForeignKey("tenants_account_sets.id"), index=True
    )
    change_batch_id: Mapped[str] = mapped_column(
        ForeignKey("ledger_change_batches.id"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="AWAITING_EXPLICIT_CONFIRMATION", index=True
    )
    confirmation_digest: Mapped[str] = mapped_column(String(64), default="")
    formal_backup_id: Mapped[str | None] = mapped_column(
        ForeignKey("ledger_backup_records.id"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AccountSetSetting(Base):
    __tablename__ = "account_set_settings"
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), primary_key=True)
    voucher_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    display_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    backup_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "auth_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="ACCOUNTANT", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UserAccountSet(Base):
    __tablename__ = "auth_user_account_sets"
    __table_args__ = (UniqueConstraint("user_id", "account_set_id", name="uq_user_account_set"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), index=True)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id", ondelete="CASCADE"), index=True)


class UserSession(Base):
    __tablename__ = "auth_user_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("account_set_id", "contract_no", name="uq_contract_no"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    contract_no: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    counterparty_name: Mapped[str] = mapped_column(String(200), default="")
    direction: Mapped[str] = mapped_column(String(12), default="RECEIVABLE")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ContractPlan(Base):
    __tablename__ = "contract_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    settled_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    note: Mapped[str] = mapped_column(String(255), default="")


class ChartOfAccount(Base):
    __tablename__ = "chart_of_accounts"
    __table_args__ = (UniqueConstraint("account_set_id", "code", name="uq_account_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    pinyin_abbr: Mapped[str] = mapped_column(String(64), default="")
    parent_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(String(32), default="资产")
    balance_direction: Mapped[str] = mapped_column(String(10), default="DEBIT")
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True)
    aux_types: Mapped[list] = mapped_column(JSONB, default=list)


class ReaResource(Base):
    __tablename__ = "rea_resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    resource_type: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    linked_account_code: Mapped[str] = mapped_column(String(32))
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)


class ReaAgent(Base):
    __tablename__ = "rea_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    agent_type: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), index=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra_meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class ReaEvent(Base):
    __tablename__ = "rea_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    event_date: Mapped[date] = mapped_column(Date)
    duality_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_doc_type: Mapped[str] = mapped_column(String(32), default="MANUAL_VOUCHER")
    raw_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Voucher(Base):
    __tablename__ = "vouchers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    voucher_word: Mapped[str] = mapped_column(String(10), default="记")
    voucher_no: Mapped[int] = mapped_column(Integer, nullable=False)
    voucher_date: Mapped[date] = mapped_column(Date, nullable=False)
    attachment_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    rea_event_id: Mapped[str | None] = mapped_column(ForeignKey("rea_events.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entries: Mapped[list["VoucherEntry"]] = relationship(
        "VoucherEntry", back_populates="voucher", cascade="all, delete-orphan"
    )


class VoucherEntry(Base):
    __tablename__ = "voucher_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    voucher_id: Mapped[str] = mapped_column(ForeignKey("vouchers.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(String(255), default="")
    account_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    debit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    credit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    aux_dimensions: Mapped[dict] = mapped_column(JSONB, default=dict)
    aux_hash: Mapped[str] = mapped_column(String(64), default="")

    voucher: Mapped["Voucher"] = relationship("Voucher", back_populates="entries")


class AccountBalance(Base):
    __tablename__ = "account_balances"
    __table_args__ = (
        UniqueConstraint("account_set_id", "period", "account_code", "aux_hash", name="uq_bal_dim"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    account_code: Mapped[str] = mapped_column(String(32), index=True)
    aux_hash: Mapped[str] = mapped_column(String(64), default="")
    opening_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    opening_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    period_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    period_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_no: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="CNY")
    linked_account_code: Mapped[str] = mapped_column(String(32), default="100201")
    rea_resource_id: Mapped[str | None] = mapped_column(ForeignKey("rea_resources.id"), nullable=True)


class BankStatement(Base):
    __tablename__ = "bank_statements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    bank_account_id: Mapped[str] = mapped_column(ForeignKey("bank_accounts.id"), index=True)
    tx_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tx_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    bank_serial_no: Mapped[str] = mapped_column(String(128), default="")
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    counterparty_name: Mapped[str] = mapped_column(String(200), default="")
    counterparty_account: Mapped[str] = mapped_column(String(64), default="")
    raw_summary: Mapped[str] = mapped_column(Text, default="")
    ai_tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    matched_agent_id: Mapped[str | None] = mapped_column(ForeignKey("rea_agents.id"), nullable=True)
    suggested_account_code: Mapped[str] = mapped_column(String(32), default="1122")
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.8000"))
    rea_event_id: Mapped[str | None] = mapped_column(ForeignKey("rea_events.id"), nullable=True)
    voucher_id: Mapped[str | None] = mapped_column(ForeignKey("vouchers.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PARSED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinancialImportBatch(Base):
    __tablename__ = "financial_import_batches"
    __table_args__ = (
        UniqueConstraint("account_set_id", "source_sha256", name="uq_fin_import_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sheet_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(20), default="VALIDATED")
    validation_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FinancialSourceRow(Base):
    __tablename__ = "financial_source_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "sheet_name", "row_no", name="uq_fin_source_row"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("financial_import_batches.id", ondelete="CASCADE"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(128), default="")
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    row_kind: Mapped[str] = mapped_column(String(32), default="DATA")
    values: Mapped[list] = mapped_column(JSONB, default=list)


class FinancialBalanceSnapshot(Base):
    __tablename__ = "financial_balance_snapshots"
    __table_args__ = (
        UniqueConstraint("batch_id", "account_code", name="uq_fin_balance_row"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("financial_import_batches.id", ondelete="CASCADE"), index=True)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    source_row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(String(32), index=True)
    account_name: Mapped[str] = mapped_column(String(160), default="")
    opening_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    opening_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    period_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    period_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    ytd_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    ytd_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    closing_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    closing_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))


class FinancialReportSnapshotRow(Base):
    __tablename__ = "financial_report_snapshot_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_no", name="uq_fin_report_row"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("financial_import_batches.id", ondelete="CASCADE"), index=True)
    account_set_id: Mapped[str] = mapped_column(ForeignKey("tenants_account_sets.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    report_type: Mapped[str] = mapped_column(String(32), index=True)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    values: Mapped[dict] = mapped_column(JSONB, default=dict)
