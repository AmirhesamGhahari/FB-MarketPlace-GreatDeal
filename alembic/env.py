import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# Ensure src/ is on the path so fb_marketplace_greatdeals can be imported by Alembic.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fb_marketplace_greatdeals.config import settings
from fb_marketplace_greatdeals.db.base import Base
from fb_marketplace_greatdeals.db.models import pipeline_tables, category, fb_listing_raw, fb_listing_classified, deal_alerts  # noqa: F401 — registers models with Base.metadata

config = context.config

# Override the placeholder URL in alembic.ini with the real one from .env.
config.set_main_option("sqlalchemy.url", str(settings.database_url))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_TRACKED_SCHEMAS = {None, "facebook"}


def _include_name(name, type_, parent_names):
    """Tell autogenerate which schemas to scan.

    None = the default (public) schema: categories, pipeline_runs.
    facebook = schema for fb_listings_raw, fb_listings_classified.
    """
    if type_ == "schema":
        return name in _TRACKED_SCHEMAS
    return True


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=_include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=_include_name,
        )
        with context.begin_transaction():
            # Several ECS tasks start at once and each runs `upgrade head`; serialise them
            # so a pending migration is applied once and the others then see it as done.
            connection.execute(text("SELECT pg_advisory_xact_lock(727274)"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
