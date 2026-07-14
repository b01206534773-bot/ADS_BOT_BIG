CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    custom_name TEXT,
    joined_at TEXT NOT NULL,
    is_removed INTEGER DEFAULT 0,
    subscription_until TEXT
);

CREATE TABLE IF NOT EXISTS redeem_codes (
    code TEXT PRIMARY KEY,
    label TEXT,
    duration_hours INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    used_by BIGINT,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS stats (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
