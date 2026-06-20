# middlewares.py - Foydalanuvchini ro'yxatdan o'tkazish va last_active yangilash

import logging
from collections.abc import Callable, Awaitable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from database import add_or_update_user

logger = logging.getLogger(__name__)


class UserTrackerMiddleware(BaseMiddleware):
    """
    Har bir Message yoki CallbackQuery kelganda foydalanuvchini
    bazaga qo'shadi yoki last_active ni yangilaydi.
    """

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
                await add_or_update_user(
                    user_id=user.id,
                    username=user.username,
                    full_name=user.full_name or str(user.id),
                )
            except Exception as exc:
                logger.error("UserTrackerMiddleware xatosi: %s", exc, exc_info=True)

        return await handler(event, data)
