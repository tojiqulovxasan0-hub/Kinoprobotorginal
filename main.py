# ╔══════════════════════════════════════════════════════════╗
# ║          KINO BOT — Yagona fayl (main.py)               ║
# ║  Barcha handlerlar, DB, klaviatura — hammasi shu yerda  ║
# ╚══════════════════════════════════════════════════════════╝

import asyncio
import logging
import os
import sys
from collections.abc import Callable, Awaitable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import BaseFilter, Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    TelegramObject,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
_admin_raw: str = os.getenv("ADMIN_ID", "").strip()
DB_PATH: str = os.getenv("DB_PATH", "kino_bot.db")
ONLINE_MINUTES: int = int(os.getenv("ONLINE_MINUTES", "10"))

if not BOT_TOKEN:
    sys.exit("❌ BOT_TOKEN .env faylida topilmadi!")
if not _admin_raw or not _admin_raw.isdigit():
    sys.exit("❌ ADMIN_ID .env faylida topilmadi yoki noto'g'ri!")

ADMIN_ID: int = int(_admin_raw)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)

# ──────────────────────────────────────────────────────────────
# DATABASE
# ──────────────────────────────────────────────────────────────

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                join_date   TEXT NOT NULL,
                last_active TEXT NOT NULL
            )
        """)
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
                channel_username TEXT UNIQUE NOT NULL
            )
        """)
        await db.commit()
    logger.info("Ma'lumotlar bazasi ishga tushirildi.")


async def db_add_or_update_user(user_id: int, username: str | None, full_name: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row:
            await db.execute(
                "UPDATE users SET username=?, full_name=?, last_active=? WHERE user_id=?",
                (username, full_name, now, user_id),
            )
        else:
            await db.execute(
                "INSERT INTO users (user_id, username, full_name, join_date, last_active)"
                " VALUES (?,?,?,?,?)",
                (user_id, username, full_name, now, now),
            )
        await db.commit()


async def db_get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT user_id, username, full_name, join_date FROM users ORDER BY join_date DESC"
        )
        return [dict(r) for r in await cur.fetchall()]


async def db_get_users_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        row = await cur.fetchone()
        return row[0] if row else 0


async def db_get_today_count() -> int:
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM users WHERE join_date LIKE ?", (f"{today}%",)
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
        cur = await db.execute("SELECT user_id FROM users")
        return [r[0] for r in await cur.fetchall()]


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


def _norm_ch(username: str) -> str:
    return username if username.startswith("@") else f"@{username}"


async def db_add_channel(username: str) -> bool:
    username = _norm_ch(username)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO channels (channel_username) VALUES (?)", (username,)
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def db_remove_channel(username: str) -> bool:
    username = _norm_ch(username)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM channels WHERE channel_username=?", (username,)
        )
        await db.commit()
        return cur.rowcount > 0


async def db_get_channels() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT channel_username FROM channels")
        return [r[0] for r in await cur.fetchall()]

# ──────────────────────────────────────────────────────────────
# KLAVIATURALAR
# ──────────────────────────────────────────────────────────────

def kb_main_user() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="🎬 Kino Qidirish"))
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
    b.add(KeyboardButton(text="⚙️ Kanallar Boshqaruvi"))
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


def kb_cancel() -> ReplyKeyboardMarkup:
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="❌ Bekor Qilish"))
    return b.as_markup(resize_keyboard=True, one_time_keyboard=True)


def kb_subscribe(channels: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.row(InlineKeyboardButton(
            text=f"➕ {ch} kanaliga obuna bo'ling",
            url=f"https://t.me/{ch.lstrip('@')}",
        ))
    b.row(InlineKeyboardButton(
        text="✅ Obunani Tekshirish", callback_data="check_sub"
    ))
    return b.as_markup()


def kb_stat() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Yangilash", callback_data="refresh_stat"))
    b.row(InlineKeyboardButton(
        text="📥 Foydalanuvchilar (TXT)", callback_data="download_users"
    ))
    return b.as_markup()


def kb_broadcast_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="✅ Ha, Yuborish", callback_data="confirm_broadcast"))
    b.add(InlineKeyboardButton(text="❌ Bekor", callback_data="cancel_broadcast"))
    b.adjust(2)
    return b.as_markup()

# ──────────────────────────────────────────────────────────────
# FILTR VA MIDDLEWARE
# ──────────────────────────────────────────────────────────────

