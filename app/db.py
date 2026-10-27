# -*- coding: utf-8 -*-
"""
智析 FinSight AI —— 数据访问层
=====================================================================
设计要点：
1. 同时支持 MySQL（课程设计要求的技术栈）与 SQLite（本地零依赖演示）。
2. 上层业务代码统一使用 `%s` 占位符编写参数化 SQL，本模块在 SQLite 方言下
   自动转换为 `?`，从而避免 SQL 注入并屏蔽数据库差异。
3. 所有日期运算在 Python 侧完成，SQL 保持 ANSI 风格，两种数据库均可执行。
"""
from __future__ import annotations

import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from config import config

try:  # MySQL 驱动（未安装时自动降级为 SQLite 演示模式）
    import pymysql
    from pymysql.cursors import DictCursor

    HAS_PYMYSQL = True
except Exception:  # pragma: no cover
    pymysql = None  # type: ignore
    DictCursor = None  # type: ignore
    HAS_PYMYSQL = False

_local = threading.local()


class DatabaseError(RuntimeError):
    """数据访问异常"""


# ---------------------------------------------------------------------------
# 方言处理
# ---------------------------------------------------------------------------
def dialect() -> str:
    """返回当前生效的数据库方言：mysql / sqlite"""
    if config.DB_DIALECT == "mysql" and not HAS_PYMYSQL:
        raise DatabaseError(
            "未安装 MySQL 驱动 PyMySQL。\n"
            "请执行：pip install pymysql\n"
            "或在 .env 中设置 DB_DIALECT=sqlite 使用本地演示数据库。"
        )
    return config.DB_DIALECT


def is_mysql() -> bool:
    return dialect() == "mysql"


def _adapt(sql: str) -> str:
    """按方言转换占位符。"""
    if is_mysql():
        return sql
    return re.sub(r"%s", "?", sql)


def _adapt_params(params: Optional[Sequence[Any]]) -> Sequence[Any]:
    if params is None:
        return ()
    return tuple(_normalize(v) for v in params)


def _normalize(value: Any) -> Any:
    """Python 值 -> 数据库可写入值。"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """数据库行 -> JSON 友好结构。"""
    result: Dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            result[key] = float(value)
        elif isinstance(value, (datetime, date)):
            result[key] = value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) \
                else value.strftime("%Y-%m-%d")
        elif isinstance(value, bytes):
            result[key] = value.decode("utf-8", "ignore")
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------
class Connection:
    """统一的连接包装，提供 query/execute 等便捷方法。"""

    def __init__(self, raw, mysql: bool):
        self.raw = raw
        self.is_mysql = mysql

    # -- 内部：游标 ---------------------------------------------------------
    @contextmanager
    def _cursor(self):
        if self.is_mysql:
            cur = self.raw.cursor(DictCursor)
        else:
            cur = self.raw.cursor()
        try:
            yield cur
        finally:
            cur.close()

    @staticmethod
    def _rows_to_dicts(cur, rows) -> List[Dict[str, Any]]:
        if rows is None:
            return []
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return [_normalize_row(r) for r in rows]  # MySQL DictCursor
        # SQLite：需要列名
        columns = [d[0] for d in (cur.description or [])]
        return [_normalize_row(dict(zip(columns, row))) for row in rows]

    # -- 查询 ---------------------------------------------------------------
    def query_all(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute(_adapt(sql), _adapt_params(params))
            return self._rows_to_dicts(cur, cur.fetchall())

    def query_one(self, sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Dict[str, Any]]:
        rows = self.query_all(sql, params)
        return rows[0] if rows else None

    def query_scalar(self, sql: str, params: Optional[Sequence[Any]] = None, default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if not row:
            return default
        for value in row.values():
            return default if value is None else value
        return default

    # -- 写入 ---------------------------------------------------------------
    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> int:
        """执行写操作，返回自增主键（无自增时返回受影响行数）。"""
        with self._cursor() as cur:
            cur.execute(_adapt(sql), _adapt_params(params))
            self.raw.commit()
            return int(cur.lastrowid or cur.rowcount or 0)

    def executemany(self, sql: str, seq_params: Iterable[Sequence[Any]]) -> int:
        data = [_adapt_params(p) for p in seq_params]
        if not data:
            return 0
        with self._cursor() as cur:
            cur.executemany(_adapt(sql), data)
            self.raw.commit()
            return cur.rowcount

    def affected(self, sql: str, params: Optional[Sequence[Any]] = None) -> int:
        """执行写操作，返回受影响行数。"""
        with self._cursor() as cur:
            cur.execute(_adapt(sql), _adapt_params(params))
            self.raw.commit()
            return int(cur.rowcount or 0)

    @contextmanager
    def transaction(self):
        """事务上下文：异常自动回滚。"""
        try:
            yield self
            self.raw.commit()
        except Exception:
            self.raw.rollback()
            raise

    def close(self) -> None:
        try:
            self.raw.close()
        except Exception:
            pass


def _create_connection() -> Connection:
    if is_mysql():
        raw = pymysql.connect(
            host=config.MYSQL_HOST,
            port=config.MYSQL_PORT,
            user=config.MYSQL_USER,
            password=config.MYSQL_PASSWORD,
            database=config.MYSQL_DATABASE,
            charset=config.MYSQL_CHARSET,
            autocommit=False,
            cursorclass=DictCursor,
        )
        return Connection(raw, mysql=True)

    # SQLite（本地演示）
    db_path = config.SQLITE_PATH
    from pathlib import Path

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(db_path, check_same_thread=False)
    raw.execute("PRAGMA foreign_keys = ON")
    return Connection(raw, mysql=False)


# ---------------------------------------------------------------------------
# 连接生命周期
# ---------------------------------------------------------------------------
def get_connection() -> Connection:
    """线程内复用连接；在 Flask 请求上下文中由 teardown 统一关闭。"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _create_connection()
        _local.conn = conn
    return conn


