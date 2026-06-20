# database.py - SQLite ma'lumotlar bazasi bilan ishlash (aiosqlite async)

import logging
import aiosqlite
from datetime import datetime, timedelta
from config import DB_PATH, ONLINE_MINUTES

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Barcha jadvallarni yaratish (agar mavjud bo'lmasa)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")  # yozuv xavfsizligi

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
    logger.info("Ma'lumotlar bazasi muvaffaqiyatli ishga tushirildi.")


# ─────────────────────────────────────────────────────────────
# FOYDALANUVCHILAR
# ─────────────────────────────────────────────────────────────

async def add_or_update_user(user_id: int, username: str | None, full_name: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        row = await cursor.fetchone()
        if row:
            await db.execute(
                "UPDATE users SET username=?, full_name=?, last_active=? WHERE user_id=?",
                (username, full_name, now, user_id),
            )
        else:
            await db.execute(
                "INSERT INTO users (user_id, username, full_name, join_date, last_active) "
                "VALUES (?,?,?,?,?)",
                (user_id, username, full_name, now, now),
            )
        await db.commit()


async def get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT user_id, username, full_name, join_date FROM users ORDER BY join_date DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]


async def get_users_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_today_users_count() -> int:
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE join_date LIKE ?", (f"{today}%",)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_online_users_count() -> int:
    threshold = (datetime.now() - timedelta(minutes=ONLINE_MINUTES)).isoformat(timespec="seconds")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM users WHERE last_active >= ?", (threshold,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id FROM users")
        return [r[0] for r in await cursor.fetchall()]


# ─────────────────────────────────────────────────────────────
# KINOLAR
# ─────────────────────────────────────────────────────────────

async def add_movie(kino_kod: str, kino_nomi: str, kino_tavsifi: str, file_id: str) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO movies (kino_kod, kino_nomi, kino_tavsifi, file_id) VALUES (?,?,?,?)",
                (kino_kod, kino_nomi, kino_tavsifi, file_id),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def get_movie_by_kod(kino_kod: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM movies WHERE kino_kod=?", (kino_kod,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def increment_views(kino_kod: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE movies SET views_count=views_count+1 WHERE kino_kod=?", (kino_kod,)
        )
        await db.commit()


async def get_top_movies(limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT kino_kod, kino_nomi, views_count FROM movies "
            "ORDER BY views_count DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def delete_movie(kino_kod: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM movies WHERE kino_kod=?", (kino_kod,))
        await db.commit()
        return cursor.rowcount > 0


async def get_all_movies() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT kino_kod, kino_nomi, kino_tavsifi, views_count FROM movies ORDER BY id DESC"
        )
        return [dict(r) for r in await cursor.fetchall()]


# ─────────────────────────────────────────────────────────────
# MAJBURIY KANALLAR
# ─────────────────────────────────────────────────────────────

def _normalize(username: str) -> str:
    return username if username.startswith("@") else f"@{username}"


async def add_channel(channel_username: str) -> bool:
    channel_username = _normalize(channel_username)
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO channels (channel_username) VALUES (?)", (channel_username,)
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def remove_channel(channel_username: str) -> bool:
    channel_username = _normalize(channel_username)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM channels WHERE channel_username=?", (channel_username,)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_all_channels() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT channel_username FROM channels")
        return [r[0] for r in await cursor.fetchall()]
