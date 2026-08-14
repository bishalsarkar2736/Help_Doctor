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
    # disable_existing_loggers=False is the whole point of naming it.
    #
    # fileConfig defaults to True, which sets disabled = True on every logger
    # that already exists when it runs. Under pytest the conftest imports the
    # application and THEN runs `alembic upgrade head`, so every application
    # logger created at import time was silenced for the rest of the session:
    # logger.info() returned without emitting, and a test asserting on log
    # output failed for a reason nowhere near itself.
    #
    # It matters outside the tests too. Anything that migrates in the same
    # process it then serves from — a management command, a container that runs
    # migrations before handing over to the app, a REPL — loses application
    # logging entirely and silently.
    fileConfig(
        config.config_file_name,
        disable_existing_loggers=False,
    )

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
    #
    # MIGRATION FIRST, IN BOTH PAIRS.
    #
    # Under privilege separation the runtime connects as a restricted role that
    # cannot create a table, so migrations must NOT use DATABASE_URL. The
    # migration variables therefore win, and the runtime ones remain as the
    # fallback for environments that have not separated the roles — where both
    # names resolve to the same credential anyway.
    #
    # The test pair is checked before the deploy pair for the same reason it
    # always was: a test run must not be steered by whatever is in .env.
    existing_url = config.get_main_option("sqlalchemy.url")

    database_url = (
        os.getenv("TEST_MIGRATION_DATABASE_URL")
        or os.getenv("TEST_DATABASE_URL")
        or os.getenv("MIGRATION_DATABASE_URL")
        or os.getenv("DATABASE_URL")
    )

    if not database_url and (not existing_url or existing_url == PLACEHOLDER_URL):
        # settings.migration_database_url, not database_url: the same fallback
        # to the POSTGRES_* parts, but named for the job it is doing.
        database_url = get_settings().migration_database_url

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
