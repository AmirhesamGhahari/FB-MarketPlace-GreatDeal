from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fb_marketplace_greatdeals.config import settings

engine = create_engine(
    str(settings.database_url),
    connect_args={"options": "-c timezone=America/Toronto"},
    pool_pre_ping=True,   # reconnect on stale connections
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
