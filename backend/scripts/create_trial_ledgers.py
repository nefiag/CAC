"""Create the two trial ledgers from the verified formal baselines.

This command deliberately refuses to overwrite an existing trial.  The caller
must provide a verified physical pg_dump made immediately before execution.
"""
import argparse
import asyncio
import hashlib
import json
import os
import uuid
from pathlib import Path

from sqlalchemy import select, text

from app.database import AsyncSessionLocal, engine
from app.models import (
    AccountSet,
    AccountSetEnvironment,
    LedgerBackupRecord,
    LedgerChangeBatch,
)


PAIRS = (
    ("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000101", "博士特电子科技（昆山）有限公司（试算）"),
    ("00000000-0000-0000-0000-000000000002", "00000000-0000-0000-0000-000000000102", "昆山宇天新能源科技有限公司（试算）"),
)


def mapped(trial_id: str, source_id: str) -> str:
    return str(uuid.uuid5(uuid.UUID(trial_id), source_id))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def insert_values(values: dict) -> dict:
    """Raw SQL text needs JSON/JSONB values serialized for asyncpg."""
    return {
        key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        for key, value in values.items()
    }


async def rows(db, sql: str, **params):
    return (await db.execute(text(sql), params)).mappings().all()


async def clone_pair(db, formal_id: str, trial_id: str, trial_name: str, backup_id: str):
    if await db.get(AccountSet, trial_id):
        raise RuntimeError(f"试算账套已存在，拒绝覆盖：{trial_id}")
    source = await db.get(AccountSet, formal_id)
    if not source:
        raise RuntimeError(f"正式账套不存在：{formal_id}")

    db.add(AccountSet(
        id=trial_id, company_name=trial_name, taxpayer_type=source.taxpayer_type,
        accounting_standard=source.accounting_standard, start_period=source.start_period,
        current_period=source.current_period, code_rule=source.code_rule,
    ))
    db.add(AccountSetEnvironment(
        account_set_id=trial_id, environment="TRIAL", parent_account_set_id=formal_id,
        write_policy="TRIAL_WRITABLE", baseline_period="2026-10",
    ))
    await db.flush()

    id_maps: dict[str, dict[str, str]] = {}
    direct_tables = {
        "chart_of_accounts": "id", "rea_resources": "id", "rea_agents": "id",
        "rea_events": "id", "vouchers": "id", "account_balances": "id",
        "bank_accounts": "id", "bank_statements": "id", "financial_import_batches": "id",
        "contracts": "id",
    }
    for table, id_col in direct_tables.items():
        found = await rows(db, f'SELECT "{id_col}" FROM {table} WHERE account_set_id=:sid', sid=formal_id)
        id_maps[table] = {row[id_col]: mapped(trial_id, row[id_col]) for row in found}

    # Clone one account-set settings row without sharing mutable JSON state.
    await db.execute(text("""
        INSERT INTO account_set_settings(account_set_id,voucher_rules,display_rules,backup_rules,updated_at)
        SELECT :tid,voucher_rules,display_rules,backup_rules,now()
        FROM account_set_settings WHERE account_set_id=:sid
    """), {"sid": formal_id, "tid": trial_id})

    async def clone_account_table(table: str, columns: list[str], transforms=None):
        transforms = transforms or {}
        source_rows = await rows(db, f"SELECT {','.join(columns)} FROM {table} WHERE account_set_id=:sid", sid=formal_id)
        for row in source_rows:
            values = dict(row)
            values["id"] = id_maps[table][row["id"]]
            values["account_set_id"] = trial_id
            for column, transform in transforms.items():
                values[column] = transform(row[column]) if row[column] else row[column]
            names = list(values)
            await db.execute(text(
                f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join(':'+n for n in names)})"
            ), insert_values(values))

    await clone_account_table("chart_of_accounts", ["id","account_set_id","code","name","pinyin_abbr","parent_code","level","category","balance_direction","is_leaf","aux_types"])
    await clone_account_table("rea_resources", ["id","account_set_id","resource_type","code","name","linked_account_code","attributes"])
    await clone_account_table("rea_agents", ["id","account_set_id","agent_type","code","name","tax_id","extra_meta"])
    await clone_account_table("rea_events", ["id","account_set_id","event_type","event_date","duality_group_id","source_doc_type","raw_payload","created_at"])
    await clone_account_table("vouchers", ["id","account_set_id","period","voucher_word","voucher_no","voucher_date","attachment_count","status","rea_event_id","created_at"], {
        "rea_event_id": lambda value: id_maps["rea_events"].get(value)
    })

    voucher_ids = id_maps["vouchers"]
    entry_count = 0
    if voucher_ids:
        entry_rows = await rows(db, "SELECT * FROM voucher_entries WHERE voucher_id = ANY(:ids)", ids=list(voucher_ids))
        entry_count = len(entry_rows)
        for row in entry_rows:
            values = dict(row); values["id"] = mapped(trial_id, row["id"]); values["voucher_id"] = voucher_ids[row["voucher_id"]]
            names = list(values)
            await db.execute(text(f"INSERT INTO voucher_entries ({','.join(names)}) VALUES ({','.join(':'+n for n in names)})"), insert_values(values))

    await clone_account_table("account_balances", ["id","account_set_id","period","account_code","aux_hash","opening_debit","opening_credit","period_debit","period_credit"])
    await clone_account_table("bank_accounts", ["id","account_set_id","bank_name","account_no","currency","linked_account_code","rea_resource_id"], {
        "rea_resource_id": lambda value: id_maps["rea_resources"].get(value)
    })
    await clone_account_table("bank_statements", ["id","account_set_id","bank_account_id","tx_fingerprint","tx_date","bank_serial_no","direction","amount","balance_after","counterparty_name","counterparty_account","raw_summary","ai_tags","matched_agent_id","suggested_account_code","confidence_score","rea_event_id","voucher_id","status","created_at"], {
        "bank_account_id": lambda value: id_maps["bank_accounts"].get(value),
        "tx_fingerprint": lambda value: hashlib.sha256(f"{trial_id}:{value}".encode()).hexdigest(),
        "matched_agent_id": lambda value: id_maps["rea_agents"].get(value),
        "rea_event_id": lambda value: id_maps["rea_events"].get(value),
        "voucher_id": lambda value: id_maps["vouchers"].get(value),
    })
    await clone_account_table("financial_import_batches", ["id","account_set_id","period","source_filename","source_sha256","document_type","sheet_name","status","validation_summary","is_active","imported_at"])

    batch_ids = id_maps["financial_import_batches"]
    child_tables = {
        "financial_source_rows": ["id","batch_id","sheet_name","row_no","row_kind","values"],
        "financial_balance_snapshots": ["id","batch_id","account_set_id","period","source_row_no","account_code","account_name","opening_debit","opening_credit","period_debit","period_credit","ytd_debit","ytd_credit","closing_debit","closing_credit"],
        "financial_report_snapshot_rows": ["id","batch_id","account_set_id","period","report_type","row_no","values"],
    }
    child_counts = {}
    for table, columns in child_tables.items():
        if not batch_ids:
            child_counts[table] = 0
            continue
        child_rows = await rows(db, f"SELECT {','.join(columns)} FROM {table} WHERE batch_id = ANY(:ids)", ids=list(batch_ids))
        child_counts[table] = len(child_rows)
        for row in child_rows:
            values = dict(row); values["id"] = mapped(trial_id, row["id"]); values["batch_id"] = batch_ids[row["batch_id"]]
            if "account_set_id" in values: values["account_set_id"] = trial_id
            names = list(values)
            await db.execute(text(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join(':'+n for n in names)})"), insert_values(values))

    await clone_account_table("contracts", ["id","account_set_id","contract_no","name","counterparty_name","direction","amount","start_date","end_date","status","note","created_at"])
    contract_ids = id_maps["contracts"]
    plan_count = 0
    if contract_ids:
        plan_rows = await rows(db, "SELECT * FROM contract_plans WHERE contract_id = ANY(:ids)", ids=list(contract_ids))
        plan_count = len(plan_rows)
        for row in plan_rows:
            values = dict(row); values["id"] = mapped(trial_id, row["id"]); values["contract_id"] = contract_ids[row["contract_id"]]
            names = list(values)
            await db.execute(text(f"INSERT INTO contract_plans ({','.join(names)}) VALUES ({','.join(':'+n for n in names)})"), insert_values(values))

    # Grant trial access to every user who can access its formal parent.
    grants = await rows(db, "SELECT user_id FROM auth_user_account_sets WHERE account_set_id=:sid", sid=formal_id)
    for grant in grants:
        await db.execute(text("INSERT INTO auth_user_account_sets(id,user_id,account_set_id) VALUES(:id,:uid,:tid) ON CONFLICT DO NOTHING"), {
            "id": mapped(trial_id, f"grant:{grant['user_id']}"), "uid": grant["user_id"], "tid": trial_id,
        })

    counts = {table: len(values) for table, values in id_maps.items()}
    counts.update(child_counts)
    counts["voucher_entries"] = entry_count
    counts["contract_plans"] = plan_count
    fingerprint = hashlib.sha256(json.dumps(counts, sort_keys=True).encode()).hexdigest()
    environment = await db.get(AccountSetEnvironment, trial_id)
    environment.baseline_fingerprint = fingerprint
    db.add(LedgerChangeBatch(
        account_set_id=trial_id, batch_type="BASELINE_CLONE",
        source_fingerprint=fingerprint, description="从正式账套复制截至2026-10的只读基准",
        evidence_manifest={"formal_account_set_id": formal_id, "row_counts": counts},
        validation_summary={"status": "BASELINE_CLONED", "promotion_allowed": False},
        status="VALIDATED", backup_id=backup_id,
    ))
    return counts


