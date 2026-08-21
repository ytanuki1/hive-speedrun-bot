from discord.ext import tasks
import cache_manager
import logging

logger = logging.getLogger("scheduler")

@tasks.loop(minutes=30)
async def cache_refresh_loop():
    logger.info("定期キャッシュ更新を実行します...")
    await cache_manager.refresh_all()

async def run_initial_refresh():
    logger.info("初回キャッシュ更新を実行します...")
    await cache_manager.refresh_all()