"""Alembic 遷移環境。連線字串取自應用程式設定(環境變數),
target_metadata 取自 app.core.db.Base,並匯入 app.models 以註冊所有 model。"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# 匯入 models 讓其 metadata 註冊到 Base(M0-1 尚無 model,之後陸續加入)
import app.models  # noqa: F401
from alembic import context
from app.core.config import settings
from app.core.db import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
