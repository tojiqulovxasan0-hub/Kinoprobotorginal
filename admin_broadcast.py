# handlers/admin_broadcast.py - Reklama yuborish (FSM)

import asyncio
import logging

from aiogram import Router, Bot, F
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from filters import IsAdmin
from database import get_all_user_ids
from keyboards import admin_main_kb, cancel_kb, confirm_broadcast_kb

logger = logging.getLogger(__name__)
router = Router()


class BroadcastForm(StatesGroup):
    waiting = State()
    confirm = State()


# ─── Boshlash ─────────────────────────────────────────────────────────────────

@router.message(IsAdmin(), F.text == "📢 Reklama Yuborish")
async def broadcast_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(BroadcastForm.waiting)
        await message.answer(
            "📢 <b>Reklama Yuborish</b>\n\n"
            "Yubormoqchi bo'lgan xabaringizni yozing yoki yuboring.\n"
            "📝 Matn | 🖼 Rasm | 🎬 Video | 🎵 Audio — barchasi qabul qilinadi.",
            reply_markup=cancel_kb(),
        )
    except Exception as exc:
        logger.error("broadcast_start xatosi: %s", exc, exc_info=True)


@router.message(IsAdmin(), StateFilter(BroadcastForm.waiting))
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=admin_main_kb())
            return

        await state.update_data(
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await state.set_state(BroadcastForm.confirm)
        await message.answer(
            "👆 Yuqoridagi xabar barcha foydalanuvchilarga yuboriladi.\n\n"
            "✅ Tasdiqlaysizmi?",
            reply_markup=confirm_broadcast_kb(),
        )
    except Exception as exc:
        logger.error("broadcast_preview xatosi: %s", exc, exc_info=True)


# ─── Tasdiqlash ───────────────────────────────────────────────────────────────

@router.callback_query(IsAdmin(), F.data == "confirm_broadcast", StateFilter(BroadcastForm.confirm))
async def broadcast_confirm(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    try:
        data = await state.get_data()
        await state.clear()
        await call.answer()

        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        user_ids = await get_all_user_ids()
        total = len(user_ids)
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
                fail += 1  # Foydalanuvchi botni bloklagan
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
                logger.error("Reklama xato (%s): %s", uid, exc, exc_info=True)
                fail += 1

            # Har 100 foydalanuvchidan keyin status yangilash
            if i % 100 == 0:
                try:
                    await status.edit_text(f"⏳ Yuborilmoqda... ({i} / {total})")
                except Exception:
                    pass

            await asyncio.sleep(0.04)  # ~25 msg/sek — Telegram limitidan past

        try:
            await status.edit_text(
                f"✅ <b>Reklama yakunlandi!</b>\n\n"
                f"👥 Jami: {total}\n"
                f"✅ Muvaffaqiyatli: {ok}\n"
                f"❌ Xato / bloklagan: {fail}",
            )
        except Exception:
            pass

        await call.message.answer("🏠 Bosh menyu:", reply_markup=admin_main_kb())

    except Exception as exc:
        logger.error("broadcast_confirm xatosi: %s", exc, exc_info=True)
        await state.clear()
        await call.message.answer("❌ Xatolik yuz berdi.", reply_markup=admin_main_kb())


@router.callback_query(IsAdmin(), F.data == "cancel_broadcast", StateFilter(BroadcastForm.confirm))
async def broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.clear()
        await call.answer("❌ Bekor qilindi.")
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await call.message.answer("❌ Reklama bekor qilindi.", reply_markup=admin_main_kb())
    except Exception as exc:
        logger.error("broadcast_cancel xatosi: %s", exc, exc_info=True)