class IsAdmin(BaseFilter):
    """Faqat ADMIN_ID ga ruxsat beruvchi filtr."""
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user.id == ADMIN_ID


class UserTrackerMiddleware(BaseMiddleware):
    """Har bir xabarda foydalanuvchini bazaga qo'shadi/yangilaydi."""
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
                await db_add_or_update_user(
                    user_id=user.id,
                    username=user.username,
                    full_name=user.full_name or str(user.id),
                )
            except Exception as exc:
                logger.error("UserTracker xatosi: %s", exc)
        return await handler(event, data)

# ──────────────────────────────────────────────────────────────
# YORDAMCHI FUNKSIYALAR
# ──────────────────────────────────────────────────────────────

async def check_subscription(bot: Bot, user_id: int) -> list[str]:
    """Obuna bo'lmagan kanallar ro'yxatini qaytaradi."""
    channels = await db_get_channels()
    not_subbed: list[str] = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(chat_id=ch, user_id=user_id)
            if member.status in ("left", "kicked"):
                not_subbed.append(ch)
        except TelegramForbiddenError:
            logger.warning("Bot %s kanalda admin emas.", ch)
        except TelegramBadRequest as exc:
            logger.warning("get_chat_member (%s): %s", ch, exc)
        except Exception as exc:
            logger.error("check_subscription (%s): %s", ch, exc)
    return not_subbed


async def subscription_guard(message: Message, bot: Bot) -> bool:
    """True = o'tsin, False = obuna xabari ko'rsatildi."""
    channels = await db_get_channels()
    if not channels:
        return True
    not_subbed = await check_subscription(bot, message.from_user.id)
    if not_subbed:
        await message.answer(
            "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>",
            reply_markup=kb_subscribe(not_subbed),
        )
        return False
    return True


def build_stat_text(total: int, today: int, online: int, top: list[dict]) -> str:
    lines = [
        "📊 <b>Bot Statistikasi</b>\n",
        f"👥 Jami foydalanuvchilar: <b>{total}</b>",
        f"🆕 Bugun yangi: <b>{today}</b>",
        f"🟢 Online (oxirgi {ONLINE_MINUTES} daqiqa): <b>{online}</b>\n",
        "🏆 <b>Top-10 Ko'p Ko'rilgan Kinolar:</b>",
    ]
    if top:
        for i, m in enumerate(top, 1):
            lines.append(
                f"  {i}. <code>{m['kino_kod']}</code> — {m['kino_nomi']} "
                f"<i>({m['views_count']} marta)</i>"
            )
    else:
        lines.append("  Hali birorta kino qo'shilmagan.")
    return "\n".join(lines)


def build_users_txt(users: list[dict]) -> bytes:
    lines = ["ID | Username | Ism-Familiya | Qo'shilgan sana\n", "-" * 60 + "\n"]
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else "—"
        lines.append(
            f"{u['user_id']} | {uname} | {u['full_name']} | {u['join_date'][:10]}\n"
        )
    return "".join(lines).encode("utf-8")

# ──────────────────────────────────────────────────────────────
# FSM HOLATLARI
# ──────────────────────────────────────────────────────────────

class AddMovieForm(StatesGroup):
    kod   = State()
    nom   = State()
    tavsif = State()
    video  = State()


class DeleteMovieForm(StatesGroup):
    kod = State()


class ChannelForm(StatesGroup):
    add    = State()
    remove = State()


class BroadcastForm(StatesGroup):
    waiting = State()
    confirm = State()


# ──────────────────────────────────────────────────────────────
# ROUTERLAR  (ikkita alohida router — admin va user)
# BU JUDA MUHIM: admin routeri dp ga birinchi qo'shiladi,
# shunda admin FSM state lari user handlerlaridan oldin ishlaydi
# ──────────────────────────────────────────────────────────────

admin_router = Router()   # Faqat admin
user_router  = Router()   # Umumiy + foydalanuvchi

# ══════════════════════════════════════════════════════════════
# UMUMIY HANDLERLAR — /start, /help, obuna (user_router)
# ══════════════════════════════════════════════════════════════

