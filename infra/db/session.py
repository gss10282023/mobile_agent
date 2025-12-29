# infra/db/session.py
from sqlalchemy.orm import declarative_base, sessionmaker
from .engine import engine

Base = declarative_base()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)
