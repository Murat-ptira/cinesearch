import os
import logging
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
TMDB_KEY  = os.getenv("TMDB_KEY",  "YOUR_TMDB_KEY")
TMDB_URL  = "https://api.themoviedb.org/3"
IMG_BASE  = "https://image.tmdb.org/t/p/w500"
LANG      = "ru-RU"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher(storage=MemoryStorage())

# ── States ────────────────────────────────────────────────────────────────────
class SearchState(StatesGroup):
    waiting_query = State()

# ── Genres ────────────────────────────────────────────────────────────────────
GENRES = {
    28:   "Боевик",     12:   "Приключения", 16:   "Анимация",
    35:   "Комедия",    80:   "Криминал",    99:   "Документальный",
    18:   "Драма",      14:   "Фэнтези",     27:   "Ужасы",
    9648: "Мистика",    10749:"Мелодрама",   878:  "Фантастика",
    53:   "Триллер",    10752:"Военный",     37:   "Вестерн",
}

# ── TMDB helpers ──────────────────────────────────────────────────────────────
async def tmdb(endpoint: str, **params) -> dict | None:
    params.setdefault("language", LANG)
    params["api_key"] = TMDB_KEY
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{TMDB_URL}{endpoint}", params=params) as r:
            if r.status != 200:
                log.warning("TMDB %s → %s", endpoint, r.status)
                return None
            return await r.json()

def stars(v: float) -> str:
    filled = round(v / 2)
    return "★" * filled + "☆" * (5 - filled)

def fmt_movie(m: dict, detail: bool = False) -> str:
    title   = m.get("title", "—")
    year    = (m.get("release_date") or "")[:4] or "—"
    rating  = m.get("vote_average", 0)
    genres  = ", ".join(GENRES.get(g["id"] if isinstance(g, dict) else g, "?")
                        for g in (m.get("genres") or [])[:3]) or "—"
    runtime = m.get("runtime")
    votes   = m.get("vote_count", 0)
    overview= m.get("overview") or "Описание отсутствует."

    text = f"🎬 <b>{title}</b> ({year})\n"
    text += f"⭐ {stars(rating)} {rating:.1f}  •  🗳 {votes:,}\n"
    if genres != "—":
        text += f"🏷 {genres}\n"
    if runtime:
        text += f"⏱ {runtime} мин\n"
    if detail:
        text += f"\n{overview[:600]}"
        if len(overview) > 600:
            text += "…"
    return text

# ── Keyboards ─────────────────────────────────────────────────────────────────
def main_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔍 Поиск по названию", callback_data="act:search")
    b.button(text="🎭 По жанру",          callback_data="act:genre")
    b.button(text="📅 По году",            callback_data="act:year")
    b.button(text="🔥 Популярные",         callback_data="act:popular")
    b.button(text="⭐ Топ рейтинга",       callback_data="act:top_rated")
    b.button(text="🆕 Новинки",            callback_data="act:upcoming")
    b.adjust(2, 2, 2)
    return b.as_markup()

def genres_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for gid, name in GENRES.items():
        b.button(text=name, callback_data=f"genre:{gid}")
    b.button(text="« Назад", callback_data="act:back")
    b.adjust(3)
    return b.as_markup()

def years_keyboard() -> InlineKeyboardMarkup:
    import datetime
    b = InlineKeyboardBuilder()
    cur = datetime.date.today().year
    decades = [
        ("2020-е", "2020,2029"),
        ("2010-е", "2010,2019"),
        ("2000-е", "2000,2009"),
        ("1990-е", "1990,1999"),
        ("1980-е", "1980,1989"),
        ("до 1980", "1900,1979"),
    ]
    for label, val in decades:
        b.button(text=label, callback_data=f"year:{val}")
    b.button(text="Конкретный год…", callback_data="act:year_exact")
    b.button(text="« Назад", callback_data="act:back")
    b.adjust(2)
    return b.as_markup()

