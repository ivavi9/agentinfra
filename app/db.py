import logging
from typing import Dict, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger("db_pool")

try:
    from psycopg_pool import ConnectionPool
except ImportError:
    ConnectionPool = None  # type: ignore

_SHARED_POSTGRES_POOL: Any = None


def get_shared_postgres_pool(db_config: Dict[str, Any], max_size: int = 10) -> Any:
    """
    Returns a shared, consolidated singleton ConnectionPool instance.
    Prevents connection exhaustion across multiple agent graphs under HPA scale-out.
    """
    global _SHARED_POSTGRES_POOL

    if _SHARED_POSTGRES_POOL is not None:
        return _SHARED_POSTGRES_POOL

    if ConnectionPool is None:
        logger.warning("psycopg_pool.ConnectionPool unavailable.")
        return None

    try:
        db_url = f"postgresql://{db_config['db_user']}:{db_config['db_password']}@{db_config['db_host']}:{db_config.get('db_port', 5432)}/{db_config['db_name']}"
        logger.info(
            f"Initializing consolidated singleton ConnectionPool (max_size={max_size})..."
        )
        _SHARED_POSTGRES_POOL = ConnectionPool(
            conninfo=db_url, max_size=max_size, open=True
        )
        return _SHARED_POSTGRES_POOL
    except Exception as e:
        logger.error(f"Failed to initialize consolidated ConnectionPool: {e}")
        return None


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

        try:
            self._pool = get_shared_postgres_pool(db_config, max_size=maxconn)
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
                "Database connection pool is uninitialized or psycopg_pool is unavailable."
            )
        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def close_all(self) -> None:
        """Closes all open connections in pool on shutdown."""
        if self._pool:
            if hasattr(self._pool, "close"):
                self._pool.close()
            self._pool = None
            logger.info("Database connection pool closed.")


db_pool = DatabasePoolSingleton()
