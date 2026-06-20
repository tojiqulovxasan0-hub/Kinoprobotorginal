# handlers/common.py - /start, /help, obuna tekshirish

import logging

from aiogram import Router, Bot, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from config import ADMIN_ID
from database import get_all_channels
from utils import check_subscription
from keyboards import main_user_kb, admin_main_kb, subscribe_kb

logger = logging.getLogger(__name__)
router = Router()


# ─── Yordamchi ────────────────────────────────────────────────────────────────

async def _check_and_warn(message: Message, bot: Bot) -> bool:
    """
    True  → foydalanuvchi barcha kanallarga obuna (yoki kanallar yo'q).
    False → ogohlantirish xabari yuborildi.
    """
    channels = await get_all_channels()
    if not channels:
        return True

    not_subbed = await check_subscription(bot, message.from_user.id)
    if not_subbed:
        await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>",
            reply_markup=subscribe_kb(not_subbed),
        )
        return False
    return True


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    try:
        if not await _check_and_warn(message, bot):
            return

        if message.from_user.id == ADMIN_ID:
            await message.answer(
                f"👋 Xush kelibsiz, <b>Admin</b>!\nBot boshqaruvi paneliga xush kelibsiz.",
                reply_markup=admin_main_kb(),
            )
        else:
            await message.answer(
                f"👋 Salom, <b>{message.from_user.full_name}</b>!\n\n"
                "🎬 Kino kodini yozing — men kinoni yuboraman.\n"
                "Masalan: <code>125</code>",
                reply_markup=main_user_kb(),
            )
    except Exception as exc:
        logger.error("cmd_start xatosi: %s", exc, exc_info=True)


# ─── /help ────────────────────────────────────────────────────────────────────

@router.message(Command("help"))
@router.message(F.text == "ℹ️ Yordam")
async def cmd_help(message: Message, bot: Bot) -> None:
    try:
        if not await _check_and_warn(message, bot):
            return
        await message.answer(
            "ℹ️ <b>Yordam</b>\n\n"
            "🎬 Kino kodini yozing — bot kinoni yuboradi.\n"
            "Masalan: <code>125</code>\n\n"
            "❓ Muammolar bo'lsa admin bilan bog'laning.",
        )
    except Exception as exc:
        logger.error("cmd_help xatosi: %s", exc, exc_info=True)


# ─── Obuna tekshirish (callback) ──────────────────────────────────────────────

@router.callback_query(F.data == "check_sub")
async def check_sub_callback(call: CallbackQuery, bot: Bot) -> None:
    try:
        not_subbed = await check_subscription(bot, call.from_user.id)
        if not_subbed:
            await call.answer(
                "❌ Hali barcha kanallarga obuna bo'lmagansiz!",
                show_alert=True,
            )
            # Tugmalarni yangilash
            try:
                await call.message.edit_reply_markup(reply_markup=subscribe_kb(not_subbed))
            except Exception:
                pass
        else:
            await call.answer("✅ Obuna tasdiqlandi!", show_alert=True)
            try:
                await call.message.delete()
            except Exception:
                pass
            # Salomlashuv xabarini qayta yuborish
            if call.from_user.id == ADMIN_ID:
                await call.message.answer(
                    "👋 Xush kelibsiz, <b>Admin</b>!",
                    reply_markup=admin_main_kb(),
                )
            else:
                await call.message.answer(
                    "✅ Obuna tasdiqlandi! Endi kino kodini yuboring.\n"
                    "Masalan: <code>125</code>",
                    reply_markup=main_user_kb(),
                )
    except Exception as exc:
        logger.error("check_sub_callback xatosi: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik yuz berdi.", show_alert=True)
