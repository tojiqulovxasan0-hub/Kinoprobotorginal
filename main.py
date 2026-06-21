# ╔══════════════════════════════════════════════════════════════════╗
# ║         KINO BOT — To'liq versiya, xatosiz ishlaydigan          ║
# ╚══════════════════════════════════════════════════════════════════╝

import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter, Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, KeyboardButton, Message,
    ReplyKeyboardMarkup, TelegramObject,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
load_dotenv()

BOT_TOKEN: str      = os.getenv("BOT_TOKEN", "").strip()
_admin_raw: str     = os.getenv("ADMIN_ID", "").strip()
DB_PATH: str        = os.getenv("DB_PATH", "kino_bot.db")
ONLINE_MINUTES: int = int(os.getenv("ONLINE_MINUTES", "10"))
REFERRAL_BONUS: int = int(os.getenv("REFERRAL_BONUS", "100"))

if not BOT_TOKEN:
    sys.exit("❌ BOT_TOKEN .env faylida topilmadi!")
if not _admin_raw or not _admin_raw.isdigit():
    sys.exit("❌ ADMIN_ID .env faylida topilmadi!")

ADMIN_ID: int = int(_admin_raw)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)

# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id         INTEGER PRIMARY KEY,
                username        TEXT,
                full_name       TEXT,
                join_date       TEXT NOT NULL,
                last_active     TEXT NOT NULL,
                referrer_id     INTEGER DEFAULT NULL,
                balance         INTEGER DEFAULT 0,
                ref_count       INTEGER DEFAULT 0,
                is_registered   INTEGER DEFAULT 0
            )
        """)
        # Migration — eski ustunlar yo'q bo'lsa qo'shish
        for col, defval in [
            ("referrer_id",   "NULL"),
            ("balance",       "0"),
            ("ref_count",     "0"),
            ("is_registered", "0"),
        ]:
            try:
                await db.execute(
                    f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT {defval}"
                )
            except Exception:
                pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                kino_kod     TEXT UNIQUE NOT NULL,
                kino_nomi    TEXT NOT NULL,
                kino_tavsifi TEXT,
                file_id      TEXT NOT NULL,
                views_count  INTEGER DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username TEXT UNIQUE NOT NULL,
                channel_title    TEXT
            )
        """)
        try:
            await db.execute("ALTER TABLE channels ADD COLUMN channel_title TEXT")
        except Exception:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS support_admins (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL
            )
        """)

        # Pending referallar — bot restart bo'lsa ham saqlanadi
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pending_referrals (
                user_id     INTEGER PRIMARY KEY,
                referrer_id INTEGER NOT NULL,
                created_at  TEXT NOT NULL
            )
        """)

        await db.commit()
    logger.info("Ma'lumotlar bazasi ishga tushirildi.")


# ─── FOYDALANUVCHILAR ──────────────────────────────────────────

async def db_get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def db_user_exists(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None


async def db_create_user(user_id: int, username: str | None,
                          full_name: str, referrer_id: int | None) -> None:
    """Yangi foydalanuvchini yaratish (is_registered=0 — hali ro'yxatdan o'tmagan)."""
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users"
            " (user_id, username, full_name, join_date, last_active,"
            "  referrer_id, balance, ref_count, is_registered)"
            " VALUES (?,?,?,?,?,?,0,0,0)",
            (user_id, username, full_name, now, now, referrer_id),
        )
        await db.commit()


async def db_register_user(user_id: int, full_name: str) -> None:
    """Foydalanuvchini to'liq ro'yxatdan o'tkazish (ism kiritganidan keyin)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET full_name=?, is_registered=1 WHERE user_id=?",
            (full_name, user_id),
        )
        await db.commit()


async def db_update_last_active(user_id: int, username: str | None, full_name: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET username=?, full_name=?, last_active=? WHERE user_id=?",
            (username, full_name, now, user_id),
        )
        await db.commit()


async def db_add_referral_bonus(referrer_id: int) -> int:
    """Bonus berish, yangi balansni qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance=balance+?, ref_count=ref_count+1 WHERE user_id=?",
            (REFERRAL_BONUS, referrer_id),
        )
        await db.commit()
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (referrer_id,))
        row = await cur.fetchone()
        return row[0] if row else REFERRAL_BONUS


async def db_update_balance(user_id: int, amount: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id)
        )
        await db.commit()
        cur = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0


async def db_set_balance(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, user_id))
        await db.commit()


async def db_get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT user_id, username, full_name, join_date, balance, ref_count"
            " FROM users ORDER BY join_date DESC"
        )
        return [dict(r) for r in await cur.fetchall()]


async def db_get_users_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_registered=1")
        row = await cur.fetchone()
        return row[0] if row else 0


async def db_get_today_count() -> int:
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users WHERE is_registered=1 AND join_date LIKE ?",
            (f"{today}%",)
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def db_get_period_count(days: int) -> int:
    threshold = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users WHERE is_registered=1 AND join_date >= ?",
            (threshold,)
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def db_get_online_count() -> int:
    threshold = (datetime.now() - timedelta(minutes=ONLINE_MINUTES)).isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users WHERE last_active >= ?", (threshold,)
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def db_get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE is_registered=1")
        return [r[0] for r in await cur.fetchall()]


async def db_get_top_referrers(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT user_id, username, full_name, ref_count, balance"
            " FROM users WHERE is_registered=1"
            " ORDER BY ref_count DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def db_get_user_refs_today(user_id: int) -> int:
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users"
            " WHERE referrer_id=? AND is_registered=1 AND join_date LIKE ?",
            (user_id, f"{today}%"),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def db_get_user_refs_period(user_id: int, days: int) -> int:
    threshold = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users"
            " WHERE referrer_id=? AND is_registered=1 AND join_date >= ?",
            (user_id, threshold),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


async def db_search_user(query: str) -> dict | None:
    """ID yoki username orqali qidirish."""
    if query.isdigit():
        return await db_get_user(int(query))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE LOWER(username)=LOWER(?)", (query.lstrip("@"),)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


# ─── PENDING REFERALLAR (bazada) ──────────────────────────────

async def db_set_pending_ref(user_id: int, referrer_id: int) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO pending_referrals (user_id, referrer_id, created_at)"
            " VALUES (?,?,?)",
            (user_id, referrer_id, now),
        )
        await db.commit()


