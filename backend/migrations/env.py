from alembic import context
from sqlalchemy import create_engine, pool
from app.core.config import Settings

if context.is_offline_mode():
    context.configure(url=Settings().database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(Settings().database_url, poolclass=pool.NullPool).connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
