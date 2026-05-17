import os
import json
import hashlib
import hmac
import time as _time
import asyncio
import threading
from urllib.parse import urlencode

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler

import database as db
from auth import verify_init_data
from distribute import distribute, optimize_preferences, team_summary

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")

app = FastAPI(title="Football Mini App")


# ─── Auth ────────────────────────────────────────────────────────

async def get_current_player(request: Request) -> dict:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user_header = request.headers.get("X-Telegram-User", "")
    print(f"[AUTH] initData: {'есть' if init_data else 'нет'} | X-Telegram-User: {user_header[:80] if user_header else 'нет'}")
    # 1. Стандартная Telegram WebApp верификация
    if init_data and BOT_TOKEN:
        user_data = verify_init_data(init_data, BOT_TOKEN)
        if user_data:
            return db.get_or_create_player(
                telegram_id=user_data["telegram_id"],
                username=user_data.get("username", ""),
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
            )

    # 2. Подписанный URL (через query params)
    uid = request.query_params.get("uid", "")
    ts = request.query_params.get("ts", "")
    sig = request.query_params.get("sig", "")
    if uid and ts and sig and BOT_TOKEN:
        try:
            expected = hmac.new(
                BOT_TOKEN.encode(), (uid + ":" + ts).encode(), hashlib.sha256
            ).hexdigest()[:32]
            if hmac.compare_digest(expected, sig):
                if abs(_time.time() - int(ts)) < 86400:
                    return db.get_or_create_player(
                        telegram_id=int(uid),
                        username=request.query_params.get("un", ""),
                        first_name=request.query_params.get("fn", ""),
                        last_name=request.query_params.get("ln", ""),
                    )
        except (ValueError, KeyError):
            pass
    # 3. Dev-мод
    if not BOT_TOKEN:
        return db.get_or_create_player(999999, "dev_user", "Dev", "User")

    raise HTTPException(status_code=403, detail="Invalid Telegram auth")


def require_admin(player: dict = Depends(get_current_player)):
    if not player.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return player


# ─── Models ──────────────────────────────────────────────────────

class GameCreate(BaseModel):
    date: str
    time: str
    location: str
    max_players: int = 20

class RatingUpdate(BaseModel):
    player_id: int
    rating: float

class PreferenceUpdate(BaseModel):
    partner_id: int

class SwapRequest(BaseModel):
    player1_id: int
    player2_id: int


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/api/me")
async def get_me(player: dict = Depends(get_current_player)):
    preference = db.get_preference(player["id"])
    game = db.get_active_game()
    registered = False
    if game:
        registered = db.is_registered(game["id"], player["id"])
    return {
        "player": player,
        "preference": preference,
        "active_game": game,
        "is_registered": registered,
    }

@app.get("/api/players")
async def get_players(player: dict = Depends(get_current_player)):
    return {"players": db.get_all_players()}

@app.get("/api/game")
async def get_active_game_endpoint(player: dict = Depends(get_current_player)):
    game = db.get_active_game()
    if not game:
        return {"game": None, "players": [], "count": 0, "is_registered": False}
    players = db.get_registered_players(game["id"])
    return {
        "game": game,
        "players": players,
        "count": len(players),
        "is_registered": db.is_registered(game["id"], player["id"]),
    }

@app.post("/api/game")
async def create_game(data: GameCreate, admin: dict = Depends(require_admin)):
    game_id = db.create_game(data.date, data.time, data.location, data.max_players)
    return {"game_id": game_id, "status": "created"}

@app.post("/api/game/close")
async def close_game(admin: dict = Depends(require_admin)):
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    db.close_game(game["id"])
    return {"status": "closed"}

@app.post("/api/register")
async def register(player: dict = Depends(get_current_player)):
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    count = db.count_registrations(game["id"])
    if count >= game["max_players"]:
        raise HTTPException(status_code=400, detail="Game is full")
    added = db.register_player(game["id"], player["id"])
    return {"registered": added, "count": count + (1 if added else 0), "max": game["max_players"]}

