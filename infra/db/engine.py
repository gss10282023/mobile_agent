# infra/db/engine.py
import os
from sqlalchemy import create_engine

# 优先 DATABASE_URL；否则按 docker-compose 的 db.env 组装
if "DATABASE_URL" in os.environ:
    DB_URL = os.environ["DATABASE_URL"]
else:
    user = os.getenv("POSTGRES_USER", "postgres")
    pwd  = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", os.getenv("DB_HOST", "localhost"))
    port = os.getenv("POSTGRES_PORT", "5432")
    db   = os.getenv("POSTGRES_DB", "eventsdb")
    DB_URL = f"postgresql+psycopg://{user}:{pwd}@{host}:{port}/{db}"

engine = create_engine(
    DB_URL,
    future=True,
    echo=os.getenv("SQL_ECHO", "0") == "1",
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