async def db_pop_pending_ref(user_id: int) -> int | None:
    """Pending refalani olish va o'chirish."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT referrer_id FROM pending_referrals WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        if row:
            await db.execute(
                "DELETE FROM pending_referrals WHERE user_id=?", (user_id,)
            )
            await db.commit()
            return row[0]
        return None

# ─── KINOLAR ──────────────────────────────────────────────────

async def db_add_movie(kod: str, nom: str, tavsif: str, file_id: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO movies (kino_kod, kino_nomi, kino_tavsifi, file_id)"
                " VALUES (?,?,?,?)",
                (kod, nom, tavsif, file_id),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def db_get_movie(kod: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM movies WHERE kino_kod=?", (kod,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def db_increment_views(kod: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE movies SET views_count=views_count+1 WHERE kino_kod=?", (kod,)
        )
        await db.commit()


async def db_delete_movie(kod: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM movies WHERE kino_kod=?", (kod,))
        await db.commit()
        return cur.rowcount > 0


async def db_get_all_movies() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT kino_kod, kino_nomi, kino_tavsifi, views_count FROM movies ORDER BY id DESC"
        )
        return [dict(r) for r in await cur.fetchall()]


async def db_get_top_movies(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT kino_kod, kino_nomi, views_count FROM movies"
            " ORDER BY views_count DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cur.fetchall()]


# ─── KANALLAR ─────────────────────────────────────────────────

def _norm_ch(username: str) -> str:
    username = username.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if username.lower().startswith(prefix):
            username = username[len(prefix):]
            break
    username = username.lstrip("@").strip().rstrip("/")
    return f"@{username}" if username else ""


async def db_add_channel(username: str, title: str = "") -> bool:
    username = _norm_ch(username)
    if not username:
        return False
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO channels (channel_username, channel_title) VALUES (?,?)",
                (username, title),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def db_remove_channel(username: str) -> bool:
    normed = _norm_ch(username)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM channels WHERE channel_username=?", (normed,)
        )
        if cur.rowcount == 0:
            cur = await db.execute(
                "DELETE FROM channels WHERE channel_username=?", (username,)
            )
        await db.commit()
        return cur.rowcount > 0


async def db_get_channels() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT channel_username, channel_title FROM channels")
        return [dict(r) for r in await cur.fetchall()]


# ─── YORDAMCHI ADMINLAR ───────────────────────────────────────

async def db_add_support(username: str) -> bool:
    username = username.strip().lstrip("@")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO support_admins (username) VALUES (?)", (username,)
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def db_remove_support(username: str) -> bool:
    username = username.strip().lstrip("@")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM support_admins WHERE username=?", (username,)
        )
        await db.commit()
        return cur.rowcount > 0


async def db_get_supports() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username FROM support_admins")
        return [r[0] for r in await cur.fetchall()]

# ═══════════════════════════════════════════════════════════════
# KLAVIATURALAR
# ═══════════════════════════════════════════════════════════════

def kb_main_user() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="🎬 Kino Qidirish"))
    b.add(KeyboardButton(text="👤 Profilim"))
    b.add(KeyboardButton(text="🔗 Referal Havola"))
    b.add(KeyboardButton(text="🏆 Reyting"))
    b.add(KeyboardButton(text="💬 Admin bilan bog'lanish"))
    b.add(KeyboardButton(text="ℹ️ Yordam"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def kb_admin_main() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="🎬 Kino Qo'shish"))
    b.add(KeyboardButton(text="🗑 Kino O'chirish"))
    b.add(KeyboardButton(text="📋 Kinolar Ro'yxati"))
    b.add(KeyboardButton(text="📢 Reklama Yuborish"))
    b.add(KeyboardButton(text="📊 Statistika"))
    b.add(KeyboardButton(text="⚙️ Kanallar"))
    b.add(KeyboardButton(text="👥 Foydalanuvchilar"))
    b.add(KeyboardButton(text="🏆 Reyting"))
    b.add(KeyboardButton(text="🛠 Yordamchi Adminlar"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def kb_admin_channels() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="➕ Kanal Qo'shish"))
    b.add(KeyboardButton(text="➖ Kanal O'chirish"))
    b.add(KeyboardButton(text="📋 Kanallar Ro'yxati"))
    b.add(KeyboardButton(text="🔙 Orqaga"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def kb_admin_users() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="🔍 Foydalanuvchi Izlash"))
    b.add(KeyboardButton(text="📥 Ro'yxat (TXT)"))
    b.add(KeyboardButton(text="🔙 Orqaga"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def kb_admin_support() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="➕ Admin Qo'shish"))
    b.add(KeyboardButton(text="➖ Admin O'chirish"))
    b.add(KeyboardButton(text="📋 Adminlar Ro'yxati"))
    b.add(KeyboardButton(text="🔙 Orqaga"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)


def kb_cancel() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="❌ Bekor Qilish"))
    return b.as_markup(resize_keyboard=True, one_time_keyboard=True)


def kb_subscribe(channels: list[dict]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        title = ch.get("channel_title") or ch["channel_username"]
        uname = ch["channel_username"].lstrip("@")
        b.row(InlineKeyboardButton(
            text=f"📢 {title} — Obuna bo'ling",
            url=f"https://t.me/{uname}",
        ))
    b.row(InlineKeyboardButton(
        text="✅ Obunani Tekshirish", callback_data="check_sub"
    ))
    return b.as_markup()


def kb_support_contact(supports: list[str]) -> InlineKeyboardMarkup:
    """Yordamchi adminlar bilan bog'lanish tugmalari."""
    b = InlineKeyboardBuilder()
    for s in supports:
        b.row(InlineKeyboardButton(
            text=f"💬 @{s} bilan bog'lanish",
            url=f"https://t.me/{s}",
        ))
    return b.as_markup()


def kb_stat() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_stat"))
    b.row(InlineKeyboardButton(text="📥 Foydalanuvchilar (TXT)", callback_data="download_users"))
    return b.as_markup()


def kb_broadcast_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="✅ Ha, Yuborish", callback_data="confirm_broadcast"))
    b.add(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_broadcast"))
    b.adjust(2)
    return b.as_markup()


def kb_user_manage(user_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="💰 Balans o'zgartirish", callback_data=f"ubal_{user_id}"
    ))
    b.row(InlineKeyboardButton(
        text="🔄 Balansni nolga tushirish", callback_data=f"uzero_{user_id}"
    ))
    b.row(InlineKeyboardButton(
        text="📊 Referal statistikasi", callback_data=f"uref_{user_id}"
    ))
    return b.as_markup()

# ═══════════════════════════════════════════════════════════════
# FILTR VA MIDDLEWARE
# ═══════════════════════════════════════════════════════════════

class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user.id == ADMIN_ID


class UserTrackerMiddleware(BaseMiddleware):
    """Har xabarda foydalanuvchini bazaga qo'shadi/yangilaydi."""
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, (Message, CallbackQuery)):
            user = event.from_user
        if user and not user.is_bot:
            try:
                exists = await db_user_exists(user.id)
                if exists:
                    await db_update_last_active(
                        user.id, user.username,
                        user.full_name or str(user.id)
                    )
            except Exception as exc:
                logger.error("UserTracker: %s", exc)
        return await handler(event, data)


