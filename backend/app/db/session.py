from functools import lru_cache

from sqlalchemy import create_engine

from app.core.config import Settings


@lru_cache(maxsize=8)
def engine_for(url: str):
    return create_engine(
        url, pool_pre_ping=True, hide_parameters=True, connect_args={"connect_timeout": 5}
    )


def engine():
    return engine_for(Settings().database_url)


def get_session():
    with engine().begin() as connection:
        yield connection
