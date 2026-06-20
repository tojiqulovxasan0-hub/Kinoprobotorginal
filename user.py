# handlers/user.py - Oddiy foydalanuvchi: kino qidirish

import logging

from aiogram import Router, Bot, F
from aiogram.types import Message

from config import ADMIN_ID
from database import get_movie_by_kod, increment_views, get_all_channels
from utils import check_subscription
from keyboards import main_user_kb, subscribe_kb

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.text == "🎬 Kino Qidirish")
async def ask_movie_code(message: Message) -> None:
    try:
        await message.answer(
            "🎬 Kino kodini yozing:\nMasalan: <code>125</code>",
            reply_markup=main_user_kb(),
        )
    except Exception as exc:
        logger.error("ask_movie_code xatosi: %s", exc, exc_info=True)


@router.message(F.text.regexp(r"^\d+$"))
async def search_movie(message: Message, bot: Bot) -> None:
    """Foydalanuvchi raqam (kino kodi) yuborganda."""
    # Adminga bu handler ishlamasin (u FSM holatida yoki boshqa narsa kiritishi mumkin)
    if message.from_user.id == ADMIN_ID:
        return

    try:
        # Obuna tekshirish
        channels = await get_all_channels()
        if channels:
            not_subbed = await check_subscription(bot, message.from_user.id)
            if not_subbed:
                await message.answer(
                    "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>",
                    reply_markup=subscribe_kb(not_subbed),
                )
                return

        kino_kod = message.text.strip()
        movie = await get_movie_by_kod(kino_kod)

        if not movie:
            await message.answer(
                f"❌ <b>{kino_kod}</b> kodli kino topilmadi.\n"
                "Kino kodini to'g'ri kiritdingizmi?",
            )
            return

        await increment_views(kino_kod)

        caption = (
            f"🎬 <b>{movie['kino_nomi']}</b>\n\n"
            f"📝 {movie['kino_tavsifi']}\n\n"
            f"🔑 Kod: <code>{movie['kino_kod']}</code>\n"
            f"👁 Ko'rishlar: <b>{movie['views_count'] + 1}</b>"
        )

        await bot.send_video(
            chat_id=message.chat.id,
            video=movie["file_id"],
            caption=caption,
        )

    except Exception as exc:
        logger.error("search_movie xatosi: %s", exc, exc_info=True)
        await message.answer("❌ Xatolik yuz berdi. Qayta urinib ko'ring.")
