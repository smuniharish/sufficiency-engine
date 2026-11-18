"""The application's existing database layer: the starting point of eval 1."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

DATABASE = Path(__file__).with_name("app.sqlite3")


def connect(path: str | Path = DATABASE) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def migrate(path: str | Path = DATABASE) -> None:
    with closing(connect(path)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS tickets (id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
        )


if __name__ == "__main__":
    migrate()
    print("migrated", DATABASE)
