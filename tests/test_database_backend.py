import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import normalize_query


def test_normalize_query_keeps_sqlite_placeholders():
    sql = "SELECT * FROM users WHERE user_id=?"
    assert normalize_query(sql, "sqlite") == sql


def test_normalize_query_rewrites_placeholders_for_postgres():
    sql = "SELECT * FROM users WHERE user_id=?"
    assert normalize_query(sql, "postgres") == "SELECT * FROM users WHERE user_id=%s"