class SubscriptionMiddleware(BaseMiddleware):
    """
    Har xabarda (admin va check_sub bundan mustasno):
    - Foydalanuvchi bazada bormi?
    - Ro'yxatdan o'tganmi (is_registered)?
    - Kanallarga obuna bo'lganmi?
    Agar yo'q bo'lsa — bloklaydi.
    """
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, (Message, CallbackQuery)):
            return await handler(event, data)

        user = event.from_user
        if not user or user.is_bot:
            return await handler(event, data)

        # Admin — hamma narsadan o'tadi
        if user.id == ADMIN_ID:
            return await handler(event, data)

        # /start — o'z handleri hal qiladi
        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        # check_sub callback — o'z handleri hal qiladi
        if isinstance(event, CallbackQuery) and event.data == "check_sub":
            return await handler(event, data)

        # FSM holatini tekshirish — ro'yxatdan o'tish jarayonida bloklama
        fsm_context: FSMContext | None = data.get("state")
        if fsm_context:
            try:
                current_state = await fsm_context.get_state()
                if current_state == RegisterForm.full_name.state:
                    # Foydalanuvchi ism yozayapti — o'tkazib yuborish
                    return await handler(event, data)
            except Exception:
                pass

        # Foydalanuvchi bazada bormi?
        try:
            u = await db_get_user(user.id)
        except Exception as exc:
            logger.error("SubMiddleware db_get_user: %s", exc)
            return await handler(event, data)

        # Bazada yo'q — /start bossin
        if not u:
            if isinstance(event, Message):
                await event.answer(
                    "👋 Botdan foydalanish uchun /start buyrug'ini bosing."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("❌ /start bosing!", show_alert=True)
            return

        # Ro'yxatdan o'tmagan — faqat FSM holatida emas bo'lsa bloklash
        if not u.get("is_registered"):
            # FSM holatini qayta tekshirish (fsm_context oldindan tekshirilgan)
            in_register = False
            if fsm_context:
                try:
                    current_state = await fsm_context.get_state()
                    if current_state and "RegisterForm" in str(current_state):
                        in_register = True
                except Exception:
                    pass
            if not in_register:
                if isinstance(event, Message):
                    await event.answer(
                        "⚠️ Ro'yxatdan o'tish tugallanmagan.\n"
                        "/start bosing va davom eting."
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer("❌ /start bosing!", show_alert=True)
                return

        # Majburiy kanallarni tekshirish
        try:
            channels = await db_get_channels()
        except Exception as exc:
            logger.error("SubMiddleware db_get_channels: %s", exc)
            return await handler(event, data)

        if not channels:
            return await handler(event, data)

        bot: Bot = data["bot"]
        not_subbed: list[dict] = []
        for ch in channels:
            try:
                member = await bot.get_chat_member(
                    chat_id=ch["channel_username"], user_id=user.id
                )
                if member.status in ("left", "kicked"):
                    not_subbed.append(ch)
            except TelegramForbiddenError:
                logger.warning("Bot %s da admin emas.", ch["channel_username"])
            except TelegramBadRequest as exc:
                logger.warning("get_chat_member (%s): %s", ch["channel_username"], exc)
            except Exception as exc:
                logger.error("SubMiddleware check (%s): %s", ch["channel_username"], exc)

        if not_subbed:
            if isinstance(event, Message):
                await event.answer(
                    "⚠️ <b>Botdan foydalanish uchun kanallarga obuna bo'ling:</b>\n\n"
                    "Obuna bo'lgach <b>«✅ Obunani Tekshirish»</b> tugmasini bosing.",
                    reply_markup=kb_subscribe(not_subbed),
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("❌ Avval kanallarga obuna bo'ling!", show_alert=True)
            return

        return await handler(event, data)


# ═══════════════════════════════════════════════════════════════
# YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════════

async def give_referral_bonus(bot: Bot, new_user_name: str, referrer_id: int) -> None:
    """Referal egasiga bonus berish va xabar yuborish."""
    try:
        new_bal = await db_add_referral_bonus(referrer_id)
        await bot.send_message(
            referrer_id,
            f"🎉 <b>{new_user_name}</b> sizning referal havolangiz orqali "
            f"ro'yxatdan o'tdi!\n"
            f"💰 Hisobingizga <b>+{REFERRAL_BONUS} so'm</b> qo'shildi.\n"
            f"💳 Umumiy balans: <b>{new_bal} so'm</b>",
        )
    except TelegramForbiddenError:
        pass
    except Exception as exc:
        logger.error("give_referral_bonus: %s", exc)


def build_stat_text(total: int, today: int, online: int,
                    week: int, month: int, top_movies: list[dict]) -> str:
    lines = [
        "📊 <b>Bot Statistikasi</b>\n",
        f"👥 Jami foydalanuvchilar: <b>{total}</b>",
        f"🆕 Bugun yangi: <b>{today}</b>",
        f"📅 1 hafta: <b>{week}</b>",
        f"📆 1 oy: <b>{month}</b>",
        f"🟢 Online (~{ONLINE_MINUTES} daqiqa): <b>{online}</b>\n",
        "🏆 <b>Top-10 Ko'rilgan Kinolar:</b>",
    ]
    if top_movies:
        for i, m in enumerate(top_movies, 1):
            lines.append(
                f"  {i}. <code>{m['kino_kod']}</code> — {m['kino_nomi']}"
                f" <i>({m['views_count']} marta)</i>"
            )
    else:
        lines.append("  Hali kino qo'shilmagan.")
    return "\n".join(lines)


def build_users_txt(users: list[dict]) -> bytes:
    lines = ["ID | Username | Ism-Familiya | Balans | Referallar | Qo'shilgan\n", "-"*72+"\n"]
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(
            f"{u['user_id']} | {uname} | {u['full_name']} |"
            f" {u.get('balance',0)} so'm | {u.get('ref_count',0)} | {u['join_date'][:10]}\n"
        )
    return "".join(lines).encode("utf-8")

# ═══════════════════════════════════════════════════════════════
# FSM HOLATLARI
# ═══════════════════════════════════════════════════════════════

class RegisterForm(StatesGroup):
    full_name = State()   # Foydalanuvchi ism-familiyasini kiritadi

class AddMovieForm(StatesGroup):
    kod    = State()
    nom    = State()
    tavsif = State()
    video  = State()

class DeleteMovieForm(StatesGroup):
    kod = State()

class ChannelForm(StatesGroup):
    add_username = State()
    add_title    = State()
    remove       = State()

class BroadcastForm(StatesGroup):
    waiting = State()
    confirm = State()

class SupportForm(StatesGroup):
    add    = State()
    remove = State()

class UserSearchForm(StatesGroup):
    waiting = State()

class UserBalanceForm(StatesGroup):
    waiting = State()

# ═══════════════════════════════════════════════════════════════
# ROUTERLAR
# ═══════════════════════════════════════════════════════════════
admin_router = Router()
user_router  = Router()

# ═══════════════════════════════════════════════════════════════
# /start  —  RO'YXATDAN O'TISH + REFERAL
# ═══════════════════════════════════════════════════════════════

@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        user = message.from_user
        args = message.text.split()

        # Referal parametrini ajratib olish
        referrer_id: int | None = None
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                ref_id = int(args[1][4:])
                if ref_id != user.id:
                    ref_exists = await db_user_exists(ref_id)
                    if ref_exists:
                        referrer_id = ref_id
            except (ValueError, IndexError):
                pass

        if user.id == ADMIN_ID:
            await state.clear()
            await message.answer(
                "👋 Xush kelibsiz, <b>Admin</b>!\nBot boshqaruvi paneliga xush kelibsiz.",
                reply_markup=kb_admin_main(),
            )
            return

        # Foydalanuvchi bazada bormi?
        existing = await db_get_user(user.id)

        if existing and existing.get("is_registered"):
            # Allaqachon to'liq ro'yxatdan o'tgan — asosiy menyuga
            channels = await db_get_channels()
            not_subbed: list[dict] = []
            for ch in channels:
                try:
                    member = await bot.get_chat_member(
                        chat_id=ch["channel_username"], user_id=user.id
                    )
                    if member.status in ("left", "kicked"):
                        not_subbed.append(ch)
                except Exception:
                    pass
            if not_subbed:
                await message.answer(
                    "⚠️ <b>Kanallarga obuna bo'ling:</b>",
                    reply_markup=kb_subscribe(not_subbed),
                )
            else:
                await message.answer(
                    f"👋 Yana xush kelibsiz, <b>{existing['full_name']}</b>!",
                    reply_markup=kb_main_user(),
                )
            return

        # Yangi foydalanuvchi yoki ro'yxatdan o'tmagan
        if not existing:
            await db_create_user(user.id, user.username,
                                 user.full_name or str(user.id), referrer_id)
            if referrer_id:
                await db_set_pending_ref(user.id, referrer_id)

        # Ism-familiya kiritish bosqichi
        await state.set_state(RegisterForm.full_name)
        await state.update_data(referrer_id=referrer_id)
        await message.answer(
            "👋 <b>Kino botiga xush kelibsiz!</b>\n\n"
            "Davom etish uchun iltimos <b>Ism-Familiyangizni</b> kiriting:\n\n"
            "<i>Masalan: Abdullayev Jasur</i>",
            reply_markup=kb_cancel(),
        )
    except Exception as exc:
        logger.error("cmd_start: %s", exc, exc_info=True)


@user_router.message(StateFilter(RegisterForm.full_name))
async def register_full_name(message: Message, state: FSMContext, bot: Bot) -> None:
    """Foydalanuvchi ism-familiyasini kiritadi."""
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer(
                "❌ Bekor qilindi.\n/start orqali qaytadan boshlashingiz mumkin."
            )
            return

        full_name = (message.text or "").strip()
        if len(full_name) < 3:
            await message.answer(
                "❌ Ism-familiya kamida 3 ta harf bo'lishi kerak. Qayta kiriting:"
            )
            return

        user = message.from_user

        # Bazada ro'yxatdan o'tkazish
        await db_register_user(user.id, full_name)
        await state.clear()

        # Majburiy kanallarni tekshirish
        channels = await db_get_channels()
        not_subbed: list[dict] = []
        for ch in channels:
            try:
                member = await bot.get_chat_member(
                    chat_id=ch["channel_username"], user_id=user.id
                )
                if member.status in ("left", "kicked"):
                    not_subbed.append(ch)
            except TelegramForbiddenError:
                logger.warning("Bot %s da admin emas.", ch["channel_username"])
            except Exception as exc:
                logger.error("register sub check (%s): %s",
                             ch["channel_username"], exc)

        if not_subbed:
            await message.answer(
                f"✅ <b>{full_name}</b>, ma'lumotlaringiz saqlandi!\n\n"
                "⚠️ <b>Botdan foydalanish uchun kanallarga obuna bo'ling:</b>\n\n"
                "Obuna bo'lgach <b>«✅ Obunani Tekshirish»</b> tugmasini bosing.",
                reply_markup=kb_subscribe(not_subbed),
            )
        else:
            # Kanallar yo'q yoki hammaga obuna — referal bonusini ber
            referrer_id = await db_pop_pending_ref(user.id)
            if referrer_id:
                await give_referral_bonus(bot, full_name, referrer_id)

            await message.answer(
                f"✅ <b>Ro'yxatdan muvaffaqiyatli o'tdingiz!</b>\n\n"
                f"👋 Xush kelibsiz, <b>{full_name}</b>!\n"
                "🎬 Kino kodini yozing. Masalan: <code>125</code>",
                reply_markup=kb_main_user(),
            )
    except Exception as exc:
        logger.error("register_full_name: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik yuz berdi. /start bosing.")

# ═══════════════════════════════════════════════════════════════
# OBUNA TEKSHIRISH (callback)
# ═══════════════════════════════════════════════════════════════

@user_router.callback_query(F.data == "check_sub")
async def check_sub_cb(call: CallbackQuery, bot: Bot) -> None:
    try:
        user = call.from_user
        channels = await db_get_channels()

        # Barcha kanallarga obunani tekshirish
        not_subbed: list[dict] = []
        for ch in channels:
            try:
                member = await bot.get_chat_member(
                    chat_id=ch["channel_username"], user_id=user.id
                )
                if member.status in ("left", "kicked"):
                    not_subbed.append(ch)
            except TelegramForbiddenError:
                logger.warning("Bot %s da admin emas.", ch["channel_username"])
            except TelegramBadRequest as exc:
                logger.warning("check_sub_cb (%s): %s", ch["channel_username"], exc)
            except Exception as exc:
                logger.error("check_sub_cb (%s): %s", ch["channel_username"], exc)

        if not_subbed:
            await call.answer(
                "❌ Hali barcha kanallarga obuna bo'lmagansiz!",
                show_alert=True,
            )
            try:
                await call.message.edit_reply_markup(
                    reply_markup=kb_subscribe(not_subbed)
                )
            except Exception:
                pass
            return

        # Hammaga obuna tasdiqlandi
        await call.answer("✅ Obuna tasdiqlandi!", show_alert=False)

        # Foydalanuvchi ma'lumotlarini tekshirish
        u = await db_get_user(user.id)
        if not u or not u.get("is_registered"):
            # Hali ro'yxatdan o'tmagan — /start ga yuborish
            try:
                await call.message.delete()
            except Exception:
                pass
            await call.message.answer(
                "⚠️ Ro'yxatdan o'tish tugallanmagan.\n/start bosing."
            )
            return

        full_name = u["full_name"]

        # Pending referal bonusini berish
        referrer_id = await db_pop_pending_ref(user.id)
        if referrer_id:
            await give_referral_bonus(bot, full_name, referrer_id)
            welcome_extra = "\n\n🎁 Siz referal havola orqali keldingiz!"
        else:
            welcome_extra = ""

        try:
            await call.message.delete()
        except Exception:
            pass

        await call.message.answer(
            f"✅ <b>Ro'yxatdan muvaffaqiyatli o'tdingiz!</b>\n\n"
            f"👋 Xush kelibsiz, <b>{full_name}</b>!\n"
            f"🎬 Kino kodini yozing. Masalan: <code>125</code>"
            f"{welcome_extra}",
            reply_markup=kb_main_user(),
        )
    except Exception as exc:
        logger.error("check_sub_cb: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik yuz berdi.", show_alert=True)


# ═══════════════════════════════════════════════════════════════
# FOYDALANUVCHI — Profil, Referal, Reyting, Bog'lanish, Yordam
# ═══════════════════════════════════════════════════════════════

@user_router.message(F.text == "👤 Profilim")
async def user_profile(message: Message, bot: Bot) -> None:
    try:
        u = await db_get_user(message.from_user.id)
        if not u:
            await message.answer("❌ Profil topilmadi. /start bosing.")
            return
        today_refs = await db_get_user_refs_today(u["user_id"])
        week_refs  = await db_get_user_refs_period(u["user_id"], 7)
        month_refs = await db_get_user_refs_period(u["user_id"], 30)
        uname = f"@{u['username']}" if u.get("username") else "—"

        bot_info = await bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start=ref_{u['user_id']}"

        text = (
            f"👤 <b>Mening Profilim</b>\n\n"
            f"🆔 ID: <code>{u['user_id']}</code>\n"
            f"👤 Ism-Familiya: <b>{u['full_name']}</b>\n"
            f"📲 Username: {uname}\n\n"
            f"💰 Balans: <b>{u.get('balance', 0)} so'm</b>\n"
            f"👥 Jami referallar: <b>{u.get('ref_count', 0)}</b>\n"
            f"  📅 Bugun: {today_refs}\n"
            f"  🗓 1 hafta: {week_refs}\n"
            f"  📆 1 oy: {month_refs}\n\n"
            f"🔗 Referal havola:\n<code>{ref_link}</code>"
        )
        await message.answer(text)
    except Exception as exc:
        logger.error("user_profile: %s", exc, exc_info=True)


@user_router.message(F.text == "🔗 Referal Havola")
async def user_referral(message: Message, bot: Bot) -> None:
    try:
        bot_info  = await bot.get_me()
        ref_link  = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"
        u         = await db_get_user(message.from_user.id)
        balance   = u.get("balance", 0) if u else 0
        ref_count = u.get("ref_count", 0) if u else 0

        text = (
            f"🔗 <b>Sizning referal havolangiz:</b>\n\n"
            f"<code>{ref_link}</code>\n\n"
            f"👥 Taklif qilganlar: <b>{ref_count}</b> kishi\n"
            f"💰 Balans: <b>{balance} so'm</b>\n\n"
            f"💡 Har bir yangi foydalanuvchi uchun <b>+{REFERRAL_BONUS} so'm</b> olasiz!\n"
            f"💳 Pulni olish uchun <b>«💬 Admin bilan bog'lanish»</b> tugmasini bosing."
        )
        await message.answer(text)
    except Exception as exc:
        logger.error("user_referral: %s", exc, exc_info=True)


@user_router.message(F.text == "🏆 Reyting")
async def user_rating(message: Message) -> None:
    try:
        top = await db_get_top_referrers(10)
        lines = ["🏆 <b>Referal Reytingi — Top 10</b>\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, u in enumerate(top, 1):
            medal = medals[i-1] if i <= 3 else f"{i}."
            name  = u["full_name"]
            lines.append(f"{medal} {name} — <b>{u['ref_count']}</b> referal")

        if not top:
            lines.append("Hali hech kim referal qilmagan.")

        # Foydalanuvchining o'z o'rni
        all_users = await db_get_top_referrers(10000)
        my_rank   = next(
            (i for i, u in enumerate(all_users, 1)
             if u["user_id"] == message.from_user.id), None
        )
        if my_rank:
            lines.append(f"\n📍 Sizning o'rningiz: <b>{my_rank}</b>-o'rin")

        await message.answer("\n".join(lines))
    except Exception as exc:
        logger.error("user_rating: %s", exc, exc_info=True)


@user_router.message(F.text == "💬 Admin bilan bog'lanish")
async def contact_admin(message: Message) -> None:
    try:
        supports = await db_get_supports()
        if not supports:
            await message.answer(
                "ℹ️ Hozircha yordamchi admin belgilanmagan.\n"
                "Keyinroq qayta urinib ko'ring."
            )
            return
        await message.answer(
            "💬 <b>Admin bilan bog'lanish</b>\n\n"
            "Quyidagi adminlardan biriga murojaat qiling:",
            reply_markup=kb_support_contact(supports),
        )
    except Exception as exc:
        logger.error("contact_admin: %s", exc, exc_info=True)


@user_router.message(F.text == "ℹ️ Yordam")
async def cmd_help(message: Message) -> None:
    try:
        await message.answer(
            "ℹ️ <b>Yordam</b>\n\n"
            "🎬 Kino kodini yozing — bot kinoni yuboradi.\n"
            "Masalan: <code>125</code>\n\n"
            "🔗 Referal havolangizni do'stlaringizga yuboring\n"
            f"💰 Har bir yangi foydalanuvchi uchun <b>+{REFERRAL_BONUS} so'm</b> bonus!\n\n"
            "💬 Muammolar uchun <b>«💬 Admin bilan bog'lanish»</b> tugmasini bosing.",
        )
    except Exception as exc:
        logger.error("cmd_help: %s", exc, exc_info=True)


# ═══════════════════════════════════════════════════════════════
# FOYDALANUVCHI — Kino qidirish
# ═══════════════════════════════════════════════════════════════

@user_router.message(F.text == "🎬 Kino Qidirish")
async def ask_movie_code(message: Message) -> None:
    try:
        await message.answer(
            "🎬 Kino kodini yozing:\nMasalan: <code>125</code>",
            reply_markup=kb_main_user(),
        )
    except Exception as exc:
        logger.error("ask_movie_code: %s", exc, exc_info=True)


@user_router.message(F.text.regexp(r"^\d+$"), StateFilter(None))
async def search_movie(message: Message, bot: Bot) -> None:
    if message.from_user.id == ADMIN_ID:
        return
    try:
        kino_kod = message.text.strip()
        movie    = await db_get_movie(kino_kod)
        if not movie:
            await message.answer(
                f"❌ <b>{kino_kod}</b> kodli kino topilmadi.\n"
                "Kodini to'g'ri kiritdingizmi?"
            )
            return
        await db_increment_views(kino_kod)
        caption = (
            f"🎬 <b>{movie['kino_nomi']}</b>\n\n"
            f"📝 {movie['kino_tavsifi']}\n\n"
            f"🔑 Kod: <code>{movie['kino_kod']}</code>\n"
            f"👁 Ko'rishlar: <b>{movie['views_count'] + 1}</b>"
        )
        await bot.send_video(
            chat_id=message.chat.id, video=movie["file_id"], caption=caption
        )
    except Exception as exc:
        logger.error("search_movie: %s", exc, exc_info=True)
        await message.answer("❌ Xatolik. Qayta urinib ko'ring.")

# ═══════════════════════════════════════════════════════════════
# ADMIN — Statistika
# ═══════════════════════════════════════════════════════════════

async def _send_stat(target: Message | CallbackQuery) -> None:
    try:
        total  = await db_get_users_count()
        today  = await db_get_today_count()
        online = await db_get_online_count()
        week   = await db_get_period_count(7)
        month  = await db_get_period_count(30)
        top    = await db_get_top_movies(10)
        text   = build_stat_text(total, today, online, week, month, top)
        if isinstance(target, Message):
            await target.answer(text, reply_markup=kb_stat())
        else:
            await target.message.edit_text(text, reply_markup=kb_stat())
    except Exception as exc:
        logger.error("_send_stat: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), Command("stat"))
@admin_router.message(IsAdmin(), F.text == "📊 Statistika")
async def cmd_stat(message: Message) -> None:
    await _send_stat(message)


@admin_router.callback_query(IsAdmin(), F.data == "refresh_stat")
async def refresh_stat(call: CallbackQuery) -> None:
    try:
        await call.answer("🔄 Yangilanmoqda...")
        await _send_stat(call)
    except Exception as exc:
        logger.error("refresh_stat: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik.", show_alert=True)


@admin_router.callback_query(IsAdmin(), F.data == "download_users")
async def download_users_cb(call: CallbackQuery, bot: Bot) -> None:
    try:
        await call.answer("⏳ Fayl tayyorlanmoqda...")
        users   = await db_get_all_users()
        content = build_users_txt(users)
        file    = BufferedInputFile(content, filename="foydalanuvchilar.txt")
        await bot.send_document(
            chat_id=call.from_user.id,
            document=file,
            caption=f"📥 Jami <b>{len(users)}</b> ta foydalanuvchi.",
        )
    except Exception as exc:
        logger.error("download_users_cb: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik.", show_alert=True)


# ═══════════════════════════════════════════════════════════════
# ADMIN — Reyting (to'liq)
# ═══════════════════════════════════════════════════════════════

@admin_router.message(IsAdmin(), F.text == "🏆 Reyting")
async def admin_rating(message: Message) -> None:
    try:
        top = await db_get_top_referrers(20)
        lines = ["🏆 <b>Referal Reytingi — Top 20</b>\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, u in enumerate(top, 1):
            medal = medals[i-1] if i <= 3 else f"{i}."
            uname = f"@{u['username']}" if u.get("username") else "—"
            lines.append(
                f"{medal} <b>{u['full_name']}</b> ({uname})\n"
                f"   👥 {u['ref_count']} referal | 💰 {u.get('balance',0)} so'm"
            )
        if not top:
            lines.append("Hali hech kim referal qilmagan.")
        today = await db_get_today_count()
        week  = await db_get_period_count(7)
        month = await db_get_period_count(30)
        lines.append(
            f"\n📈 <b>Yangi foydalanuvchilar:</b>\n"
            f"  Bugun: {today} | Hafta: {week} | Oy: {month}"
        )
        await message.answer("\n".join(lines))
    except Exception as exc:
        logger.error("admin_rating: %s", exc, exc_info=True)


# ═══════════════════════════════════════════════════════════════
# ADMIN — Foydalanuvchilar boshqaruvi
# ═══════════════════════════════════════════════════════════════

@admin_router.message(IsAdmin(), F.text == "👥 Foydalanuvchilar")
async def admin_users_menu(message: Message) -> None:
    try:
        total = await db_get_users_count()
        await message.answer(
            f"👥 <b>Foydalanuvchilar boshqaruvi</b>\n\nJami: <b>{total}</b> ta",
            reply_markup=kb_admin_users(),
        )
    except Exception as exc:
        logger.error("admin_users_menu: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), F.text == "🔍 Foydalanuvchi Izlash")
async def user_search_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(UserSearchForm.waiting)
        await message.answer(
            "🔍 Foydalanuvchi <b>ID</b> si yoki <b>@username</b> ini yuboring:",
            reply_markup=kb_cancel(),
        )
    except Exception as exc:
        logger.error("user_search_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(UserSearchForm.waiting))
async def user_search_done(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_users())
            return

        query = (message.text or "").strip()
        await state.clear()

        user_data = await db_search_user(query)
        if not user_data:
            await message.answer(
                "❌ Foydalanuvchi topilmadi.", reply_markup=kb_admin_users()
            )
            return

        uid     = user_data["user_id"]
        uname   = f"@{user_data['username']}" if user_data.get("username") else "—"
        today_r = await db_get_user_refs_today(uid)
        week_r  = await db_get_user_refs_period(uid, 7)
        month_r = await db_get_user_refs_period(uid, 30)
        reg     = "✅ Ha" if user_data.get("is_registered") else "❌ Yo'q"

        text = (
            f"👤 <b>Foydalanuvchi ma'lumotlari</b>\n\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"👤 Ism-Familiya: <b>{user_data['full_name']}</b>\n"
            f"📲 Username: {uname}\n"
            f"📅 Qo'shilgan: {user_data['join_date'][:10]}\n"
            f"✅ Ro'yxatdan o'tgan: {reg}\n\n"
            f"💰 Balans: <b>{user_data.get('balance', 0)} so'm</b>\n"
            f"👥 Jami referallar: <b>{user_data.get('ref_count', 0)}</b>\n"
            f"  Bugun: {today_r} | Hafta: {week_r} | Oy: {month_r}"
        )
        await message.answer(text, reply_markup=kb_user_manage(uid))
    except Exception as exc:
        logger.error("user_search_done: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_users())


@admin_router.callback_query(IsAdmin(), F.data.startswith("ubal_"))
async def user_balance_start(call: CallbackQuery, state: FSMContext) -> None:
    try:
        uid = int(call.data.split("_")[1])
        await state.update_data(target_uid=uid)
        await state.set_state(UserBalanceForm.waiting)
        u = await db_get_user(uid)
        cur_bal = u.get("balance", 0) if u else 0
        await call.message.answer(
            f"💰 Foydalanuvchi: <b>{u['full_name'] if u else uid}</b>\n"
            f"Hozirgi balans: <b>{cur_bal} so'm</b>\n\n"
            "Yangi miqdor kiriting:\n"
            "<i>+500 → qo'shish | -200 → ayirish | 0 → nol</i>",
            reply_markup=kb_cancel(),
        )
        await call.answer()
    except Exception as exc:
        logger.error("user_balance_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(UserBalanceForm.waiting))
async def user_balance_done(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_main())
            return

        raw = (message.text or "").strip()
        if not raw.lstrip("-").isdigit():
            await message.answer("❌ Faqat raqam kiriting. Masalan: <code>500</code> yoki <code>-200</code>:")
            return

        data    = await state.get_data()
        uid     = data["target_uid"]
        amount  = int(raw)
        await state.clear()

        if amount == 0:
            await db_set_balance(uid, 0)
            new_bal = 0
        else:
            new_bal = await db_update_balance(uid, amount)

        sign = "+" if amount >= 0 else ""
        await message.answer(
            f"✅ Balans yangilandi!\n"
            f"👤 ID: <code>{uid}</code>\n"
            f"O'zgarish: <b>{sign}{amount} so'm</b>\n"
            f"Yangi balans: <b>{new_bal} so'm</b>",
            reply_markup=kb_admin_main(),
        )
        try:
            u = await db_get_user(uid)
            name = u["full_name"] if u else "Foydalanuvchi"
            await bot.send_message(
                uid,
                f"💰 <b>Balansingiz yangilandi!</b>\n\n"
                f"O'zgarish: <b>{sign}{amount} so'm</b>\n"
                f"Yangi balans: <b>{new_bal} so'm</b>",
            )
        except Exception:
            pass
    except Exception as exc:
        logger.error("user_balance_done: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_main())


@admin_router.callback_query(IsAdmin(), F.data.startswith("uzero_"))
async def user_balance_zero(call: CallbackQuery, bot: Bot) -> None:
    try:
        uid = int(call.data.split("_")[1])
        await db_set_balance(uid, 0)
        await call.answer("✅ Balans 0 ga tushirildi.", show_alert=True)
        try:
            await bot.send_message(
                uid,
                "ℹ️ <b>Balansingiz 0 ga tushirildi.</b>\n"
                "Murojaat uchun adminlarga bog'laning.",
            )
        except Exception:
            pass
    except Exception as exc:
        logger.error("user_balance_zero: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik.", show_alert=True)


@admin_router.callback_query(IsAdmin(), F.data.startswith("uref_"))
async def user_ref_stat(call: CallbackQuery) -> None:
    try:
        uid    = int(call.data.split("_")[1])
        today  = await db_get_user_refs_today(uid)
        week   = await db_get_user_refs_period(uid, 7)
        month  = await db_get_user_refs_period(uid, 30)
        u      = await db_get_user(uid)
        total  = u.get("ref_count", 0) if u else 0
        name   = u["full_name"] if u else str(uid)
        await call.answer(
            f"👤 {name}\n"
            f"👥 Referallar:\n"
            f"Bugun: {today}\n"
            f"1 hafta: {week}\n"
            f"1 oy: {month}\n"
            f"Jami: {total}",
            show_alert=True,
        )
    except Exception as exc:
        logger.error("user_ref_stat: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik.", show_alert=True)


@admin_router.message(IsAdmin(), F.text == "📥 Ro'yxat (TXT)")
async def download_users_menu(message: Message, bot: Bot) -> None:
    try:
        users   = await db_get_all_users()
        content = build_users_txt(users)
        file    = BufferedInputFile(content, filename="foydalanuvchilar.txt")
        await bot.send_document(
            chat_id=message.chat.id,
            document=file,
            caption=f"📥 Jami <b>{len(users)}</b> ta foydalanuvchi.",
        )
    except Exception as exc:
        logger.error("download_users_menu: %s", exc, exc_info=True)
        await message.answer("❌ Xatolik.")

# ═══════════════════════════════════════════════════════════════
# ADMIN — Kanallar, Yordamchi adminlar, Kino, Reklama, Orqaga
# ═══════════════════════════════════════════════════════════════

@admin_router.message(IsAdmin(), F.text == "🔙 Orqaga")
async def back_to_main(message: Message, state: FSMContext) -> None:
    try:
        await state.clear()
        await message.answer("🏠 Bosh menyu", reply_markup=kb_admin_main())
    except Exception as exc:
        logger.error("back_to_main: %s", exc, exc_info=True)

# ─── Kanallar ─────────────────────────────────────────────────

@admin_router.message(IsAdmin(), F.text == "⚙️ Kanallar")
async def channels_menu(message: Message) -> None:
    try:
        await message.answer("⚙️ <b>Kanallar Boshqaruvi</b>", reply_markup=kb_admin_channels())
    except Exception as exc:
        logger.error("channels_menu: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), F.text == "➕ Kanal Qo'shish")
async def channel_add_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(ChannelForm.add_username)
        await message.answer(
            "➕ <b>Kanal qo'shish</b>\n\n"
            "Kanal username'ini yuboring:\n"
            "✅ To'g'ri: <code>@majburiykanal</code>\n"
            "✅ To'g'ri: <code>majburiykanal</code>\n\n"
            "⚠️ Bot o'sha kanalda <b>admin</b> bo'lishi shart!",
            reply_markup=kb_cancel(),
        )
    except Exception as exc:
        logger.error("channel_add_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(ChannelForm.add_username))
async def channel_add_uname(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_channels())
            return
        uname = _norm_ch((message.text or "").strip())
        if not uname:
            await message.answer("❌ Noto'g'ri format. Masalan: <code>@majburiykanal</code>")
            return
        await state.update_data(ch_username=uname)
        await state.set_state(ChannelForm.add_title)
        await message.answer(
            "✏️ Kanal sarlavhasini kiriting (tugmada ko'rinadigan nom):",
            reply_markup=kb_cancel(),
        )
    except Exception as exc:
        logger.error("channel_add_uname: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(ChannelForm.add_title))
async def channel_add_title(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_channels())
            return
        title = (message.text or "").strip()
        if not title:
            await message.answer("❌ Sarlavha bo'sh bo'lmasin:")
            return
        data    = await state.get_data()
        uname   = data["ch_username"]
        success = await db_add_channel(uname, title)
        await state.clear()
        if success:
            await message.answer(
                f"✅ Kanal qo'shildi!\n📢 Sarlavha: <b>{title}</b>\n"
                f"🔗 Username: <code>{uname}</code>\n\n"
                f"⚠️ Bot {uname} kanalida <b>admin</b> bo'lishi shart!",
                reply_markup=kb_admin_channels(),
            )
        else:
            await message.answer(
                f"⚠️ <b>{uname}</b> allaqachon ro'yxatda.",
                reply_markup=kb_admin_channels(),
            )
    except Exception as exc:
        logger.error("channel_add_title: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_channels())


@admin_router.message(IsAdmin(), F.text == "➖ Kanal O'chirish")
async def channel_remove_start(message: Message, state: FSMContext) -> None:
    try:
        channels = await db_get_channels()
        if not channels:
            await message.answer("📭 Ro'yxat bo'sh.", reply_markup=kb_admin_channels())
            return
        lines = ["➖ <b>O'chirish uchun username'ni yuboring:</b>\n"]
        for i, ch in enumerate(channels, 1):
            t = ch.get("channel_title") or ch["channel_username"]
            lines.append(f"{i}. {t} — <code>{ch['channel_username']}</code>")
        await state.set_state(ChannelForm.remove)
        await message.answer("\n".join(lines), reply_markup=kb_cancel())
    except Exception as exc:
        logger.error("channel_remove_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(ChannelForm.remove))
async def channel_remove_done(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_channels())
            return
        username = (message.text or "").strip()
        deleted  = await db_remove_channel(username)
        await state.clear()
        if deleted:
            await message.answer(
                f"✅ <b>{username}</b> o'chirildi.", reply_markup=kb_admin_channels()
            )
        else:
            await message.answer(
                f"❌ <b>{username}</b> topilmadi.", reply_markup=kb_admin_channels()
            )
    except Exception as exc:
        logger.error("channel_remove_done: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_channels())


@admin_router.message(IsAdmin(), F.text == "📋 Kanallar Ro'yxati")
async def list_channels(message: Message) -> None:
    try:
        channels = await db_get_channels()
        if not channels:
            await message.answer("📭 Hali kanal yo'q.", reply_markup=kb_admin_channels())
            return
        lines = ["📋 <b>Majburiy Kanallar:</b>\n"]
        for i, ch in enumerate(channels, 1):
            t = ch.get("channel_title") or ch["channel_username"]
            lines.append(f"{i}. <b>{t}</b>\n   <code>{ch['channel_username']}</code>")
        await message.answer("\n".join(lines), reply_markup=kb_admin_channels())
    except Exception as exc:
        logger.error("list_channels: %s", exc, exc_info=True)


# ─── Yordamchi Adminlar ───────────────────────────────────────

@admin_router.message(IsAdmin(), F.text == "🛠 Yordamchi Adminlar")
async def support_menu(message: Message) -> None:
    try:
        supports = await db_get_supports()
        count    = len(supports)
        await message.answer(
            f"🛠 <b>Yordamchi Adminlar Boshqaruvi</b>\n\n"
            f"Hozirda: <b>{count}</b> ta yordamchi admin\n\n"
            "Foydalanuvchilar «💬 Admin bilan bog'lanish» tugmasida\n"
            "shu adminlarning username larini ko'radi.",
            reply_markup=kb_admin_support(),
        )
    except Exception as exc:
        logger.error("support_menu: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), F.text == "➕ Admin Qo'shish")
async def support_add_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(SupportForm.add)
        await message.answer(
            "➕ Yordamchi admin username'ini yuboring:\n"
            "Masalan: <code>@username</code> yoki <code>username</code>",
            reply_markup=kb_cancel(),
        )
    except Exception as exc:
        logger.error("support_add_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(SupportForm.add))
async def support_add_done(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_support())
            return
        username = (message.text or "").strip().lstrip("@")
        if not username:
            await message.answer("❌ Username bo'sh bo'lmasin.")
            return
        success = await db_add_support(username)
        await state.clear()
        if success:
            await message.answer(
                f"✅ @{username} yordamchi admin qilib qo'shildi.\n"
                f"Foydalanuvchilar endi @{username} ga murojaat qiladi.",
                reply_markup=kb_admin_support(),
            )
        else:
            await message.answer(
                f"⚠️ @{username} allaqachon ro'yxatda.",
                reply_markup=kb_admin_support(),
            )
    except Exception as exc:
        logger.error("support_add_done: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_support())


@admin_router.message(IsAdmin(), F.text == "➖ Admin O'chirish")
async def support_remove_start(message: Message, state: FSMContext) -> None:
    try:
        supports = await db_get_supports()
        if not supports:
            await message.answer("📭 Ro'yxat bo'sh.", reply_markup=kb_admin_support())
            return
        text = "➖ O'chirish uchun username'ni yuboring:\n\n"
        text += "\n".join(f"{i}. @{s}" for i, s in enumerate(supports, 1))
        await state.set_state(SupportForm.remove)
        await message.answer(text, reply_markup=kb_cancel())
    except Exception as exc:
        logger.error("support_remove_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(SupportForm.remove))
async def support_remove_done(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_support())
            return
        username = (message.text or "").strip().lstrip("@")
        deleted  = await db_remove_support(username)
        await state.clear()
        if deleted:
            await message.answer(
                f"✅ @{username} o'chirildi.", reply_markup=kb_admin_support()
            )
        else:
            await message.answer(
                f"❌ @{username} topilmadi.", reply_markup=kb_admin_support()
            )
    except Exception as exc:
        logger.error("support_remove_done: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_support())


@admin_router.message(IsAdmin(), F.text == "📋 Adminlar Ro'yxati")
async def list_supports(message: Message) -> None:
    try:
        supports = await db_get_supports()
        if not supports:
            await message.answer("📭 Hali yordamchi admin yo'q.", reply_markup=kb_admin_support())
            return
        text = "📋 <b>Yordamchi Adminlar:</b>\n\n"
        text += "\n".join(f"{i}. @{s}" for i, s in enumerate(supports, 1))
        await message.answer(text, reply_markup=kb_admin_support())
    except Exception as exc:
        logger.error("list_supports: %s", exc, exc_info=True)

# ─── Kino qo'shish / o'chirish ────────────────────────────────

@admin_router.message(IsAdmin(), F.text == "🎬 Kino Qo'shish")
async def add_movie_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(AddMovieForm.kod)
        await message.answer(
            "🎬 <b>Yangi kino qo'shish</b>\n\n1️⃣ Kino kodini yuboring (masalan: <code>125</code>):",
            reply_markup=kb_cancel(),
        )
    except Exception as exc:
        logger.error("add_movie_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(AddMovieForm.kod))
async def add_movie_kod(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_main())
            return
        kod = (message.text or "").strip()
        if not kod:
            await message.answer("❌ Kod bo'sh bo'lmasin:")
            return
        await state.update_data(kino_kod=kod)
        await state.set_state(AddMovieForm.nom)
        await message.answer("2️⃣ Kino nomini yuboring:", reply_markup=kb_cancel())
    except Exception as exc:
        logger.error("add_movie_kod: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(AddMovieForm.nom))
async def add_movie_nom(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_main())
            return
        nom = (message.text or "").strip()
        if not nom:
            await message.answer("❌ Nom bo'sh bo'lmasin:")
            return
        await state.update_data(kino_nomi=nom)
        await state.set_state(AddMovieForm.tavsif)
        await message.answer("3️⃣ Kino tavsifini yuboring:", reply_markup=kb_cancel())
    except Exception as exc:
        logger.error("add_movie_nom: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(AddMovieForm.tavsif))
async def add_movie_tavsif(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_main())
            return
        tavsif = (message.text or "").strip()
        await state.update_data(kino_tavsifi=tavsif)
        await state.set_state(AddMovieForm.video)
        await message.answer("4️⃣ Kinoni <b>video</b> sifatida yuboring:", reply_markup=kb_cancel())
    except Exception as exc:
        logger.error("add_movie_tavsif: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(AddMovieForm.video))
async def add_movie_video(message: Message, state: FSMContext) -> None:
    try:
        if message.text and message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_main())
            return
        if not message.video:
            await message.answer("❌ Iltimos, aynan <b>video</b> yuboring.")
            return
        file_id = message.video.file_id
        data    = await state.get_data()
        await state.clear()
        success = await db_add_movie(
            kod=data["kino_kod"], nom=data["kino_nomi"],
            tavsif=data.get("kino_tavsifi", ""), file_id=file_id,
        )
        if success:
            await message.answer(
                f"✅ Kino qo'shildi!\n🔑 Kod: <code>{data['kino_kod']}</code>\n"
                f"🎬 Nom: {data['kino_nomi']}",
                reply_markup=kb_admin_main(),
            )
        else:
            await message.answer(
                f"⚠️ <b>{data['kino_kod']}</b> kodli kino allaqachon mavjud!",
                reply_markup=kb_admin_main(),
            )
    except Exception as exc:
        logger.error("add_movie_video: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_main())


@admin_router.message(IsAdmin(), F.text == "🗑 Kino O'chirish")
async def delete_movie_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(DeleteMovieForm.kod)
        await message.answer("🗑 O'chirish uchun kino kodini yuboring:", reply_markup=kb_cancel())
    except Exception as exc:
        logger.error("delete_movie_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(DeleteMovieForm.kod))
async def delete_movie_kod(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_main())
            return
        kod     = (message.text or "").strip()
        deleted = await db_delete_movie(kod)
        await state.clear()
        if deleted:
            await message.answer(f"✅ <b>{kod}</b> kodli kino o'chirildi.", reply_markup=kb_admin_main())
        else:
            await message.answer(f"❌ <b>{kod}</b> kodli kino topilmadi.", reply_markup=kb_admin_main())
    except Exception as exc:
        logger.error("delete_movie_kod: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_main())


@admin_router.message(IsAdmin(), F.text == "📋 Kinolar Ro'yxati")
async def list_movies(message: Message) -> None:
    try:
        movies = await db_get_all_movies()
        if not movies:
            await message.answer("📭 Hali kino yo'q.")
            return
        header = "📋 <b>Kinolar Ro'yxati:</b>\n\n"
        rows   = [
            f"🔑 <code>{m['kino_kod']}</code> | {m['kino_nomi']} | 👁 {m['views_count']}"
            for m in movies
        ]
        chunk: list[str] = [header]
        length = len(header)
        for row in rows:
            if length + len(row) + 1 > 4000:
                await message.answer("".join(chunk))
                chunk, length = [], 0
            chunk.append(row + "\n")
            length += len(row) + 1
        if chunk:
            await message.answer("".join(chunk))
    except Exception as exc:
        logger.error("list_movies: %s", exc, exc_info=True)
        await message.answer("❌ Xatolik.")


# ─── Reklama yuborish ─────────────────────────────────────────

@admin_router.message(IsAdmin(), F.text == "📢 Reklama Yuborish")
async def broadcast_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(BroadcastForm.waiting)
        await message.answer(
            "📢 <b>Reklama Yuborish</b>\n\n"
            "Yubormoqchi bo'lgan xabaringizni yuboring.\n"
            "📝 Matn | 🖼 Rasm | 🎬 Video | 🎵 Audio — barchasi qabul qilinadi.",
            reply_markup=kb_cancel(),
        )
    except Exception as exc:
        logger.error("broadcast_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(BroadcastForm.waiting))
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_main())
            return
        await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
        await state.set_state(BroadcastForm.confirm)
        await message.answer(
            "👆 Yuqoridagi xabar barcha foydalanuvchilarga yuboriladi.\n\n✅ Tasdiqlaysizmi?",
            reply_markup=kb_broadcast_confirm(),
        )
    except Exception as exc:
        logger.error("broadcast_preview: %s", exc, exc_info=True)


@admin_router.callback_query(
    IsAdmin(), F.data == "confirm_broadcast", StateFilter(BroadcastForm.confirm)
)
async def broadcast_confirm(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    try:
        data = await state.get_data()
        await state.clear()
        await call.answer()
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        user_ids = await db_get_all_user_ids()
        total    = len(user_ids)
        ok = fail = 0
        status   = await call.message.answer(f"⏳ Yuborilmoqda... (0 / {total})")

        for i, uid in enumerate(user_ids, 1):
            try:
                await bot.copy_message(
                    chat_id=uid,
                    from_chat_id=data["from_chat_id"],
                    message_id=data["message_id"],
                )
                ok += 1
            except TelegramForbiddenError:
                fail += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await bot.copy_message(
                        chat_id=uid,
                        from_chat_id=data["from_chat_id"],
                        message_id=data["message_id"],
                    )
                    ok += 1
                except Exception:
                    fail += 1
            except TelegramBadRequest as e:
                logger.warning("Reklama BadRequest (%s): %s", uid, e)
                fail += 1
            except Exception as e:
                logger.error("Reklama xato (%s): %s", uid, e)
                fail += 1

            if i % 100 == 0:
                try:
                    await status.edit_text(f"⏳ Yuborilmoqda... ({i} / {total})")
                except Exception:
                    pass
            await asyncio.sleep(0.04)

        try:
            await status.edit_text(
                f"✅ <b>Reklama yakunlandi!</b>\n\n"
                f"👥 Jami: {total}\n✅ Yuborildi: {ok}\n❌ Bloklagan: {fail}",
            )
        except Exception:
            pass
        await call.message.answer("🏠 Bosh menyu:", reply_markup=kb_admin_main())
    except Exception as exc:
        logger.error("broadcast_confirm: %s", exc, exc_info=True)
        await state.clear()
        await call.message.answer("❌ Xatolik.", reply_markup=kb_admin_main())


@admin_router.callback_query(
    IsAdmin(), F.data == "cancel_broadcast", StateFilter(BroadcastForm.confirm)
)
async def broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.clear()
        await call.answer("❌ Bekor qilindi.")
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await call.message.answer("❌ Reklama bekor qilindi.", reply_markup=kb_admin_main())
    except Exception as exc:
        logger.error("broadcast_cancel: %s", exc, exc_info=True)


# ═══════════════════════════════════════════════════════════════
# ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════════════

async def main() -> None:
    await init_db()

    session = AiohttpSession()
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Middleware tartib: UserTracker birinchi, Subscription keyin
    dp.message.middleware(UserTrackerMiddleware())
    dp.callback_query.middleware(UserTrackerMiddleware())
    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    # Router tartib: admin birinchi (FSM priority)
    dp.include_router(admin_router)
    dp.include_router(user_router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as exc:
        logger.warning("delete_webhook: %s", exc)

    try:
        me = await bot.get_me()
        logger.info("✅ Bot ishga tushdi: @%s (ID: %d)", me.username, me.id)
    except Exception as exc:
        logger.error("Bot info: %s", exc)

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            polling_timeout=30,
        )
    except asyncio.CancelledError:
        logger.info("Polling bekor qilindi.")
    except Exception as exc:
        logger.critical("Polling xatosi: %s", exc, exc_info=True)
        raise
    finally:
        await bot.session.close()
        logger.info("Bot to'xtatildi.")


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
