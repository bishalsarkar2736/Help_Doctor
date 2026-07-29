from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from app.db.base import Base
from app.models import *
import os

from app.config import get_settings



# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True
    )

    with context.begin_transaction():
        context.run_migrations()




PLACEHOLDER_URL = "driver://user:pass@localhost/dbname"


def run_migrations_online():
    # Precedence:
    #   1. explicit env vars (tests / deploys)
    #   2. a url already set on the config by the caller (e.g. conftest)
    #   3. the application settings, as a last resort for local runs
    existing_url = config.get_main_option("sqlalchemy.url")

    database_url = (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
    )

    if not database_url and (not existing_url or existing_url == PLACEHOLDER_URL):
        database_url = get_settings().database_url

    if database_url and "+asyncpg" in database_url:
        database_url = database_url.replace("+asyncpg", "+psycopg2")

    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    if database_url:
        # Escape % so ConfigParser interpolation doesn't choke on
        # url-encoded characters in the password (e.g. %24 for '$').
        config.set_main_option(
            "sqlalchemy.url",
            database_url.replace("%", "%%"),
        )

    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()
      

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
