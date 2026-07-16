import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Iterable

import psycopg2
import psycopg2.extras


def normalize_database_url(dsn: str) -> str:
    dsn = (dsn or '').strip()
    if dsn.startswith('postgres://'):
        return 'postgresql://' + dsn[len('postgres://'):]
    return dsn


def normalize_query(query: str, backend: str) -> str:
    if backend == 'postgres':
        return query.replace('?', '%s')
    return query


class DB:
    def __init__(self, path: str):
        self.path = Path(path)
        self.backend = 'postgres' if os.environ.get('DATABASE_URL') else 'sqlite'
        self.conn = None
        self._connect()
        self.init()

    def _ensure_connection(self):
        """Reconnect if the connection has been closed or lost."""
        try:
            if self.backend == 'postgres':
                self.conn.cursor().execute('SELECT 1')
            else:
                self.conn.cursor().execute('SELECT 1')
        except Exception:
            print('DB connection lost, reconnecting…')
            try:
                self.conn.close()
            except Exception:
                pass
            self._connect()

    def _execute(self, query: str, params=()):
        self._ensure_connection()
        cursor = self.conn.cursor()
        cursor.execute(normalize_query(query, self.backend), params)
        return cursor

    def _fetchone(self, query: str, params=()):
        return self._execute(query, params).fetchone()

    def _fetchall(self, query: str, params=()):
        return self._execute(query, params).fetchall()

    def _connect(self):
        if self.backend == 'postgres':
            dsn = normalize_database_url(os.environ['DATABASE_URL'])
            connect_kwargs = {
                'cursor_factory': psycopg2.extras.RealDictCursor,
            }
            if 'sslmode=' not in dsn and 'sslrootcert=' not in dsn:
                connect_kwargs['sslmode'] = 'require'
            try:
                self.conn = psycopg2.connect(dsn, **connect_kwargs)
                print('Database backend: postgres')
            except Exception as exc:
                print(f'Postgres connection failed, falling back to SQLite: {exc}')
                self.backend = 'sqlite'
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.conn = sqlite3.connect(self.path, check_same_thread=False)
                self.conn.row_factory = sqlite3.Row
                print(f'Database backend: sqlite ({self.path})')
                return
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            print(f'Database backend: sqlite ({self.path})')

    def init(self):
        c = self.conn.cursor()
        if self.backend == 'postgres':
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                custom_name TEXT,
                joined_at TEXT NOT NULL,
                is_removed INTEGER DEFAULT 0,
                subscription_until TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                label TEXT,
                duration_hours INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                used_by BIGINT,
                used_at TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )''')
        else:
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                custom_name TEXT,
                joined_at TEXT NOT NULL,
                is_removed INTEGER DEFAULT 0,
                subscription_until TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                label TEXT,
                duration_hours INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                used_by INTEGER,
                used_at TEXT
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            )''')
        self.conn.commit()

    def now(self) -> str:
        return datetime.utcnow().isoformat(timespec='seconds')

    def add_user(self, user_id: int, username: str = '', first_name: str = ''):
        c = self.conn.cursor()
        if self.backend == 'postgres':
            c.execute(
                '''INSERT INTO users(user_id, username, first_name, joined_at, is_removed)
                   VALUES(%s,%s,%s,%s,0)
                   ON CONFLICT(user_id) DO UPDATE SET
                   username=EXCLUDED.username,
                   first_name=EXCLUDED.first_name''',
                (user_id, username or '', first_name or '', self.now())
            )
        else:
            c.execute(
                '''INSERT INTO users(user_id, username, first_name, joined_at, is_removed)
                   VALUES(?,?,?,?,0)
                   ON CONFLICT(user_id) DO UPDATE SET
                   username=excluded.username,
                   first_name=excluded.first_name''',
                (user_id, username or '', first_name or '', self.now())
            )
        self.conn.commit()

    def remove_user(self, user_id: int):
        self._execute('UPDATE users SET is_removed=1 WHERE user_id=?', (user_id,))
        self.conn.commit()

    def set_custom_name(self, user_id: int, name: str):
        self._execute('UPDATE users SET custom_name=? WHERE user_id=?', (name, user_id))
        self.conn.commit()

    def set_subscription_hours(self, user_id: int, hours: int):
        row = self.get_user(user_id)
        base = datetime.utcnow()

        if row and row['subscription_until'] and not row['is_removed']:
            try:
                current_until = datetime.fromisoformat(row['subscription_until'])
                if current_until > base:
                    base = current_until
            except Exception:
                pass

        until = base + timedelta(hours=hours)
        if self.backend == 'postgres':
            self._execute(
                '''INSERT INTO users(user_id, username, first_name, joined_at, is_removed, subscription_until)
                   VALUES(%s,%s,%s,%s,0,%s)
                   ON CONFLICT(user_id) DO UPDATE SET
                       subscription_until=EXCLUDED.subscription_until,
                       is_removed=0''',
                (user_id, '', '', self.now(), until.isoformat(timespec='seconds'))
            )
        else:
            self._execute(
                '''INSERT INTO users(user_id, username, first_name, joined_at, is_removed, subscription_until)
                   VALUES(?,?,?,?,0,?)
                   ON CONFLICT(user_id) DO UPDATE SET
                       subscription_until=excluded.subscription_until,
                       is_removed=0''',
                (user_id, '', '', self.now(), until.isoformat(timespec='seconds'))
            )
        self.conn.commit()
        return until

    def get_user(self, user_id: int):
        return self._fetchone('SELECT * FROM users WHERE user_id=?', (user_id,))

    def all_active_users(self) -> Iterable[sqlite3.Row]:
        return self._fetchall('SELECT * FROM users WHERE is_removed=0')

    def create_code(self, code: str, duration_hours: int, label: str = ''):
        self._execute(
            'INSERT INTO redeem_codes(code,label,duration_hours,created_at) VALUES(?,?,?,?)',
            (code, label, duration_hours, self.now())
        )
        self.conn.commit()

    def get_code(self, code: str):
        return self._fetchone('SELECT * FROM redeem_codes WHERE code=?', (code,))

    def use_code(self, code: str, user_id: int) -> Optional[int]:
        row = self.get_code(code)
        if not row or row['used_by']:
            return None
        self._execute(
            'UPDATE redeem_codes SET used_by=?, used_at=? WHERE code=?',
            (user_id, self.now(), code)
        )
        self.conn.commit()
        return int(row['duration_hours'])

    def inc(self, key: str, amount: int = 1):
        if self.backend == 'postgres':
            self._execute(
                'INSERT INTO stats(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=stats.value+%s',
                (key, amount, amount)
            )
        else:
            self._execute(
                'INSERT INTO stats(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=value+?',
                (key, amount, amount)
            )
        self.conn.commit()

    def get_stat(self, key: str) -> int:
        row = self._fetchone('SELECT value FROM stats WHERE key=?', (key,))
        return int(row['value']) if row else 0

    def list_recent_codes(self, limit: int = 10):
        return self._fetchall('SELECT * FROM redeem_codes ORDER BY created_at DESC LIMIT ?', (limit,))

    def counts(self):
        users = self._fetchone('SELECT COUNT(*) AS c FROM users WHERE is_removed=0')['c']
        removed = self._fetchone('SELECT COUNT(*) AS c FROM users WHERE is_removed=1')['c']
        codes = self._fetchone('SELECT COUNT(*) AS c FROM redeem_codes')['c']
        unused = self._fetchone('SELECT COUNT(*) AS c FROM redeem_codes WHERE used_by IS NULL')['c']
        return dict(
            users=users,
            removed=removed,
            codes=codes,
            unused=unused,
            requests=self.get_stat('requests')
        )


def is_subscribed(row) -> bool:
    if not row or row['is_removed']:
        return False
    if not row['subscription_until']:
        return False
    try:
        return datetime.fromisoformat(row['subscription_until']) > datetime.utcnow()
    except Exception:
        return False
