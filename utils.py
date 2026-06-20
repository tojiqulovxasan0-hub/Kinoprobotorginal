# utils.py - Yordamchi funksiyalar

import logging
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from config import ONLINE_MINUTES
from database import get_all_channels

logger = logging.getLogger(__name__)


async def check_subscription(bot: Bot, user_id: int) -> list[str]:
    """
    Foydalanuvchining barcha majburiy kanallarga obunasini tekshiradi.
    Qaytaradi: obuna bo'lmagan kanallar ro'yxati (bo'sh bo'lsa — hammaga obuna).
    """
    channels = await get_all_channels()
    not_subbed: list[str] = []

    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status in ("left", "kicked"):
                not_subbed.append(channel)
        except TelegramForbiddenError:
            logger.warning("Bot %s kanalda admin emas yoki kirish yo'q — o'tkazib yuborildi.", channel)
        except TelegramBadRequest as exc:
            logger.warning("get_chat_member xatosi (%s): %s", channel, exc)
        except Exception as exc:
            logger.error("check_subscription (%s) kutilmagan xato: %s", channel, exc, exc_info=True)

    return not_subbed


def build_stat_text(total: int, today: int, online: int, top_movies: list[dict]) -> str:
    lines = [
        "📊 <b>Bot Statistikasi</b>\n",
        f"👥 Jami foydalanuvchilar: <b>{total}</b>",
        f"🆕 Bugun yangi: <b>{today}</b>",
        f"🟢 Online (oxirgi {ONLINE_MINUTES} daqiqa): <b>{online}</b>\n",
        "🏆 <b>Top-10 Ko'p Ko'rilgan Kinolar:</b>",
    ]
    if top_movies:
        for i, m in enumerate(top_movies, 1):
            lines.append(
                f"  {i}. <code>{m['kino_kod']}</code> — {m['kino_nomi']} "
                f"<i>({m['views_count']} ko'rishlar)</i>"
            )
    else:
        lines.append("  Hali birorta kino qo'shilmagan.")
    return "\n".join(lines)


def build_users_txt(users: list[dict]) -> bytes:
    lines = ["ID | Username | Ism-Familiya | Qo'shilgan sana\n", "-" * 60 + "\n"]
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(f"{u['user_id']} | {uname} | {u['full_name']} | {u['join_date'][:10]}\n")
    return "".join(lines).encode("utf-8")
