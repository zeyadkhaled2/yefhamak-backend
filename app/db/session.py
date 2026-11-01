from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# pool_pre_ping: Neon's free compute goes to sleep, so test each connection before using it.
# prepare_threshold=None: avoids prepared-statement errors behind Neon's connection pooler.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args={"prepare_threshold": None},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency: one database session per request, always closed afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
