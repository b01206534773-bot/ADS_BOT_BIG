"""
start.py - runs both the Telegram bot and the web dashboard concurrently
"""
import asyncio
import os
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).parent))

from dashboard.server import make_app, DASHBOARD_PORT

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')


def ensure_runtime_paths():
    Path('data').mkdir(exist_ok=True)
    Path('data/temp').mkdir(exist_ok=True)
    Path('proxies.txt').touch(exist_ok=True)


async def run_dashboard():
    app = make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', DASHBOARD_PORT)
    await site.start()
    print(f'Dashboard running on http://0.0.0.0:{DASHBOARD_PORT}')


async def run_bot():
    if not TOKEN:
        print('WARNING: TELEGRAM_BOT_TOKEN not set — bot will not start')
        return
    import main as bot_main
    await bot_main.dp.start_polling(
        bot_main.bot,
        allowed_updates=bot_main.dp.resolve_used_update_types(),
    )


async def main():
    ensure_runtime_paths()
    await asyncio.gather(
        run_dashboard(),
        run_bot(),
    )


if __name__ == '__main__':
    asyncio.run(main())
