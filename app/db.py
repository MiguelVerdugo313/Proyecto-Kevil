"""Capa de base de datos (SQLite local)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base

engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Migración sencilla: añade las columnas nuevas a una base ya existente.

    SQLite admite ALTER TABLE ADD COLUMN, así que actualizar la aplicación no
    obliga a nadie a empezar de cero ni a instalar herramientas de migración.
    """
    from sqlalchemy import text

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            rows = connection.execute(text(f"PRAGMA table_info('{table.name}')")).fetchall()
            if not rows:
                continue
            existing = {row[1] for row in rows}
            for column in table.columns:
                if column.name in existing:
                    continue
                kind = column.type.compile(engine.dialect)
                default = "'{}'" if kind.upper() == "JSON" else "NULL"
                if column.default is not None and getattr(column.default, "arg", None) is not None:
                    arg = column.default.arg
                    if isinstance(arg, (int, float)) and not isinstance(arg, bool):
                        default = str(arg)
                    elif isinstance(arg, str):
                        default = f"'{arg}'"
                    elif isinstance(arg, bool):
                        default = "1" if arg else "0"
                connection.execute(
                    text(
                        f"ALTER TABLE {table.name} "
                        f"ADD COLUMN {column.name} {kind} DEFAULT {default}"
                    )
                )


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sesión con commit/rollback automático (para hilos de trabajo)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
