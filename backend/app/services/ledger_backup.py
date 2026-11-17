"""Verified physical PostgreSQL backups for every accounting mutation."""
import asyncio
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from ..database import AsyncSessionLocal, DATABASE_URL
from ..models import LedgerBackupRecord


def _pg_url() -> str:
    return DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


async def backup_before_mutation(account_set_id: str, operation: str) -> LedgerBackupRecord:
    backup_dir = Path(os.getenv("LEDGER_BACKUP_DIR", "/var/lib/coxiaoac/backups"))
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    safe_operation = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in operation)
    final_path = backup_dir / f"{timestamp}-{safe_operation}-{account_set_id[-6:]}.dump"
    temp_path = final_path.with_suffix(".dump.part")

    process = await asyncio.create_subprocess_exec(
        "pg_dump", "--format=custom", f"--dbname={_pg_url()}", f"--file={temp_path}",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"账务变更前备份失败，已拒绝写入：{stderr.decode(errors='replace')[-500:]}")
    if not temp_path.is_file() or temp_path.stat().st_size == 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("账务变更前备份为空，已拒绝写入")

    verify = await asyncio.create_subprocess_exec(
        "pg_restore", "--list", str(temp_path),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, verify_error = await verify.communicate()
    if verify.returncode != 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"账务变更前备份校验失败，已拒绝写入：{verify_error.decode(errors='replace')[-500:]}")
    temp_path.replace(final_path)

    digest = hashlib.sha256()
    with final_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    record = LedgerBackupRecord(
        account_set_id=account_set_id, operation=operation,
        storage_path=str(final_path), sha256=digest.hexdigest(),
        size_bytes=final_path.stat().st_size, row_counts={},
        restore_command="scripts/restore_ledger_backup.sh BACKUP_FILE",
        status="VERIFIED",
    )
    async with AsyncSessionLocal() as audit_db:
        audit_db.add(record)
        await audit_db.commit()
        await audit_db.refresh(record)
    return record