async def main(args):
    backup = Path(args.backup).resolve()
    if not backup.is_file() or backup.stat().st_size == 0:
        raise RuntimeError("前置数据库备份不存在或为空，拒绝变更")
    actual_sha = file_sha256(backup)
    if actual_sha != args.sha256.lower():
        raise RuntimeError("前置数据库备份 SHA-256 不匹配，拒绝变更")

    async with engine.begin() as connection:
        await connection.run_sync(__import__("app.models", fromlist=["Base"]).Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        backup_record = LedgerBackupRecord(
            operation="CREATE_TRIAL_LEDGERS",
            storage_path=args.record_path or str(backup), sha256=actual_sha,
            size_bytes=backup.stat().st_size, row_counts={},
            restore_command="docker compose -f docker-compose.prod.yml exec -T db pg_restore --clean --if-exists -U coxiaoac_user -d coxiaoac < BACKUP_FILE",
            status="VERIFIED",
        )
        db.add(backup_record); await db.flush()
        summary = {}
        try:
            for formal_id, trial_id, trial_name in PAIRS:
                summary[trial_id] = await clone_pair(db, formal_id, trial_id, trial_name, backup_record.id)
            backup_record.row_counts = summary
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    print(json.dumps({"status": "CREATED", "backup_sha256": actual_sha, "trials": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--record-path", default="")
    asyncio.run(main(parser.parse_args()))
