from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import get_settings

settings = get_settings()

# Sync engine on purpose: the dispense path relies on SELECT ... FOR UPDATE inside a
# real transaction, and sync sessions keep that easy to read and easy to test with
# threads. FastAPI runs `def` endpoints in a threadpool, so the API stays concurrent.
engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
