# config.py — .env faylidan konfiguratsiyalarni o'qish

import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# .env faylini yuklash (Docker ichida ham, oddiy serverda ham ishlaydi)
load_dotenv()

logger = logging.getLogger(__name__)

# ─── Majburiy o'zgaruvchilar ──────────────────────────────────────────────────

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
_admin_raw: str = os.getenv("ADMIN_ID", "").strip()

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN .env faylida topilmadi! Bot ishlamaydi.")
    sys.exit(1)

if not _admin_raw or not _admin_raw.isdigit():
    logger.critical("ADMIN_ID .env faylida topilmadi yoki noto'g'ri! Bot ishlamaydi.")
    sys.exit(1)

ADMIN_ID: int = int(_admin_raw)

# ─── Ixtiyoriy o'zgaruvchilar ─────────────────────────────────────────────────

DB_PATH: str = os.getenv("DB_PATH", "kino_bot.db")
ONLINE_MINUTES: int = int(os.getenv("ONLINE_MINUTES", "10"))

# DB papkasini yaratish (agar mavjud bo'lmasa)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
