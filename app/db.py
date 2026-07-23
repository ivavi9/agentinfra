import os
import logging
from typing import Dict, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger("db_pool")

try:
    import psycopg2
    from psycopg2 import pool
except ImportError:
    psycopg2 = None
    pool = None


class DatabasePoolSingleton:
    """
    Consolidated Database Connection Pool Singleton.
    Prevents connection exhaustion across multiple pods and agent graphs under HPA scaling.
    Caps max connections per pod to 10 (total 50 across 5 HPA replicas).
    """

    _instance: Optional["DatabasePoolSingleton"] = None
    _pool: Any = None

    def __new__(cls) -> "DatabasePoolSingleton":
        if cls._instance is None:
            cls._instance = super(DatabasePoolSingleton, cls).__new__(cls)
        return cls._instance

    def initialize(
        self, db_config: Dict[str, Any], minconn: int = 1, maxconn: int = 10
    ) -> None:
        """Initializes the thread-safe connection pool."""
        if self._pool is not None:
            return

        if not psycopg2 or not pool:
            logger.warning(
                "psycopg2 not installed — running with mock database pool fallback."
            )
            return

        try:
            self._pool = pool.ThreadedConnectionPool(
                minconn=minconn,
                maxconn=maxconn,
                host=db_config.get("host", os.getenv("POSTGRES_HOST", "localhost")),
                port=int(db_config.get("port", os.getenv("POSTGRES_PORT", 5432))),
                dbname=db_config.get("dbname", os.getenv("POSTGRES_DB", "agentinfra")),
                user=db_config.get("user", os.getenv("POSTGRES_USER", "postgres")),
                password=db_config.get(
                    "password", os.getenv("POSTGRES_PASSWORD", "postgres")
                ),
            )
            logger.info(
                f"Database connection pool initialized (min={minconn}, max={maxconn})."
            )
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL connection pool: {e}")
            self._pool = None

    @contextmanager
    def get_connection(self):
        """Context manager for acquiring and releasing pool connections."""
        if not self._pool:
            raise RuntimeError(
                "Database connection pool is uninitialized or psycopg2 is unavailable."
            )
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def close_all(self) -> None:
        """Closes all open connections in pool on shutdown."""
        if self._pool:
            self._pool.closeall()
            self._pool = None
            logger.info("Database connection pool closed.")


db_pool = DatabasePoolSingleton()
