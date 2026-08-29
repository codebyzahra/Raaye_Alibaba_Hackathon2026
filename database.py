"""SQLAlchemy database setup and models for RAaye.

Tables are created automatically via ``init_db()`` (called at FastAPI
startup).  Uses a local SQLite file only.
"""

import os
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'raaye.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(bind=engine)


# --- Models ---------------------------------------------------------------

class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    raw_text = Column(Text, nullable=False)
    normalized_text = Column(Text, nullable=False)
    source = Column(String(255), default="csv_upload")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    aspect_sentiments = relationship("AspectSentiment", back_populates="review", cascade="all, delete-orphan")
    actions = relationship("Action", back_populates="review", cascade="all, delete-orphan")


class AspectSentiment(Base):
    __tablename__ = "aspect_sentiments"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False)
    aspect = Column(String(255), nullable=False)
    sentiment = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    review = relationship("Review", back_populates="aspect_sentiments")


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False)
    action_type = Column(String(100), nullable=False)
    action_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    review = relationship("Review", back_populates="actions")
