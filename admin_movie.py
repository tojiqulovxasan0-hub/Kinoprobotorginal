# handlers/admin_movie.py - Admin: kino qo'shish / o'chirish / ro'yxat (FSM)

import logging

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from filters import IsAdmin
from database import add_movie, delete_movie, get_all_movies
from keyboards import admin_main_kb, cancel_kb

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdmin())  # Faqat admin


# ─── FSM holatlari ────────────────────────────────────────────────────────────

class AddMovieForm(StatesGroup):
    kod = State()
    nom = State()
    tavsif = State()
    video = State()


class DeleteMovieForm(StatesGroup):
    kod = State()


# ─── Kino qo'shish ────────────────────────────────────────────────────────────

@router.message(F.text == "🎬 Kino Qo'shish")
async def add_movie_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(AddMovieForm.kod)
        await message.answer(
            "🎬 <b>Yangi kino qo'shish</b>\n\n"
            "1️⃣ Kino kodini yuboring (masalan: <code>125</code>):",
            reply_markup=cancel_kb(),
        )
    except Exception as exc:
        logger.error("add_movie_start xatosi: %s", exc, exc_info=True)


@router.message(StateFilter(AddMovieForm.kod))
async def add_movie_kod(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=admin_main_kb())
            return
        kod = message.text.strip() if message.text else ""
        if not kod:
            await message.answer("❌ Kod bo'sh bo'lmasin. Qayta yuboring:")
            return
        await state.update_data(kino_kod=kod)
        await state.set_state(AddMovieForm.nom)
        await message.answer("2️⃣ Kino nomini yuboring:", reply_markup=cancel_kb())
    except Exception as exc:
        logger.error("add_movie_kod xatosi: %s", exc, exc_info=True)


@router.message(StateFilter(AddMovieForm.nom))
async def add_movie_nom(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=admin_main_kb())
            return
        nom = message.text.strip() if message.text else ""
        if not nom:
            await message.answer("❌ Nom bo'sh bo'lmasin. Qayta yuboring:")
            return
        await state.update_data(kino_nomi=nom)
        await state.set_state(AddMovieForm.tavsif)
        await message.answer("3️⃣ Kino tavsifini yuboring:", reply_markup=cancel_kb())
    except Exception as exc:
        logger.error("add_movie_nom xatosi: %s", exc, exc_info=True)


@router.message(StateFilter(AddMovieForm.tavsif))
async def add_movie_tavsif(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=admin_main_kb())
            return
        tavsif = message.text.strip() if message.text else ""
        await state.update_data(kino_tavsifi=tavsif)
        await state.set_state(AddMovieForm.video)
        await message.answer(
            "4️⃣ Endi kinoni <b>video</b> sifatida yuboring:",
            reply_markup=cancel_kb(),
        )
    except Exception as exc:
        logger.error("add_movie_tavsif xatosi: %s", exc, exc_info=True)


@router.message(StateFilter(AddMovieForm.video))
async def add_movie_video(message: Message, state: FSMContext) -> None:
    try:
        if message.text and message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=admin_main_kb())
            return
        if not message.video:
            await message.answer("❌ Iltimos, aynan <b>video</b> yuboring (fayl emas).")
            return

        file_id = message.video.file_id
        data = await state.get_data()
        await state.clear()

        success = await add_movie(
            kino_kod=data["kino_kod"],
            kino_nomi=data["kino_nomi"],
            kino_tavsifi=data.get("kino_tavsifi", ""),
            file_id=file_id,
        )

        if success:
            await message.answer(
                f"✅ Kino muvaffaqiyatli qo'shildi!\n\n"
                f"🔑 Kod: <code>{data['kino_kod']}</code>\n"
                f"🎬 Nom: {data['kino_nomi']}",
                reply_markup=admin_main_kb(),
            )
        else:
            await message.answer(
                f"⚠️ <b>{data['kino_kod']}</b> kodli kino allaqachon mavjud!\n"
                "Boshqa kod bilan urinib ko'ring.",
                reply_markup=admin_main_kb(),
            )
    except Exception as exc:
        logger.error("add_movie_video xatosi: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik yuz berdi.", reply_markup=admin_main_kb())


# ─── Kino o'chirish ───────────────────────────────────────────────────────────

@router.message(F.text == "🗑 Kino O'chirish")
async def delete_movie_start(message: Message, state: FSMContext) -> None:
    try:
        await state.set_state(DeleteMovieForm.kod)
        await message.answer("🗑 O'chirish uchun kino kodini yuboring:", reply_markup=cancel_kb())
    except Exception as exc:
        logger.error("delete_movie_start xatosi: %s", exc, exc_info=True)


@router.message(StateFilter(DeleteMovieForm.kod))
async def delete_movie_kod(message: Message, state: FSMContext) -> None:
    try:
        if message.text == "❌ Bekor Qilish":
            await state.clear()
            await message.answer("❌ Bekor qilindi.", reply_markup=admin_main_kb())
            return
        kod = message.text.strip() if message.text else ""
        deleted = await delete_movie(kod)
        await state.clear()

        if deleted:
            await message.answer(
                f"✅ <b>{kod}</b> kodli kino o'chirildi.",
                reply_markup=admin_main_kb(),
            )
        else:
            await message.answer(
                f"❌ <b>{kod}</b> kodli kino topilmadi.",
                reply_markup=admin_main_kb(),
            )
    except Exception as exc:
        logger.error("delete_movie_kod xatosi: %s", exc, exc_info=True)
        await state.clear()
        await message.answer("❌ Xatolik yuz berdi.", reply_markup=admin_main_kb())


# ─── Kinolar ro'yxati ─────────────────────────────────────────────────────────

@router.message(F.text == "📋 Kinolar Ro'yxati")
async def list_movies(message: Message) -> None:
    try:
        movies = await get_all_movies()
        if not movies:
            await message.answer("📭 Hali hech qanday kino qo'shilmagan.")
            return

        header = "📋 <b>Kinolar Ro'yxati:</b>\n\n"
        rows = [
            f"🔑 <code>{m['kino_kod']}</code> | {m['kino_nomi']} | 👁 {m['views_count']}"
            for m in movies
        ]

        # Telegram 4096 belgi limitiga ko'ra chunklab yuborish
        chunk: list[str] = [header]
        length = len(header)
        for row in rows:
            if length + len(row) + 1 > 4000:
                await message.answer("".join(chunk))
                chunk = []
                length = 0
            chunk.append(row + "\n")
            length += len(row) + 1

        if chunk:
            await message.answer("".join(chunk))

    except Exception as exc:
        logger.error("list_movies xatosi: %s", exc, exc_info=True)
        await message.answer("❌ Xatolik yuz berdi.")
