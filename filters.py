# filters.py - Maxsus filtrlar

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from config import ADMIN_ID


class IsAdmin(BaseFilter):
    """Faqat ADMIN_ID ga ruxsat beruvchi filtr."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user.id == ADMIN_ID
