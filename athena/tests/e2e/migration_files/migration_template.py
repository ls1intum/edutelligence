from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# NOTE: The revision ID and create_date will be dynamically replaced by the test script
revision: str = "{revision_id}"
down_revision: Union[str, None] = "1746440063036_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add a 'status' column to the modeling_feedbacks table."""
    op.add_column(
        "modeling_feedbacks",
        sa.Column("status", sa.String(length=50), nullable=True, server_default="new"),
    )


def downgrade() -> None:
    """Remove the 'status' column from the modeling_feedbacks table."""
    op.drop_column("modeling_feedbacks", "status")
