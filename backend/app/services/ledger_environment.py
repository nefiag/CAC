from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AccountSetEnvironment


FORMAL = "FORMAL"
TRIAL = "TRIAL"


async def get_ledger_environment(db: AsyncSession, account_set_id: str) -> AccountSetEnvironment | None:
    return (
        await db.execute(
            select(AccountSetEnvironment).where(
                AccountSetEnvironment.account_set_id == account_set_id
            )
        )
    ).scalar_one_or_none()


async def require_trial_ledger(db: AsyncSession, account_set_id: str) -> AccountSetEnvironment:
    """Reject direct accounting mutations against a formal or unknown ledger."""
    environment = await get_ledger_environment(db, account_set_id)
    if not environment:
        raise ValueError("账套尚未登记正式/试算环境，禁止写入")
    if environment.environment != TRIAL or environment.write_policy != "TRIAL_WRITABLE":
        raise ValueError("正式账套已锁定；请在对应试算账套处理，明确确认后再提升")
    return environment

