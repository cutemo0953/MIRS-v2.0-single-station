"""
PostgreSQL Database Manager for Neon
Provides same interface as SQLite DatabaseManager for seamless switching
"""
import os
import logging
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Try to import psycopg2
try:
    import psycopg2
    import psycopg2.extras
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    logger.warning("psycopg2 not installed, PostgreSQL support disabled")


class PostgresRowWrapper:
    """Wrapper to make psycopg2 rows behave like sqlite3.Row"""
    def __init__(self, row_dict):
        self._dict = row_dict or {}

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._dict.values())[key]
        return self._dict.get(key)

    def __iter__(self):
        return iter(self._dict.values())

    def keys(self):
        return self._dict.keys()

    def values(self):
        return self._dict.values()

    def items(self):
        return self._dict.items()

    def get(self, key, default=None):
        return self._dict.get(key, default)


class PostgresCursorWrapper:
    """Wrapper to make psycopg2 cursor behave like sqlite3 cursor"""
    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None
        self.rowcount = 0

    def execute(self, sql: str, params=None):
        # Convert SQLite-style ? placeholders to PostgreSQL %s
        pg_sql = sql.replace('?', '%s')

        # Handle CURRENT_TIMESTAMP for PostgreSQL
        pg_sql = pg_sql.replace('CURRENT_TIMESTAMP', 'NOW()')

        # Handle SQLite datetime() function
        if "datetime('now')" in pg_sql.lower():
            pg_sql = pg_sql.replace("datetime('now')", "NOW()")
            pg_sql = pg_sql.replace("DATETIME('now')", "NOW()")

        # Handle DATE('now')
        pg_sql = pg_sql.replace("DATE('now')", "CURRENT_DATE")
        pg_sql = pg_sql.replace("date('now')", "CURRENT_DATE")

        # Handle INTEGER PRIMARY KEY AUTOINCREMENT -> SERIAL
        # (not needed for queries, only for schema)

        try:
            if params:
                self._cursor.execute(pg_sql, params)
            else:
                self._cursor.execute(pg_sql)

            self.rowcount = self._cursor.rowcount

            # Try to get lastrowid for INSERT
            if pg_sql.strip().upper().startswith('INSERT') and 'RETURNING' not in pg_sql.upper():
                try:
                    # Try to get the last inserted id
                    self._cursor.execute("SELECT lastval()")
                    result = self._cursor.fetchone()
                    if result:
                        self.lastrowid = result[0]
                except:
                    pass
        except Exception as e:
            logger.error(f"PostgreSQL execute error: {e}\nSQL: {pg_sql}\nParams: {params}")
            raise

        return self

    def executemany(self, sql: str, params_list):
        pg_sql = sql.replace('?', '%s')
        for params in params_list:
            self.execute(pg_sql, params)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        # psycopg2.extras.RealDictCursor returns dict-like rows
        if hasattr(row, 'keys'):
            return PostgresRowWrapper(dict(row))
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [PostgresRowWrapper(dict(row)) if hasattr(row, 'keys') else row for row in rows]

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size else self._cursor.fetchmany()
        return [PostgresRowWrapper(dict(row)) if hasattr(row, 'keys') else row for row in rows]

    def close(self):
        self._cursor.close()


class PostgresConnectionWrapper:
    """Wrapper to make psycopg2 connection behave like sqlite3 connection"""
    def __init__(self, conn, no_close=False):
        self._conn = conn
        self._no_close = no_close

    def cursor(self):
        return PostgresCursorWrapper(
            self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        )

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if not self._no_close:
            self._conn.close()

    def execute(self, sql: str, params=None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, value):
        pass  # Ignore, we use RealDictCursor


class PostgresDatabaseManager:
    """PostgreSQL Database Manager - compatible interface with SQLite DatabaseManager"""

    _connection_pool = None

    def __init__(self, database_url: str = None):
        self.database_url = database_url or os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable not set")

        if not POSTGRES_AVAILABLE:
            raise ImportError("psycopg2 is required for PostgreSQL support")

        self.is_memory = False  # PostgreSQL is always persistent
        logger.info(f"初始化 PostgreSQL 資料庫連接")

        # Test connection
        try:
            conn = self.get_connection()
            conn.close()
            logger.info("PostgreSQL 連接成功")
        except Exception as e:
            logger.error(f"PostgreSQL 連接失敗: {e}")
            raise

    def get_connection(self):
        """Get a PostgreSQL connection"""
        try:
            conn = psycopg2.connect(self.database_url)
            conn.autocommit = False
            return PostgresConnectionWrapper(conn)
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    def close_connection(self, conn):
        """Close connection"""
        if conn:
            try:
                conn.close()
            except:
                pass

    def init_database(self):
        """Initialize database - tables should already exist in Neon"""
        logger.info("PostgreSQL 資料庫已初始化 (使用 Neon)")
        pass

    # ========== Query Methods (same interface as SQLite) ==========

    def get_equipment(self) -> List[Dict]:
        """Get all equipment"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id, name, category, quantity, status,
                       last_check, power_level, remarks,
                       endurance_type, capacity_per_unit, capacity_unit,
                       tracking_mode, power_watts
                FROM equipment
                ORDER BY name
            """)
            return [dict(row._dict) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_inventory_items(self) -> List[Dict]:
        """Get all items with inventory"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT i.code, i.name, i.category, i.unit, i.min_stock,
                       COALESCE(SUM(inv.quantity), 0) as quantity
                FROM items i
                LEFT JOIN inventory inv ON i.code = inv.item_code
                GROUP BY i.code, i.name, i.category, i.unit, i.min_stock
                ORDER BY i.name
            """)
            return [dict(row._dict) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_blood_inventory(self) -> List[Dict]:
        """Get blood inventory"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT blood_type, quantity, updated_at
                FROM blood_inventory
                ORDER BY blood_type
            """)
            return [dict(row._dict) for row in cursor.fetchall()]
        finally:
            conn.close()


def get_database_manager():
    """
    Factory function to get appropriate database manager.
    Returns PostgresDatabaseManager if DATABASE_URL is set, otherwise None.
    """
    database_url = os.environ.get('DATABASE_URL')
    if database_url and POSTGRES_AVAILABLE:
        try:
            return PostgresDatabaseManager(database_url)
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL manager: {e}")
            return None
    return None
