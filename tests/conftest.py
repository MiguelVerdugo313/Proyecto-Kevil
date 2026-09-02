import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Cada ejecución de las pruebas usa su propia carpeta de datos.
os.environ.setdefault("KEVIL_DATA_DIR", tempfile.mkdtemp(prefix="kevil-tests-"))

import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Base  # noqa: E402
from app.db import engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare():
    settings.ensure_dirs()
    init_db()
    yield


@pytest.fixture
def session():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
