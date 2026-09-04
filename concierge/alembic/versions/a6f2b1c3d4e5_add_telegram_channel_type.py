"""add telegram to channel_type CHECK constraints

Revision ID: a6f2b1c3d4e5
Revises: 594ca7479bd7
Create Date: 2026-09-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6f2b1c3d4e5"
down_revision: Union[str, None] = "594ca7479bd7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every column that uses the VARCHAR-backed 'channel_type' enum and exists in
# the migrated schema. (messages.source_channel does NOT exist — the enum there
# is only in the SQLAlchemy metadata, not the DB.)
_CHANNEL_TYPE_COLUMNS = [
    ("channels", "type"),
    ("conversations", "channel_type"),
    ("reservations", "source_channel"),
    ("requests", "channel_type"),
]

_VALUES = ["webchat", "whatsapp", "sms", "voice", "instagram", "email"]


def _ensure_telegram_in_check(table: str, column: str, *, add: bool) -> None:
    """Add/remove 'telegram' from the enum CHECK on `table.column` — but only if
    a CHECK constraint actually exists.

    The alembic migrations render these columns as plain VARCHAR(32) with NO
    check constraint (verified against the live schema), so on migrated DBs this
    is a no-op and 'telegram' already inserts fine. The guard exists for dev DBs
    built via `create_all`, where SQLAlchemy DOES emit an enum CHECK that would
    otherwise reject the new value. The original constraint name is preserved.
    """
    values = list(_VALUES)
    if add:
        values.append("telegram")
        needs_fix = "con.def NOT LIKE '%telegram%'"
    else:
        needs_fix = "con.def LIKE '%telegram%'"
    # Escaped for embedding inside the plpgsql string literal ('' = one quote).
    values_sql = ", ".join(f"''{v}''" for v in values)

    op.execute(
        f"""
        DO $$
        DECLARE
            con record;
        BEGIN
            FOR con IN
                SELECT c.conname, pg_get_constraintdef(c.oid) AS def
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_attribute a ON a.attrelid = t.oid
                    AND a.attnum = ANY(c.conkey)
                WHERE n.nspname = 'public'
                  AND t.relname = '{table}'
                  AND a.attname = '{column}'
                  AND c.contype = 'c'
            LOOP
                IF {needs_fix} THEN
                    EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', con.conname);
                    EXECUTE format(
                        'ALTER TABLE {table} ADD CONSTRAINT %I '
                        'CHECK ({column} IN ({values_sql}))',
                        con.conname
                    );
                END IF;
            END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    for table, column in _CHANNEL_TYPE_COLUMNS:
        _ensure_telegram_in_check(table, column, add=True)


def downgrade() -> None:
    for table, column in _CHANNEL_TYPE_COLUMNS:
        _ensure_telegram_in_check(table, column, add=False)