def movies_keyboard(movies: list, page: int, total: int, context: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in movies:
        title = m.get("title","—")
        year  = (m.get("release_date") or "")[:4]
        label = f"{title} ({year})" if year else title
        b.button(text=label[:40], callback_data=f"movie:{m['id']}")
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"page:{context}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{min(total,20)}", callback_data="noop"))
    if page < min(total, 20):
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"page:{context}:{page+1}"))
    b.row(*nav)
    b.row(InlineKeyboardButton(text="« Главное меню", callback_data="act:back"))
    b.adjust(1)
    return b.as_markup()

def movie_detail_keyboard(movie_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🎬 На TMDB", url=f"https://www.themoviedb.org/movie/{movie_id}")
    b.button(text="« К результатам", callback_data="act:back_results")
    b.button(text="🏠 Главное меню",  callback_data="act:back")
    b.adjust(1)
    return b.as_markup()

# ── Session store (simple in-memory) ─────────────────────────────────────────
user_sessions: dict[int, dict] = {}

def session(uid: int) -> dict:
    if uid not in user_sessions:
        user_sessions[uid] = {"last_results": [], "context": ""}
    return user_sessions[uid]

# ── Handlers ──────────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(
        "👋 <b>Привет!</b> Я помогу найти фильм.\n\nВыберите способ поиска:",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "ℹ️ <b>Команды:</b>\n"
        "/start — главное меню\n"
        "/search — поиск по названию\n"
        "/popular — популярные фильмы\n"
        "/top — топ рейтинга\n"
        "/upcoming — новинки\n\n"
        "Также можно просто написать название фильма.",
        parse_mode="HTML"
    )

@dp.message(Command("popular"))
async def cmd_popular(msg: Message):
    await show_popular(msg)

@dp.message(Command("top"))
async def cmd_top(msg: Message):
    await show_top_rated(msg)

@dp.message(Command("upcoming"))
async def cmd_upcoming(msg: Message):
    await show_upcoming(msg)

@dp.message(Command("search"))
async def cmd_search(msg: Message, state: FSMContext):
    await state.set_state(SearchState.waiting_query)
    await msg.answer("🔍 Введите название фильма:", parse_mode="HTML")

# ── Catch plain text as search ────────────────────────────────────────────────
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(msg: Message, state: FSMContext):
    cur = await state.get_state()
    if cur == SearchState.waiting_query:
        await state.clear()
    await do_search(msg, msg.text.strip(), 1)

