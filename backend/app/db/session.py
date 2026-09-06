"""Engine and session handling.

Handlers take a session through :func:`session_scope`, which commits on a clean
exit and rolls back on any exception. Nothing in this codebase calls
``session.commit()`` and then does more work — a half-committed auth operation
is the kind of state that is very hard to reason about after the fact.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import config

engine = create_engine(
    config.DATABASE_URL,
    pool_size=config.DB_POOL_SIZE,
    max_overflow=config.DB_MAX_OVERFLOW,
    pool_pre_ping=True,          # a recycled connection after a DB restart otherwise
                                 # fails the first request of every pooled connection
    pool_recycle=1800,
    echo=config.DB_ECHO,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False, future=True)


@contextmanager
def independent_scope() -> Iterator[Session]:
    """A transaction that survives the request failing.

    ``session_scope`` rolls back when the handler raises, which is right for the
    handler's own writes and wrong for two kinds of security bookkeeping:

    * the brute-force counter — one that unwinds on every failed login counts
      nothing, so the lockout never triggers;
    * the audit trail — one that only records successes is not an audit trail.

    Both are recorded through here instead, on their own connection, so they are
    committed before the request is rejected.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
