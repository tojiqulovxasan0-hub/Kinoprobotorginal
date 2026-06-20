# main.py — Production-ready bot ishga tushirish

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database import init_db
from middlewares import UserTrackerMiddleware
from handlers import common, user, admin_movie, admin_broadcast, admin_channels, admin_stat

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Ortiqcha debug log larni o'chirish
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(UserTrackerMiddleware())
    dp.callback_query.middleware(UserTrackerMiddleware())

    # Tartib muhim: admin handlerlari foydalanuvchi handlerlaridan oldin
    dp.include_router(common.router)          # /start, /help, obuna
    dp.include_router(admin_stat.router)      # /stat, statistika
    dp.include_router(admin_channels.router)  # kanal boshqaruvi
    dp.include_router(admin_movie.router)     # kino CRUD (FSM)
    dp.include_router(admin_broadcast.router) # reklama (FSM)
    dp.include_router(user.router)            # kino qidirish — eng oxirida

    return dp


# ─── Asosiy ───────────────────────────────────────────────────────────────────

async def main() -> None:
    # Ma'lumotlar bazasini ishga tushirish
    await init_db()

    # Session — timeout va keep-alive sozlamalari
    session = AiohttpSession()

    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    # Eski pending update larni tozalash
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as exc:
        logger.warning("delete_webhook xatosi (muhim emas): %s", exc)

    # Bot username ni logga chiqarish
    try:
        me = await bot.get_me()
        logger.info("✅ Bot ishga tushdi: @%s (ID: %d)", me.username, me.id)
    except Exception as exc:
        logger.error("Bot ma'lumotlarini olishda xato: %s", exc)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            polling_timeout=30,
        )
    except asyncio.CancelledError:
        logger.info("Polling bekor qilindi.")
    except Exception as exc:
        logger.critical("Polling ishlamay to'xtadi: %s", exc, exc_info=True)
        raise
    finally:
        await bot.session.close()
        logger.info("Bot sessiyasi yopildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot Ctrl+C bilan to'xtatildi.")
    except SystemExit:
        pass
    except Exception as exc:
        logger.critical("Kutilmagan xato: %s", exc, exc_info=True)
        sys.exit(1)
