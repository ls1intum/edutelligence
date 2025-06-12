from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, mysql, sqlite

# BigInteger that autoincrements on SQLite as well
BigIntAI = (
    sa.BigInteger()
    .with_variant(sqlite.INTEGER(), "sqlite")
    .with_variant(mysql.BIGINT(), "mysql")
    .with_variant(postgresql.BIGINT(), "postgresql")
)

exercise_type_enum = sa.Enum("text", "programming", "modeling", name="exercise_type")


# Identifiers
revision: str = "1746440063036_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table(
        "exercise",
        sa.Column("id", BigIntAI, primary_key=True, autoincrement=True),
        sa.Column("lms_url", sa.String(), nullable=False, index=True),
        sa.Column("title", sa.String(), nullable=False, index=True),
        sa.Column("max_points", sa.Float(), nullable=False),
        sa.Column("bonus_points", sa.Float(), nullable=False),
        sa.Column("grading_instructions", sa.String()),
        sa.Column("problem_statement", sa.String()),
        sa.Column("grading_criteria", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("type", exercise_type_enum, nullable=False, index=True),
    )

    op.create_table(
        "structured_grading_criterion",
        sa.Column("id", BigIntAI, primary_key=True, autoincrement=True),
        sa.Column(
            "exercise_id",
            BigIntAI,
            sa.ForeignKey("exercise.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("instructions_hash", sa.String(), nullable=False),
        sa.Column("structured_grading_criterion", sa.JSON(), nullable=False),
    )

    op.create_table(
        "modeling_exercises",
        sa.Column(
            "id",
            BigIntAI,
            sa.ForeignKey("exercise.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("example_solution", sa.String()),
    )

    op.create_table(
        "text_exercises",
        sa.Column(
            "id",
            BigIntAI,
            sa.ForeignKey("exercise.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("example_solution", sa.String()),
    )

    op.create_table(
        "programming_exercises",
        sa.Column(
            "id",
            BigIntAI,
            sa.ForeignKey("exercise.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("programming_language", sa.String(), nullable=False),
        sa.Column("solution_repository_uri", sa.String(), nullable=False),
        sa.Column("template_repository_uri", sa.String(), nullable=False),
        sa.Column("tests_repository_uri", sa.String(), nullable=False),
    )

    op.create_table(
        "modeling_submissions",
        sa.Column("id", BigIntAI, primary_key=True, autoincrement=True),
        sa.Column("lms_url", sa.String(), nullable=False, index=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "exercise_id",
            BigIntAI,
            sa.ForeignKey("modeling_exercises.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    op.create_table(
        "text_submissions",
        sa.Column("id", BigIntAI, primary_key=True, autoincrement=True),
        sa.Column("lms_url", sa.String(), nullable=False, index=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column(
            "exercise_id",
            BigIntAI,
            sa.ForeignKey("text_exercises.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    op.create_table(
        "programming_submissions",
        sa.Column("id", BigIntAI, primary_key=True, autoincrement=True),
        sa.Column("lms_url", sa.String(), nullable=False, index=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("repository_uri", sa.String(), nullable=False),
        sa.Column(
            "exercise_id",
            BigIntAI,
            sa.ForeignKey("programming_exercises.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    common_feedback_cols = [
        sa.Column("id", BigIntAI, primary_key=True, autoincrement=True),
        sa.Column("lms_url", sa.String(), nullable=False, index=True),
        sa.Column("lms_id", sa.BigInteger()),
        sa.Column("title", sa.String()),
        sa.Column("description", sa.String()),
        sa.Column("credits", sa.Float(), nullable=False),
        sa.Column("structured_grading_instruction_id", sa.BigInteger()),
        sa.Column("is_graded", sa.Boolean(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column(
            "is_suggestion", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.UniqueConstraint("lms_id"),
    ]

    op.create_table(
        "modeling_feedbacks",
        *common_feedback_cols,
        sa.Column("element_ids", sa.JSON(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column(
            "exercise_id",
            BigIntAI,
            sa.ForeignKey("modeling_exercises.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "submission_id",
            BigIntAI,
            sa.ForeignKey("modeling_submissions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    op.create_table(
        "text_feedbacks",
        *common_feedback_cols,
        sa.Column("index_start", sa.Integer(), nullable=True),
        sa.Column("index_end", sa.Integer(), nullable=True),
        sa.Column(
            "exercise_id",
            BigIntAI,
            sa.ForeignKey("text_exercises.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "submission_id",
            BigIntAI,
            sa.ForeignKey("text_submissions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    op.create_table(
        "programming_feedbacks",
        *common_feedback_cols,
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column(
            "exercise_id",
            BigIntAI,
            sa.ForeignKey("programming_exercises.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "submission_id",
            BigIntAI,
            sa.ForeignKey("programming_submissions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:

    op.drop_table("programming_feedbacks")
    op.drop_table("text_feedbacks")
    op.drop_table("modeling_feedbacks")

    op.drop_table("programming_submissions")
    op.drop_table("text_submissions")
    op.drop_table("modeling_submissions")

    op.drop_table("programming_exercises")
    op.drop_table("text_exercises")
    op.drop_table("modeling_exercises")

    op.drop_table("structured_grading_criterion")
    op.drop_table("exercise")

    exercise_type_enum.drop(op.get_bind())
