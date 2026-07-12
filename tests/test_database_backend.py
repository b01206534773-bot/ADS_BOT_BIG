import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import database
from database import DB, normalize_query


def test_normalize_query_keeps_sqlite_placeholders():
    sql = "SELECT * FROM users WHERE user_id=?"
    assert normalize_query(sql, "sqlite") == sql


def test_normalize_query_rewrites_placeholders_for_postgres():
    sql = "SELECT * FROM users WHERE user_id=?"
    assert normalize_query(sql, "postgres") == "SELECT * FROM users WHERE user_id=%s"


def test_falls_back_to_sqlite_when_postgres_connection_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://bad:bad@localhost:5432/test")

    def raise_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(database.psycopg2, "connect", raise_error)

    db = DB(str(tmp_path / "fallback.db"))
    assert db.backend == "sqlite"
    assert db.conn is not None
    assert db.get_user(1) is None