@user_router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot) -> None:
    try:
        if not await subscription_guard(message, bot):
            return
        if message.from_user.id == ADMIN_ID:
            await message.answer(
                "👋 Xush kelibsiz, <b>Admin</b>!\nBot boshqaruvi paneliga xush kelibsiz.",
                reply_markup=kb_admin_main(),
            )
        else:
            await message.answer(
                f"👋 Salom, <b>{message.from_user.full_name}</b>!\n\n"
                "🎬 Kino kodini yozing — men kinoni yuboraman.\n"
                "Masalan: <code>125</code>",
                reply_markup=kb_main_user(),
            )
    except Exception as exc:
        logger.error("cmd_start: %s", exc, exc_info=True)


@user_router.message(Command("help"))
@user_router.message(F.text == "ℹ️ Yordam")
async def cmd_help(message: Message, bot: Bot) -> None:
    try:
        if not await subscription_guard(message, bot):
            return
        await message.answer(
            "ℹ️ <b>Yordam</b>\n\n"
            "🎬 Kino kodini yozing — bot kinoni yuboradi.\n"
            "Masalan: <code>125</code>\n\n"
            "❓ Muammolar bo'lsa admin bilan bog'laning.",
        )
    except Exception as exc:
        logger.error("cmd_help: %s", exc, exc_info=True)


@user_router.callback_query(F.data == "check_sub")
async def check_sub_cb(call: CallbackQuery, bot: Bot) -> None:
    try:
        not_subbed = await check_subscription(bot, call.from_user.id)
        if not_subbed:
            await call.answer(
                "❌ Hali barcha kanallarga obuna bo'lmagansiz!", show_alert=True
            )
            try:
                await call.message.edit_reply_markup(
                    reply_markup=kb_subscribe(not_subbed)
                )
            except Exception:
                pass
        else:
            await call.answer("✅ Obuna tasdiqlandi!", show_alert=True)
            try:
                await call.message.delete()
            except Exception:
                pass
            if call.from_user.id == ADMIN_ID:
                await call.message.answer(
                    "👋 Xush kelibsiz, <b>Admin</b>!", reply_markup=kb_admin_main()
                )
            else:
                await call.message.answer(
                    "✅ Obuna tasdiqlandi! Kino kodini yuboring.\n"
                    "Masalan: <code>125</code>",
                    reply_markup=kb_main_user(),
                )
    except Exception as exc:
        logger.error("check_sub_cb: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik.", show_alert=True)

# ══════════════════════════════════════════════════════════════
# FOYDALANUVCHI — kino qidirish (user_router)
# MUHIM: StateFilter(None) — faqat holatsiz (hech qanday FSM
# state yo'q) holatda ishlaydi. Shu bilan admin FSM ni buzmaydi.
# ══════════════════════════════════════════════════════════════

@user_router.message(F.text == "🎬 Kino Qidirish")
async def ask_movie_code(message: Message) -> None:
    try:
        await message.answer(
            "🎬 Kino kodini yozing:\nMasalan: <code>125</code>",
            reply_markup=kb_main_user(),
        )
    except Exception as exc:
        logger.error("ask_movie_code: %s", exc, exc_info=True)


@user_router.message(
    F.text.regexp(r"^\d+$"),
    StateFilter(None),       # ← KALIT: faqat hech qanday state yo'qda ishlaydi
)
async def search_movie(message: Message, bot: Bot) -> None:
    """Foydalanuvchi raqam (kino kodi) yuborganda kinoni topib yuboradi."""
    # Admin bu handlerga tushmasligi uchun
    if message.from_user.id == ADMIN_ID:
        return
    try:
        # Obuna tekshirish
        channels = await db_get_channels()
        if channels:
            not_subbed = await check_subscription(bot, message.from_user.id)
            if not_subbed:
                await message.answer(
                    "⚠️ <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>",
                    reply_markup=kb_subscribe(not_subbed),
                )
                return

        kino_kod = message.text.strip()
        movie = await db_get_movie(kino_kod)
        if not movie:
            await message.answer(
                f"❌ <b>{kino_kod}</b> kodli kino topilmadi.\n"
                "Kino kodini to'g'ri kiritdingizmi?"
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
            chat_id=message.chat.id,
            video=movie["file_id"],
            caption=caption,
        )
    except Exception as exc:
        logger.error("search_movie: %s", exc, exc_info=True)
        await message.answer("❌ Xatolik yuz berdi. Qayta urinib ko'ring.")

# ══════════════════════════════════════════════════════════════
# ADMIN — statistika (admin_router)
# ══════════════════════════════════════════════════════════════