# ── Callbacks ─────────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "act:search")
async def cb_search(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(SearchState.waiting_query)
    await cb.message.answer("🔍 Введите название фильма:")

@dp.callback_query(F.data == "act:genre")
async def cb_genre(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("🎭 Выберите жанр:", reply_markup=genres_keyboard())

@dp.callback_query(F.data == "act:year")
async def cb_year(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("📅 Выберите период:", reply_markup=years_keyboard())

@dp.callback_query(F.data == "act:popular")
async def cb_popular(cb: CallbackQuery):
    await cb.answer()
    await show_popular(cb.message, edit=True)

@dp.callback_query(F.data == "act:top_rated")
async def cb_top(cb: CallbackQuery):
    await cb.answer()
    await show_top_rated(cb.message, edit=True)

@dp.callback_query(F.data == "act:upcoming")
async def cb_upcoming(cb: CallbackQuery):
    await cb.answer()
    await show_upcoming(cb.message, edit=True)

@dp.callback_query(F.data == "act:back")
async def cb_back(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await cb.message.edit_text(
        "Выберите способ поиска:",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "act:back_results")
async def cb_back_results(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    s   = session(uid)
    if s.get("last_results"):
        ctx = s.get("context", "popular")
        kb  = movies_keyboard(s["last_results"], s.get("page", 1), s.get("total_pages", 1), ctx)
        await cb.message.edit_text(
            s.get("list_text", "Результаты поиска:"),
            parse_mode="HTML",
            reply_markup=kb
        )
    else:
        await cb.message.edit_text("Выберите способ поиска:", reply_markup=main_keyboard())

@dp.callback_query(F.data.startswith("genre:"))
async def cb_genre_select(cb: CallbackQuery):
    await cb.answer()
    gid = int(cb.data.split(":")[1])
    name = GENRES.get(gid, "Жанр")
    data = await tmdb("/discover/movie", with_genres=gid,
                      sort_by="popularity.desc", **{"vote_count.gte": 50})
    if not data:
        await cb.answer("Ошибка запроса", show_alert=True); return
    movies = data.get("results", [])
    uid = cb.from_user.id
    s   = session(uid)
    s.update(last_results=movies, page=1, total_pages=data["total_pages"],
             context=f"genre:{gid}", list_text=f"🎭 <b>{name}</b> — найдено {data['total_results']:,}")
    await cb.message.edit_text(
        s["list_text"],
        parse_mode="HTML",
        reply_markup=movies_keyboard(movies, 1, data["total_pages"], f"genre:{gid}")
    )

@dp.callback_query(F.data.startswith("year:"))
async def cb_year_select(cb: CallbackQuery):
    await cb.answer()
    _, rng = cb.data.split(":", 1)
    y1, y2 = rng.split(",")
    data = await tmdb("/discover/movie",
                      sort_by="popularity.desc",
                      **{"primary_release_date.gte": f"{y1}-01-01",
                         "primary_release_date.lte": f"{y2}-12-31",
                         "vote_count.gte": 100})
    if not data:
        await cb.answer("Ошибка запроса", show_alert=True); return
    movies = data.get("results", [])
    label  = f"{y1}–{y2}"
    uid = cb.from_user.id
    s   = session(uid)
    s.update(last_results=movies, page=1, total_pages=data["total_pages"],
             context=f"year:{rng}", list_text=f"📅 <b>{label}</b> — найдено {data['total_results']:,}")
    await cb.message.edit_text(
        s["list_text"],
        parse_mode="HTML",
        reply_markup=movies_keyboard(movies, 1, data["total_pages"], f"year:{rng}")
    )

@dp.callback_query(F.data == "act:year_exact")
async def cb_year_exact(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(SearchState.waiting_query)
    await state.update_data(mode="year")
    await cb.message.answer("📅 Введите год (например: 2023):")

@dp.callback_query(F.data.startswith("movie:"))
async def cb_movie(cb: CallbackQuery):
    await cb.answer()
    mid  = int(cb.data.split(":")[1])
    data = await tmdb(f"/movie/{mid}")
    if not data:
        await cb.answer("Не удалось получить данные", show_alert=True); return

    text  = fmt_movie(data, detail=True)
    poster= data.get("poster_path")

    if poster:
        try:
            await cb.message.answer_photo(
                photo=f"{IMG_BASE}{poster}",
                caption=text,
                parse_mode="HTML",
                reply_markup=movie_detail_keyboard(mid)
            )
        except Exception:
            await cb.message.answer(text, parse_mode="HTML",
                                    reply_markup=movie_detail_keyboard(mid))
    else:
        await cb.message.answer(text, parse_mode="HTML",
                                reply_markup=movie_detail_keyboard(mid))

@dp.callback_query(F.data.startswith("page:"))
async def cb_page(cb: CallbackQuery):
    await cb.answer()
    parts   = cb.data.split(":")
    context = parts[1] + (":" + parts[2] if len(parts) > 3 else "")
    page    = int(parts[-1])

    uid = cb.from_user.id
    s   = session(uid)

    # Re-fetch for the page
    if context.startswith("search:"):
        q    = context[7:]
        data = await tmdb("/search/movie", query=q, page=page)
    elif context.startswith("genre:"):
        gid  = int(context[6:])
        data = await tmdb("/discover/movie", with_genres=gid,
                          sort_by="popularity.desc", page=page, **{"vote_count.gte": 50})
    elif context.startswith("year:"):
        rng  = context[5:]
        y1, y2 = rng.split(",")
        data = await tmdb("/discover/movie",
                          sort_by="popularity.desc", page=page,
                          **{"primary_release_date.gte": f"{y1}-01-01",
                             "primary_release_date.lte": f"{y2}-12-31",
                             "vote_count.gte": 100})
    elif context == "popular":
        data = await tmdb("/movie/popular", page=page)
    elif context == "top_rated":
        data = await tmdb("/movie/top_rated", page=page)
    elif context == "upcoming":
        data = await tmdb("/movie/upcoming", page=page)
    else:
        data = await tmdb("/movie/popular", page=page)

    if not data: return
    movies = data.get("results", [])
    s.update(last_results=movies, page=page, total_pages=data["total_pages"])
    await cb.message.edit_text(
        s.get("list_text", "Результаты:"),
        parse_mode="HTML",
        reply_markup=movies_keyboard(movies, page, data["total_pages"], context)
    )

@dp.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()

# ── Helper coroutines ─────────────────────────────────────────────────────────
async def do_search(msg: Message, query: str, page: int):
    data = await tmdb("/search/movie", query=query, page=page)
    if not data or not data.get("results"):
        await msg.answer("😔 Ничего не найдено. Попробуйте другой запрос.",
                         reply_markup=main_keyboard())
        return
    movies = data["results"]
    ctx    = f"search:{query}"
    uid    = msg.from_user.id
    s      = session(uid)
    label  = f"🔍 <b>«{query}»</b> — {data['total_results']:,} результатов"
    s.update(last_results=movies, page=page, total_pages=data["total_pages"],
             context=ctx, list_text=label)
    await msg.answer(label, parse_mode="HTML",
                     reply_markup=movies_keyboard(movies, page, data["total_pages"], ctx))

async def show_popular(msg: Message, edit: bool = False):
    data = await tmdb("/movie/popular")
    if not data: return
    movies = data["results"]
    uid = msg.from_user.id if hasattr(msg, "from_user") else 0
    s   = session(uid)
    label = f"🔥 <b>Популярные фильмы</b>"
    s.update(last_results=movies, page=1, total_pages=data["total_pages"],
             context="popular", list_text=label)
    kb = movies_keyboard(movies, 1, data["total_pages"], "popular")
    if edit:
        await msg.edit_text(label, parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(label, parse_mode="HTML", reply_markup=kb)

async def show_top_rated(msg: Message, edit: bool = False):
    data = await tmdb("/movie/top_rated")
    if not data: return
    movies = data["results"]
    uid = msg.from_user.id if hasattr(msg, "from_user") else 0
    s   = session(uid)
    label = f"⭐ <b>Топ рейтинга</b>"
    s.update(last_results=movies, page=1, total_pages=data["total_pages"],
             context="top_rated", list_text=label)
    kb = movies_keyboard(movies, 1, data["total_pages"], "top_rated")
    if edit:
        await msg.edit_text(label, parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(label, parse_mode="HTML", reply_markup=kb)

async def show_upcoming(msg: Message, edit: bool = False):
    data = await tmdb("/movie/upcoming")
    if not data: return
    movies = data["results"]
    uid = msg.from_user.id if hasattr(msg, "from_user") else 0
    s   = session(uid)
    label = f"🆕 <b>Новинки в кино</b>"
    s.update(last_results=movies, page=1, total_pages=data["total_pages"],
             context="upcoming", list_text=label)
    kb = movies_keyboard(movies, 1, data["total_pages"], "upcoming")
    if edit:
        await msg.edit_text(label, parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(label, parse_mode="HTML", reply_markup=kb)

# ── Run ───────────────────────────────────────────────────────────────────────
async def main():
    log.info("CineSearch Bot starting…")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
