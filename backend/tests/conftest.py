from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.db.base import Base


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:"
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(
        dbapi_connection,
        _connection_record,
    ) -> None:
        dbapi_connection.execute(
            "PRAGMA foreign_keys=ON"
        )

        # Your search service uses func.char_length().
        # SQLite does not provide that function by default.
        dbapi_connection.create_function(
            "char_length",
            1,
            len,
        )

    Base.metadata.create_all(engine)

    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    with TestingSession() as session:
        yield session

    Base.metadata.drop_all(engine)
    engine.dispose()