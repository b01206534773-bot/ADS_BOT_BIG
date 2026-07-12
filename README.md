# ADS_BOT_BIG

## Supabase / Railway setup

- The project now supports PostgreSQL via the `DATABASE_URL` environment variable.
- A Supabase folder was added at [supabase](supabase) with local config and seed SQL.
- In Railway, add these variables:
  - `TELEGRAM_BOT_TOKEN`
  - `DATABASE_URL` = your Supabase Postgres connection string
  - `ADMIN_USER_IDS` (optional)
  - `BOT_NAME` (optional)
  - `SUPPORT_URL` (optional)