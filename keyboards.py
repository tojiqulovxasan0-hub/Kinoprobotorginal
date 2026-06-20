# keyboards.py - Barcha inline va reply klaviaturalar

from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


# ─────────────────────────────────────────────────────────────
# FOYDALANUVCHI
# ─────────────────────────────────────────────────────────────

def main_user_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="🎬 Kino Qidirish"))
    b.add(KeyboardButton(text="ℹ️ Yordam"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def subscribe_kb(channels: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        username = ch.lstrip("@")
        b.row(InlineKeyboardButton(
            text=f"➕ {ch} kanaliga obuna bo'ling",
            url=f"https://t.me/{username}",
        ))
    b.row(InlineKeyboardButton(text="✅ Obunani Tekshirish", callback_data="check_sub"))
    return b.as_markup()


# ─────────────────────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────────────────────

def admin_main_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="🎬 Kino Qo'shish"))
    b.add(KeyboardButton(text="🗑 Kino O'chirish"))
    b.add(KeyboardButton(text="📋 Kinolar Ro'yxati"))
    b.add(KeyboardButton(text="📢 Reklama Yuborish"))
    b.add(KeyboardButton(text="📊 Statistika"))
    b.add(KeyboardButton(text="⚙️ Kanallar Boshqaruvi"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def admin_channels_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="➕ Kanal Qo'shish"))
    b.add(KeyboardButton(text="➖ Kanal O'chirish"))
    b.add(KeyboardButton(text="📋 Kanallar Ro'yxati"))
    b.add(KeyboardButton(text="🔙 Orqaga"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def stat_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_stat"))
    b.row(InlineKeyboardButton(text="📥 Foydalanuvchilar (TXT)", callback_data="download_users"))
    return b.as_markup()


def cancel_kb() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="❌ Bekor Qilish"))
    return b.as_markup(resize_keyboard=True, one_time_keyboard=True)


def confirm_broadcast_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="✅ Ha, Yuborish", callback_data="confirm_broadcast"))
    b.add(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_broadcast"))
    b.adjust(2)
    return b.as_markup()
