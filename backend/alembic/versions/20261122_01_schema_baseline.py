"""Track the existing Coxiaoac schema under Alembic.

The first upgrade is intentionally idempotent so existing installations can
adopt migration tracking without recreating or deleting audited ledger data.
"""

from alembic import op

from app.models import Base

revision = "20261122_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # A baseline downgrade must never drop accounting data.
    pass
