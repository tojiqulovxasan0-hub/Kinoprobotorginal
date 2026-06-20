# handlers/admin_stat.py - Statistika va foydalanuvchilar ro'yxatini yuklash

import logging

from aiogram import Router, Bot, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile

from filters import IsAdmin
from database import (
    get_users_count, get_today_users_count,
    get_online_users_count, get_top_movies, get_all_users,
)
from utils import build_stat_text, build_users_txt
from keyboards import admin_main_kb, stat_kb

logger = logging.getLogger(__name__)
router = Router()


async def _send_stat(target: Message | CallbackQuery) -> None:
    try:
        total = await get_users_count()
        today = await get_today_users_count()
        online = await get_online_users_count()
        top = await get_top_movies(10)
        text = build_stat_text(total, today, online, top)

        if isinstance(target, Message):
            await target.answer(text, reply_markup=stat_kb())
        else:
            await target.message.edit_text(text, reply_markup=stat_kb())
    except Exception as exc:
        logger.error("_send_stat xatosi: %s", exc, exc_info=True)


@router.message(IsAdmin(), Command("stat"))
@router.message(IsAdmin(), F.text == "📊 Statistika")
async def cmd_stat(message: Message) -> None:
    await _send_stat(message)


@router.callback_query(IsAdmin(), F.data == "refresh_stat")
async def refresh_stat(call: CallbackQuery) -> None:
    try:
        await call.answer("🔄 Yangilanmoqda...")
        await _send_stat(call)
    except Exception as exc:
        logger.error("refresh_stat xatosi: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik.", show_alert=True)


@router.callback_query(IsAdmin(), F.data == "download_users")
async def download_users(call: CallbackQuery, bot: Bot) -> None:
    try:
        await call.answer("⏳ Fayl tayyorlanmoqda...")
        users = await get_all_users()
        content = build_users_txt(users)
        file = BufferedInputFile(content, filename="foydalanuvchilar.txt")
        await bot.send_document(
            chat_id=call.from_user.id,
            document=file,
            caption=f"📥 Jami <b>{len(users)}</b> ta foydalanuvchi.",
        )
    except Exception as exc:
        logger.error("download_users xatosi: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik.", show_alert=True)
