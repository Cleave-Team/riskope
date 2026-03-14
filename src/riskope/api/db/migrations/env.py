import os
import re
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

host = os.environ.get("POSTGRES_HOST", "localhost")
port = os.environ.get("POSTGRES_PORT", "5432")
user = os.environ.get("POSTGRES_USER", "riskope")
password = os.environ.get("POSTGRES_PASSWORD", "riskope")
database = os.environ.get("POSTGRES_DATABASE", "riskope")

sync_url = f"postgresql://{user}:{password}@{host}:{port}/{database}"
config.set_main_option("sqlalchemy.url", sync_url)

from riskope.api.db.models import Base  # noqa: E402

target_metadata = Base.metadata


def _next_revision_id(context, revision, directives):
    if not directives:
        return

    script = directives[0]
    versions_dir = Path(config.get_main_option("script_location") or ".") / "versions"
    existing = sorted(int(m.group(1)) for f in versions_dir.glob("*.py") if (m := re.match(r"^(\d+)_", f.name)))
    next_id = str((existing[-1] + 1) if existing else 1).zfill(3)
    script.rev_id = next_id


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
            process_revision_directives=_next_revision_id,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
