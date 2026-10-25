from pathlib import Path

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade():
    op.execute(Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"))


def downgrade():
    raise RuntimeError("Forward-only migrations preserve conversation evidence")