@app.post("/api/unregister")
async def unregister(player: dict = Depends(get_current_player)):
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    removed = db.unregister_player(game["id"], player["id"])
    return {"unregistered": removed, "count": db.count_registrations(game["id"])}

@app.post("/api/preference")
async def set_preference(data: PreferenceUpdate, player: dict = Depends(get_current_player)):
    db.set_preference(player["id"], data.partner_id)
    partner = db.get_player_by_id(data.partner_id)
    return {"status": "set", "partner": partner}

@app.delete("/api/preference")
async def clear_preference(player: dict = Depends(get_current_player)):
    db.clear_preference(player["id"])
    return {"status": "cleared"}

@app.post("/api/distribute")
async def distribute_teams(admin: dict = Depends(require_admin)):
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    players = db.get_registered_players(game["id"])
    if len(players) < 4:
        raise HTTPException(status_code=400, detail="Need at least 4 players")
    num_teams = 2 if len(players) <= 15 else (3 if len(players) <= 24 else 4)
    teams = distribute(players, num_teams)
    prefs = db.get_all_preferences()
    game_player_ids = set()
    for p in players:
        game_player_ids.add(p["id"])
    relevant_prefs = {}
    for k, v in prefs.items():
        if k in game_player_ids and v in game_player_ids:
            relevant_prefs[k] = v
    teams, pref_logs = optimize_preferences(teams, relevant_prefs)
    db.save_teams(game["id"], teams)
    summary = team_summary(teams)
    return {"teams": summary, "preference_logs": pref_logs}

@app.get("/api/teams")
async def get_teams(player: dict = Depends(get_current_player)):
    game = db.get_active_game()
    if not game:
        return {"teams": {}}
    teams = db.get_teams(game["id"])
    result = {}
    for tn, players in teams.items():
        total = sum(p["rating"] for p in players)
        result[tn] = {
            "players": players,
            "total_rating": round(total, 1),
            "avg_rating": round(total / len(players), 1) if players else 0,
        }
    return {"game": game, "teams": result}

@app.post("/api/swap")
async def swap(data: SwapRequest, admin: dict = Depends(require_admin)):
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    ok = db.swap_players(game["id"], data.player1_id, data.player2_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot swap")
    return {"status": "swapped"}

@app.post("/api/rating")
async def update_rating(data: RatingUpdate, admin: dict = Depends(require_admin)):
    if not 1.0 <= data.rating <= 10.0:
        raise HTTPException(status_code=400, detail="Rating 1.0-10.0")
    db.set_player_rating(data.player_id, data.rating)
    return {"status": "updated"}


# ─── Frontend ────────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    return FileResponse("frontend/index.html")

if os.path.exists("frontend"):
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ─── Telegram Bot (встроенный) ───────────────────────────────────

def make_signed_url(user):
    ts = str(int(_time.time()))
    data = str(user.id) + ":" + ts
    sig = hmac.new(BOT_TOKEN.encode(), data.encode(), hashlib.sha256).hexdigest()[:32]
    params = urlencode({
        "uid": user.id,
        "un": user.username or "",
        "fn": user.first_name or "",
        "ln": user.last_name or "",
        "ts": ts,
        "sig": sig,
    })
    return WEBAPP_URL + "?" + params


async def tg_start(update: Update, context):
    user = update.effective_user
    url = make_signed_url(user)
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(
            text="⚽ Открыть Football App",
            web_app=WebAppInfo(url=url),
        )]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "👋 Привет! Нажми кнопку ниже ⚽",
        reply_markup=keyboard,
    )


def run_bot():
    if not BOT_TOKEN or not WEBAPP_URL:
        print("⚠️  BOT_TOKEN или WEBAPP_URL не задан — бот не запущен")
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        bot_app = Application.builder().token(BOT_TOKEN).build()
        bot_app.add_handler(CommandHandler("start", tg_start))
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
        print("🤖 Telegram-бот запущен")
        # Держим бота живым
        while True:
            await asyncio.sleep(3600)

    loop.run_until_complete(_run())

# ─── Startup ─────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    db.init_db()
    if not BOT_TOKEN:
        print("⚠️  BOT_TOKEN не задан — dev-режим")
    print("✅ Football Mini App запущен")
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()