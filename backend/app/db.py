import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./orchestrator.db")

# Render (and some providers) hand out postgres:// URLs; SQLAlchemy 2.x needs postgresql://.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
# Neon (serverless Postgres) drops idle connections, so a pooled connection can be dead by the
# time we reuse it — most often right after the free instance wakes from sleep. Without this,
# the first query after an idle stretch fails with "SSL connection has been closed unexpectedly"
# (a 500). pool_pre_ping checks each connection with a lightweight ping and transparently
# reconnects if it's dead; pool_recycle proactively retires connections older than 5 minutes.
# Both are harmless no-ops for local SQLite.
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=300,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
