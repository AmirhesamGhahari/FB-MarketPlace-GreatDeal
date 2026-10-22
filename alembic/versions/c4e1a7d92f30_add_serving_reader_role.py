"""add read-only role for the website API

Revision ID: c4e1a7d92f30
Revises: b680bfbae539
Create Date: 2026-10-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'c4e1a7d92f30'
down_revision: Union[str, None] = 'b680bfbae539'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROLE = "web_serving_tables_reader"


def upgrade() -> None:
    # The role gets no password here (it cannot log in until one is set with ALTER ROLE ... PASSWORD).
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} LOGIN;
            END IF;
        END
        $$
    """)
    # dbt creates this schema too; IF NOT EXISTS lets either side go first.
    op.execute("CREATE SCHEMA IF NOT EXISTS serving")
    op.execute(f"GRANT USAGE ON SCHEMA serving TO {ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA serving TO {ROLE}")
    # dbt drops and recreates tables on every run; this re-grants SELECT on each new table created by this user.
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA serving GRANT SELECT ON TABLES TO {ROLE}")


def downgrade() -> None:
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA serving REVOKE SELECT ON TABLES FROM {ROLE}")
    op.execute(f"DROP OWNED BY {ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {ROLE}")
