# ADS_BOT_BIG — FB Boost Bot

A Telegram bot for managing Facebook ads (Arabic-language), with a built-in web admin dashboard.

## Stack

- **Python 3.12** + **aiogram 3** (Telegram bot framework)
- **aiohttp** (web dashboard server)
- **SQLite** (default local DB at `data/bot.db`) or **PostgreSQL** via `DATABASE_URL`
- **Redis** (optional FSM storage) via `REDIS_URL`; falls back to in-memory

## How to run

The workflow `Start application` runs `python start.py`, which starts both:
- The **Telegram bot** (polling)
- The **web dashboard** on port 5000

## Required secrets

| Secret | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |

## Optional environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | _(SQLite)_ | PostgreSQL connection string (e.g. Supabase) |
| `REDIS_URL` | _(MemoryStorage)_ | Redis URL for persistent FSM state |
| `ADMIN_USER_IDS` | _(none)_ | Comma-separated Telegram user IDs with admin access |
| `BOT_NAME` | `⚡ FB Boost Bot` | Display name shown in bot messages |
| `SUPPORT_URL` | `https://t.me/` | Support link shown in the bot menu |
| `PORT` | `5000` | Dashboard port |

## Project structure

- `main.py` — Bot handlers and dispatcher
- `start.py` — Entry point: runs bot + dashboard concurrently
- `database.py` — SQLite/Postgres DB wrapper
- `dashboard/` — aiohttp web admin dashboard
- `gates/` — Ad gate logic (standard, dark post, partnership)
- `services/` — Facebook API, BM card service, proxy manager, redeem codes
- `keyboards.py` — Telegram inline keyboard builders
- `states.py` — FSM state definitions
- `proxies.txt` — One proxy per line (`user:pass@host:port`)
- `data/` — Runtime data (SQLite DB, temp files)

## User preferences

- Keep existing project structure and stack.