def close_connection(_exc: Optional[BaseException] = None) -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


# ---------------------------------------------------------------------------
# 快捷函数
# ---------------------------------------------------------------------------
def query_all(sql: str, params: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    return get_connection().query_all(sql, params)


def query_one(sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Dict[str, Any]]:
    return get_connection().query_one(sql, params)


def query_scalar(sql: str, params: Optional[Sequence[Any]] = None, default: Any = None) -> Any:
    return get_connection().query_scalar(sql, params, default)


def execute(sql: str, params: Optional[Sequence[Any]] = None) -> int:
    return get_connection().execute(sql, params)


def affected(sql: str, params: Optional[Sequence[Any]] = None) -> int:
    return get_connection().affected(sql, params)


def ping() -> Dict[str, Any]:
    """数据库连通性探测，供“系统状态”页展示。"""
    info: Dict[str, Any] = {"dialect": config.DB_DIALECT}
    try:
        conn = get_connection()
        one = conn.query_scalar("SELECT 1", default=None)
        info["connected"] = one == 1
        if is_mysql():
            row = conn.query_one("SELECT VERSION() AS v")
            info["version"] = (row or {}).get("v")
            info["database"] = config.MYSQL_DATABASE
            info["host"] = f"{config.MYSQL_HOST}:{config.MYSQL_PORT}"
        else:
            info["version"] = sqlite3.sqlite_version
            info["database"] = config.SQLITE_PATH
        tables = conn.query_all(
            "SELECT table_name AS t FROM information_schema.tables WHERE table_schema = %s"
            if is_mysql() else
            "SELECT name AS t FROM sqlite_master WHERE type = 'table'",
            (config.MYSQL_DATABASE,) if is_mysql() else None,
        )
        info["tables"] = sorted(r["t"] for r in tables if not str(r["t"]).startswith("sqlite_"))
    except Exception as exc:  # pragma: no cover
        info["connected"] = False
        info["error"] = str(exc)
    return info


# ---------------------------------------------------------------------------
# 日期工具（全部在 Python 侧完成，保证跨数据库一致）
# ---------------------------------------------------------------------------
def today() -> date:
    return date.today()


def add_months(d: date, months: int) -> date:
    """日期加 N 个月（月末自动收敛，如 1/31 + 1 月 = 2/28）。"""
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    day = d.day
    while day > 0:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return d


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    return None


def overdue_days(loan_date: Any, deadline: Any = None, months: Optional[int] = None,
                 ref: Optional[date] = None) -> int:
    """计算逾期天数：当前日期 - 约定还款日（未逾期返回 0 或负数）。"""
    ref = ref or today()
    deadline_date = parse_date(deadline) or add_months(
        parse_date(loan_date) or ref, months if months is not None else config.OVERDUE_MONTHS
    )
    return (ref - deadline_date).days


def fmt_date(value: Any) -> Optional[str]:
    d = parse_date(value)
    return d.strftime("%Y-%m-%d") if d else None


__all__ = [
    "Connection", "DatabaseError", "HAS_PYMYSQL", "add_months", "affected", "close_connection",
    "dialect", "execute", "fmt_date", "get_connection", "is_mysql", "overdue_days", "parse_date",
    "ping", "query_all", "query_one", "query_scalar", "today",
]