async def _send_stat(target: Message | CallbackQuery) -> None:
    try:
        total  = await db_get_users_count()
        today  = await db_get_today_count()
        online = await db_get_online_count()
        top    = await db_get_top_movies(10)
        text   = build_stat_text(total, today, online, top)
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
async def download_users(call: CallbackQuery, bot: Bot) -> None:
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
        logger.error("download_users: %s", exc, exc_info=True)
        await call.answer("❌ Xatolik.", show_alert=True)


# ══════════════════════════════════════════════════════════════
# ADMIN — kanallar boshqaruvi (admin_router, FSM)
# ══════════════════════════════════════════════════════════════

@admin_router.message(IsAdmin(), F.text == "⚙️ Kanallar Boshqaruvi")
async def channels_menu(message: Message) -> None:
    try:
        await message.answer(
            "⚙️ <b>Kanallar Boshqaruvi</b>", reply_markup=kb_admin_channels()
        )
    except Exception as exc:
        logger.error("channels_menu: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), F.text == "🔙 Orqaga")
async def back_to_main(message: Message, state: FSMContext) -> None:
    try:
        await state.clear()
        await message.answer("🏠 Bosh menyu", reply_markup=kb_admin_main())
    except Exception as exc:
        logger.error("back_to_main: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), F.text == "➕ Kanal Qo'shish")
async def channel_add_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(ChannelForm.add)
        await message.answer(
            "➕ Kanal username'ini yuboring.\nMasalan: <code>@kanal_username</code>",
            reply_markup=kb_cancel(),
        )
    except Exception as exc:
        logger.error("channel_add_start: %s", exc, exc_info=True)


@admin_router.message(IsAdmin(), StateFilter(ChannelForm.add))
async def channel_add_done(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_channels())
            return
        username = (message.text or "").strip()
        if not username:
            await message.answer("❌ Username bo'sh bo'lmasin.")
            return
        success = await db_add_channel(username)
        await state.clear()
        uname = _norm_ch(username)
        if success:
            await message.answer(
                f"✅ <b>{uname}</b> qo'shildi.", reply_markup=kb_admin_channels()
            )
        else:
            await message.answer(
                f"⚠️ <b>{uname}</b> allaqachon mavjud.", reply_markup=kb_admin_channels()
            )
    except Exception as exc:
        logger.error("channel_add_done: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_channels())


@admin_router.message(IsAdmin(), F.text == "➖ Kanal O'chirish")
async def channel_remove_start(message: Message, state: FSMContext) -> None:
    try:
        channels = await db_get_channels()
        if not channels:
            await message.answer("📭 Ro'yxat bo'sh.", reply_markup=kb_admin_channels())
            return
        text = "➖ O'chirmoqchi bo'lgan kanal username'ini yuboring.\n\n"
        text += "<b>Mavjud kanallar:</b>\n" + "\n".join(
            f"{i}. {ch}" for i, ch in enumerate(channels, 1)
        )
        await state.set_state(ChannelForm.remove)
        await message.answer(text, reply_markup=kb_cancel())
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
        uname = _norm_ch(username)
        if deleted:
            await message.answer(
                f"✅ <b>{uname}</b> o'chirildi.", reply_markup=kb_admin_channels()
            )
        else:
            await message.answer(
                f"❌ <b>{uname}</b> topilmadi.", reply_markup=kb_admin_channels()
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
            await message.answer(
                "📭 Hali hech qanday kanal yo'q.", reply_markup=kb_admin_channels()
            )
            return
        text = "📋 <b>Majburiy Kanallar:</b>\n\n" + "\n".join(
            f"{i}. {ch}" for i, ch in enumerate(channels, 1)
        )
        await message.answer(text, reply_markup=kb_admin_channels())
    except Exception as exc:
        logger.error("list_channels: %s", exc, exc_info=True)

# ══════════════════════════════════════════════════════════════
# ADMIN — kino qo'shish / o'chirish (admin_router, FSM)
# ══════════════════════════════════════════════════════════════

@admin_router.message(IsAdmin(), F.text == "🎬 Kino Qo'shish")
async def add_movie_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(AddMovieForm.kod)
        await message.answer(
            "🎬 <b>Yangi kino qo'shish</b>\n\n"
            "1️⃣ Kino kodini yuboring (masalan: <code>125</code>):",
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
            await message.answer("❌ Kod bo'sh bo'lmasin. Qayta yuboring:")
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
            await message.answer("❌ Nom bo'sh bo'lmasin. Qayta yuboring:")
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
        await message.answer(
            "4️⃣ Endi kinoni <b>video</b> sifatida yuboring:",
            reply_markup=kb_cancel(),
        )
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
            await message.answer(
                "❌ Iltimos, aynan <b>video</b> yuboring (fayl emas, video!)."
            )
            return
        file_id = message.video.file_id
        data    = await state.get_data()
        await state.clear()

        success = await db_add_movie(
            kod=data["kino_kod"],
            nom=data["kino_nomi"],
            tavsif=data.get("kino_tavsifi", ""),
            file_id=file_id,
        )
        if success:
            await message.answer(
                f"✅ Kino muvaffaqiyatli qo'shildi!\n\n"
                f"🔑 Kod: <code>{data['kino_kod']}</code>\n"
                f"🎬 Nom: {data['kino_nomi']}",
                reply_markup=kb_admin_main(),
            )
        else:
            await message.answer(
                f"⚠️ <b>{data['kino_kod']}</b> kodli kino allaqachon mavjud!\n"
                "Boshqa kod bilan urinib ko'ring.",
                reply_markup=kb_admin_main(),
            )
    except Exception as exc:
        logger.error("add_movie_video: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik yuz berdi.", reply_markup=kb_admin_main())


@admin_router.message(IsAdmin(), F.text == "🗑 Kino O'chirish")
async def delete_movie_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(DeleteMovieForm.kod)
        await message.answer(
            "🗑 O'chirish uchun kino kodini yuboring:", reply_markup=kb_cancel()
        )
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
            await message.answer(
                f"✅ <b>{kod}</b> kodli kino o'chirildi.", reply_markup=kb_admin_main()
            )
        else:
            await message.answer(
                f"❌ <b>{kod}</b> kodli kino topilmadi.", reply_markup=kb_admin_main()
            )
    except Exception as exc:
        logger.error("delete_movie_kod: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik.", reply_markup=kb_admin_main())


@admin_router.message(IsAdmin(), F.text == "📋 Kinolar Ro'yxati")
async def list_movies(message: Message) -> None:
    try:
        movies = await db_get_all_movies()
        if not movies:
            await message.answer("📭 Hali hech qanday kino yo'q.")
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

# ══════════════════════════════════════════════════════════════
# ADMIN — reklama yuborish (admin_router, FSM)
# ══════════════════════════════════════════════════════════════

@admin_router.message(IsAdmin(), F.text == "📢 Reklama Yuborish")
async def broadcast_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(BroadcastForm.waiting)
        await message.answer(
            "📢 <b>Reklama Yuborish</b>\n\n"
            "Yubormoqchi bo'lgan xabaringizni yozing yoki yuboring.\n"
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
        await state.update_data(
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await state.set_state(BroadcastForm.confirm)
        await message.answer(
            "👆 Yuqoridagi xabar barcha foydalanuvchilarga yuboriladi.\n\n"
            "✅ Tasdiqlaysizmi?",
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
        status = await call.message.answer(f"⏳ Yuborilmoqda... (0 / {total})")

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
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
                try:
                    await bot.copy_message(
                        chat_id=uid,
                        from_chat_id=data["from_chat_id"],
                        message_id=data["message_id"],
                    )
                    ok += 1
                except Exception:
                    fail += 1
            except TelegramBadRequest as exc:
                logger.warning("Reklama BadRequest (%s): %s", uid, exc)
                fail += 1
            except Exception as exc:
                logger.error("Reklama xato (%s): %s", uid, exc)
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
                f"👥 Jami: {total}\n"
                f"✅ Muvaffaqiyatli: {ok}\n"
                f"❌ Bloklagan: {fail}",
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
        await call.message.answer(
            "❌ Reklama bekor qilindi.", reply_markup=kb_admin_main()
        )
    except Exception as exc:
        logger.error("broadcast_cancel: %s", exc, exc_info=True)


# ══════════════════════════════════════════════════════════════
# ISHGA TUSHIRISH
# ══════════════════════════════════════════════════════════════

async def main() -> None:
    await init_db()

    session = AiohttpSession()
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(UserTrackerMiddleware())
    dp.callback_query.middleware(UserTrackerMiddleware())

    # TARTIB MUHIM:
    # 1. admin_router — birinchi (FSM state lari priority oladi)
    # 2. user_router  — keyin (search_movie StateFilter(None) bilan himoyalangan)
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
        logger.error("Bot ma'lumotlari: %s", exc)

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
