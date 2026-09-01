"""Thin async-friendly wrapper around stdlib sqlite3.

sqlite3 connections are blocking and not meant to be shared across threads,
so every call opens a short-lived connection and runs it via
asyncio.to_thread — simplest correct option for a single-instance, low-QPS
tool like this (no need for SQLAlchemy or a connection pool).
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from core.config import DB_PATH

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _init_db_sync() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = _SCHEMA_PATH.read_text()
    conn = _connect()
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def _execute_sync(query: str, params: Sequence[Any] = ()) -> int:
    conn = _connect()
    try:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _executemany_sync(query: str, seq_of_params: Iterable[Sequence[Any]]) -> None:
    conn = _connect()
    try:
        conn.executemany(query, seq_of_params)
        conn.commit()
    finally:
        conn.close()


def _fetchone_sync(query: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    conn = _connect()
    try:
        return conn.execute(query, params).fetchone()
    finally:
        conn.close()


def _fetchall_sync(query: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    conn = _connect()
    try:
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


async def init_db() -> None:
    await asyncio.to_thread(_init_db_sync)


async def execute(query: str, params: Sequence[Any] = ()) -> int:
    """Run an INSERT/UPDATE/DELETE, return lastrowid."""
    return await asyncio.to_thread(_execute_sync, query, params)


async def executemany(query: str, seq_of_params: Iterable[Sequence[Any]]) -> None:
    await asyncio.to_thread(_executemany_sync, query, list(seq_of_params))


async def fetchone(query: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    return await asyncio.to_thread(_fetchone_sync, query, params)


async def fetchall(query: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return await asyncio.to_thread(_fetchall_sync, query, params)


async def get_setting(key: str, default: str | None = None) -> str | None:
    row = await fetchone("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    await execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


if __name__ == "__main__":
    # `python -m core.db.database` — safe, idempotent local init used in dev
    # and referenced by CLAUDE.md as always-safe-to-run.
    asyncio.run(init_db())
    print(f"Initialized {DB_PATH}")
