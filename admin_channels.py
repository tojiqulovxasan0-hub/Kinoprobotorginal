# handlers/admin_channels.py - Majburiy kanallar boshqaruvi

import logging

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from filters import IsAdmin
from database import add_channel, remove_channel, get_all_channels
from keyboards import admin_main_kb, admin_channels_kb, cancel_kb

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdmin())


class ChannelForm(StatesGroup):
    add = State()
    remove = State()


# ─── Menyu ────────────────────────────────────────────────────────────────────

@router.message(F.text == "⚙️ Kanallar Boshqaruvi")
async def channels_menu(message: Message) -> None:
    try:
        await message.answer("⚙️ <b>Kanallar Boshqaruvi</b>", reply_markup=admin_channels_kb())
    except Exception as exc:
        logger.error("channels_menu xatosi: %s", exc, exc_info=True)


@router.message(F.text == "🔙 Orqaga")
async def back_to_main(message: Message, state: FSMContext) -> None:
    try:
        await state.clear()
        await message.answer("🏠 Bosh menyu", reply_markup=admin_main_kb())
    except Exception as exc:
        logger.error("back_to_main xatosi: %s", exc, exc_info=True)


# ─── Kanal qo'shish ───────────────────────────────────────────────────────────

@router.message(F.text == "➕ Kanal Qo'shish")
async def channel_add_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(ChannelForm.add)
        await message.answer(
            "➕ Qo'shmoqchi bo'lgan kanal username'ini yuboring.\n"
            "Masalan: <code>@kanal_username</code>",
            reply_markup=cancel_kb(),
        )
    except Exception as exc:
        logger.error("channel_add_start xatosi: %s", exc, exc_info=True)


@router.message(StateFilter(ChannelForm.add))
async def channel_add_done(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=admin_channels_kb())
            return
        username = (message.text or "").strip()
        if not username:
            await message.answer("❌ Username bo'sh bo'lmasin. Qayta yuboring:")
            return
        success = await add_channel(username)
        await state.clear()
        if success:
            uname = username if username.startswith("@") else f"@{username}"
            await message.answer(
                f"✅ <b>{uname}</b> majburiy kanallarga qo'shildi.",
                reply_markup=admin_channels_kb(),
            )
        else:
            uname = username if username.startswith("@") else f"@{username}"
            await message.answer(
                f"⚠️ <b>{uname}</b> allaqachon ro'yxatda mavjud.",
                reply_markup=admin_channels_kb(),
            )
    except Exception as exc:
        logger.error("channel_add_done xatosi: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik yuz berdi.", reply_markup=admin_channels_kb())


# ─── Kanal o'chirish ──────────────────────────────────────────────────────────

@router.message(F.text == "➖ Kanal O'chirish")
async def channel_remove_start(message: Message, state: FSMContext) -> None:
    try:
        channels = await get_all_channels()
        if not channels:
            await message.answer("📭 Ro'yxat bo'sh.", reply_markup=admin_channels_kb())
            return
        text = "➖ O'chirmoqchi bo'lgan kanal username'ini yuboring.\n\n"
        text += "<b>Mavjud kanallar:</b>\n" + "\n".join(
            f"{i}. {ch}" for i, ch in enumerate(channels, 1)
        )
        await state.set_state(ChannelForm.remove)
        await message.answer(text, reply_markup=cancel_kb())
    except Exception as exc:
        logger.error("channel_remove_start xatosi: %s", exc, exc_info=True)


@router.message(StateFilter(ChannelForm.remove))
async def channel_remove_done(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=admin_channels_kb())
            return
        username = (message.text or "").strip()
        deleted = await remove_channel(username)
        await state.clear()
        uname = username if username.startswith("@") else f"@{username}"
        if deleted:
            await message.answer(
                f"✅ <b>{uname}</b> ro'yxatdan o'chirildi.",
                reply_markup=admin_channels_kb(),
            )
        else:
            await message.answer(
                f"❌ <b>{uname}</b> ro'yxatda topilmadi.",
                reply_markup=admin_channels_kb(),
            )
    except Exception as exc:
        logger.error("channel_remove_done xatosi: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik yuz berdi.", reply_markup=admin_channels_kb())


# ─── Kanallar ro'yxati ────────────────────────────────────────────────────────

@router.message(F.text == "📋 Kanallar Ro'yxati")
async def list_channels(message: Message) -> None:
    try:
        channels = await get_all_channels()
        if not channels:
            await message.answer("📭 Hali hech qanday kanal qo'shilmagan.", reply_markup=admin_channels_kb())
            return
        text = "📋 <b>Majburiy Kanallar:</b>\n\n" + "\n".join(
            f"{i}. {ch}" for i, ch in enumerate(channels, 1)
        )
        await message.answer(text, reply_markup=admin_channels_kb())
    except Exception as exc:
        logger.error("list_channels xatosi: %s", exc, exc_info=True)
