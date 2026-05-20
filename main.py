import os
import hashlib
import hmac
import time as _time
import asyncio
import threading
import random
from itertools import combinations
from urllib.parse import urlencode

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

import database as db
from auth import verify_init_data

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")

app = FastAPI(title="Football Mini App")


# --- Auth ---

async def get_current_player(request: Request) -> dict:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    # 1. Standard Telegram WebApp verification
    if init_data and BOT_TOKEN:
        user_data = verify_init_data(init_data, BOT_TOKEN)
        if user_data:
            return db.get_or_create_player(
                telegram_id=user_data["telegram_id"],
                username=user_data.get("username", ""),
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
            )

    # 2. Signed URL (query params)
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
                    player = db.get_or_create_player(
                        telegram_id=int(uid),
                        username=request.query_params.get("un", ""),
                        first_name=request.query_params.get("fn", ""),
                        last_name=request.query_params.get("ln", ""),
                    )
                    if int(uid) in [982854595]:
                        db.set_admin(player["id"], True)
                        player["is_admin"] = 1
                    return player
        except (ValueError, KeyError):
            pass

    # 3. Dev mode
    if not BOT_TOKEN:
        return db.get_or_create_player(999999, "dev_user", "Dev", "User")

    raise HTTPException(status_code=403, detail="Invalid Telegram auth")


def require_admin(player: dict = Depends(get_current_player)):
    if not player.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return player


# --- Models ---

class GameCreate(BaseModel):
    date: str
    time: str
    location: str

class TeamsUpdate(BaseModel):
    teams: dict  # {team_number: [player_id, ...]}

class MatchCreate(BaseModel):
    game_id: int
    team_a: int
    team_b: int
    result: Optional[str] = None  # "team_a", "team_b", "draw", or null

class MatchUpdate(BaseModel):
    result: Optional[str] = None

class GoalCreate(BaseModel):
    match_id: int
    player_id: int
    assist_player_id: Optional[int] = None

class RatingUpdate(BaseModel):
    player_id: int
    rating: float

class GuestAdd(BaseModel):
    name: str
    rating: float = 5.0


# --- Endpoints ---

@app.get("/api/me")
async def get_me(player: dict = Depends(get_current_player)):
    return {"player": player}


@app.get("/api/players")
async def get_players(player: dict = Depends(get_current_player)):
    return {"players": db.get_all_players()}


@app.get("/api/stats")
async def get_stats(player: dict = Depends(get_current_player)):
    return {"stats": db.get_player_stats()}


# --- Games ---

@app.get("/api/games")
async def get_games(player: dict = Depends(get_current_player)):
    return {"games": db.get_all_games()}


@app.get("/api/game")
async def get_active_game_endpoint(player: dict = Depends(get_current_player)):
    game = db.get_active_game()
    if not game:
        return {"game": None, "teams": {}, "matches": [], "goals": []}
    teams = db.get_teams(game["id"])
    matches = db.get_matches(game["id"])
    goals = db.get_game_goals(game["id"])
    return {"game": game, "teams": teams, "matches": matches, "goals": goals}


@app.get("/api/game/{game_id}")
async def get_game_detail(game_id: int, player: dict = Depends(get_current_player)):
    game = db.get_game_by_id(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    teams = db.get_teams(game_id)
    matches = db.get_matches(game_id)
    goals = db.get_game_goals(game_id)
    return {"game": game, "teams": teams, "matches": matches, "goals": goals}


@app.post("/api/game")
async def create_game(data: GameCreate, admin: dict = Depends(require_admin)):
    game_id = db.create_game(data.date, data.time, data.location)
    return {"game_id": game_id, "status": "created"}


@app.post("/api/game/close")
async def close_game(admin: dict = Depends(require_admin)):
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    db.close_game(game["id"])
    return {"status": "closed"}


@app.delete("/api/game/{game_id}")
async def delete_game(game_id: int, admin: dict = Depends(require_admin)):
    game = db.get_game_by_id(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    db.delete_game(game_id)
    return {"status": "deleted"}


# --- Teams ---

@app.post("/api/teams/{game_id}")
async def update_teams(game_id: int, data: TeamsUpdate, admin: dict = Depends(require_admin)):
    game = db.get_game_by_id(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    db.save_teams(game_id, data.teams)
    return {"status": "saved"}


@app.get("/api/teams/{game_id}")
async def get_teams(game_id: int, player: dict = Depends(get_current_player)):
    teams = db.get_teams(game_id)
    return {"teams": teams}


# --- Matches ---

@app.post("/api/match")
async def create_match(data: MatchCreate, admin: dict = Depends(require_admin)):
    if data.result and data.result not in ("team_a", "team_b", "draw"):
        raise HTTPException(status_code=400, detail="Invalid result")
    match_id = db.create_match(data.game_id, data.team_a, data.team_b, data.result)
    return {"match_id": match_id, "status": "created"}


@app.put("/api/match/{match_id}")
async def update_match(match_id: int, data: MatchUpdate, admin: dict = Depends(require_admin)):
    match = db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if data.result and data.result not in ("team_a", "team_b", "draw"):
        raise HTTPException(status_code=400, detail="Invalid result")
    db.update_match(match_id, data.result)
    return {"status": "updated"}


@app.delete("/api/match/{match_id}")
async def delete_match(match_id: int, admin: dict = Depends(require_admin)):
    match = db.get_match_by_id(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    db.delete_match(match_id)
    return {"status": "deleted"}


# --- Goals ---

@app.post("/api/goal")
async def create_goal(data: GoalCreate, admin: dict = Depends(require_admin)):
    match = db.get_match_by_id(data.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    goal_id = db.add_goal(data.match_id, data.player_id, data.assist_player_id)
    return {"goal_id": goal_id, "status": "created"}


@app.delete("/api/goal/{goal_id}")
async def delete_goal(goal_id: int, admin: dict = Depends(require_admin)):
    db.delete_goal(goal_id)
    return {"status": "deleted"}


@app.get("/api/goals/{match_id}")
async def get_goals(match_id: int, player: dict = Depends(get_current_player)):
    return {"goals": db.get_goals(match_id)}


# --- Rating & Guest ---

@app.delete("/api/player/{player_id}")
async def delete_player(player_id: int, admin: dict = Depends(require_admin)):
    player = db.get_player_by_id(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    db.delete_player(player_id)
    return {"status": "deleted"}


@app.post("/api/rating")
async def update_rating(data: RatingUpdate, admin: dict = Depends(require_admin)):
    if not 1.0 <= data.rating <= 10.0:
        raise HTTPException(status_code=400, detail="Rating 1.0-10.0")
    db.set_player_rating(data.player_id, data.rating)
    return {"status": "updated"}


@app.post("/api/guest")
async def add_guest(data: GuestAdd, admin: dict = Depends(require_admin)):
    if not 1.0 <= data.rating <= 10.0:
        raise HTTPException(status_code=400, detail="Rating 1.0-10.0")
    fake_tg_id = -random.randint(100000, 9999999)
    player = db.get_or_create_player(
        telegram_id=fake_tg_id,
        username="",
        first_name=data.name,
        last_name="(guest)",
    )
    db.set_player_rating(player["id"], data.rating)
    return {"status": "added", "player": player}


# --- Frontend ---

@app.get("/")
async def serve_index():
    return FileResponse("frontend/index.html")

if os.path.exists("frontend"):
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


# --- Telegram Bot ---

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
            text="Football App",
            web_app=WebAppInfo(url=url),
        )]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "Nажми кнопку ниже",
        reply_markup=keyboard,
    )


# --- Match recording bot (inline buttons) ---

def _player_name(p):
    name = (p.get("first_name") or p.get("username") or "?").strip()
    return name.split()[0] if name else "?"


def _build_scorers_keyboard(match_id, players):
    buttons = []
    row = []
    for p in players:
        row.append(InlineKeyboardButton(
            _player_name(p),
            callback_data=f"goal:{match_id}:{p['id']}"
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("Готово ✓", callback_data=f"done:{match_id}")])
    return InlineKeyboardMarkup(buttons)


def _format_goals(goals):
    if not goals:
        return "нет"
    parts = []
    for g in goals:
        scorer = (g.get("scorer_first") or "?").split()[0]
        assist = g.get("assist_first")
        if assist:
            parts.append(f"{scorer} (ас. {assist.split()[0]})")
        else:
            parts.append(scorer)
    return ", ".join(parts)


async def tg_match(update: Update, context):
    if not update.message:
        return
    game = db.get_active_game()
    if not game:
        await update.message.reply_text("Нет активной игры.")
        return
    teams = db.get_teams(game["id"])
    team_nums = sorted(teams.keys())
    if len(team_nums) < 2:
        await update.message.reply_text("Команды ещё не набраны.")
        return
    buttons = [
        [InlineKeyboardButton(
            f"Команда {a} vs Команда {b}",
            callback_data=f"match:{a}:{b}"
        )]
        for a, b in combinations(team_nums, 2)
    ]
    await update.message.reply_text(
        "Выберите пару команд:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def tg_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")

    try:
        if parts[0] == "match":
            team_a, team_b = int(parts[1]), int(parts[2])
            game = db.get_active_game()
            if not game:
                await query.edit_message_text("Нет активной игры.")
                return
            match_id = db.create_match(game["id"], team_a, team_b, None)
            teams = db.get_teams(game["id"])
            a_str = ", ".join(_player_name(p) for p in teams.get(team_a, []))
            b_str = ", ".join(_player_name(p) for p in teams.get(team_b, []))
            buttons = [[
                InlineKeyboardButton(f"🏆 Команда {team_a}", callback_data=f"result:{match_id}:team_a"),
                InlineKeyboardButton("🤝 Ничья", callback_data=f"result:{match_id}:draw"),
                InlineKeyboardButton(f"🏆 Команда {team_b}", callback_data=f"result:{match_id}:team_b"),
            ]]
            await query.edit_message_text(
                f"Команда {team_a}: {a_str}\nКоманда {team_b}: {b_str}\n\nКто победил?",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif parts[0] == "result":
            match_id, winner = int(parts[1]), parts[2]
            db.update_match(match_id, winner)
            match = db.get_match_by_id(match_id)
            teams = db.get_teams(match["game_id"])
            pa = teams.get(match["team_a"], [])
            pb = teams.get(match["team_b"], [])
            result_labels = {
                "team_a": f"🏆 Команда {match['team_a']}",
                "team_b": f"🏆 Команда {match['team_b']}",
                "draw": "🤝 Ничья",
            }
            keyboard = _build_scorers_keyboard(match_id, pa + pb)
            await query.edit_message_text(
                f"Результат: {result_labels[winner]}\n\nКто забил?",
                reply_markup=keyboard
            )

        elif parts[0] == "goal":
            match_id, player_id = int(parts[1]), int(parts[2])
            goal_id = db.add_goal(match_id, player_id, None)
            match = db.get_match_by_id(match_id)
            teams = db.get_teams(match["game_id"])
            all_players = teams.get(match["team_a"], []) + teams.get(match["team_b"], [])
            scorer = next((p for p in all_players if p["id"] == player_id), None)
            scorer_name = _player_name(scorer) if scorer else "?"
            buttons = []
            row = []
            for p in all_players:
                if p["id"] == player_id:
                    continue
                row.append(InlineKeyboardButton(
                    _player_name(p),
                    callback_data=f"assist:{match_id}:{goal_id}:{p['id']}"
                ))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([InlineKeyboardButton(
                "Без ассиста",
                callback_data=f"assist:{match_id}:{goal_id}:none"
            )])
            await query.edit_message_text(
                f"Гол: {scorer_name}\nАссист?",
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        elif parts[0] == "assist":
            match_id, goal_id = int(parts[1]), int(parts[2])
            assist_id = None if parts[3] == "none" else int(parts[3])
            db.update_goal_assist(goal_id, assist_id)
            match = db.get_match_by_id(match_id)
            teams = db.get_teams(match["game_id"])
            all_players = teams.get(match["team_a"], []) + teams.get(match["team_b"], [])
            goals = db.get_goals(match_id)
            keyboard = _build_scorers_keyboard(match_id, all_players)
            await query.edit_message_text(
                f"Голы: {_format_goals(goals)}\n\nЕщё?",
                reply_markup=keyboard
            )

        elif parts[0] == "done":
            match_id = int(parts[1])
            match = db.get_match_by_id(match_id)
            goals = db.get_goals(match_id)
            teams = db.get_teams(match["game_id"])
            pa = teams.get(match["team_a"], [])
            pb = teams.get(match["team_b"], [])
            result_labels = {
                "team_a": f"🏆 Команда {match['team_a']}",
                "team_b": f"🏆 Команда {match['team_b']}",
                "draw": "🤝 Ничья",
            }
            a_str = ", ".join(_player_name(p) for p in pa)
            b_str = ", ".join(_player_name(p) for p in pb)
            await query.edit_message_text(
                f"✅ Матч записан!\n"
                f"Команда {match['team_a']} ({a_str}) vs Команда {match['team_b']} ({b_str})\n"
                f"Результат: {result_labels.get(match.get('result'), '—')}\n"
                f"Голы: {_format_goals(goals)}"
            )

    except Exception as e:
        print(f"[bot] callback error: {e}")
        try:
            await query.edit_message_text(f"Ошибка: {e}")
        except Exception:
            pass


def run_bot():
    if not BOT_TOKEN or not WEBAPP_URL:
        print("BOT_TOKEN or WEBAPP_URL not set - bot not started")
        return
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run():
        bot_app = Application.builder().token(BOT_TOKEN).build()
        bot_app.add_handler(CommandHandler("start", tg_start))
        bot_app.add_handler(CommandHandler("match", tg_match))
        bot_app.add_handler(CallbackQueryHandler(tg_callback))
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(drop_pending_updates=True)
        print("Telegram bot started")
        while True:
            await asyncio.sleep(3600)

    loop.run_until_complete(_run())


# --- Startup ---

@app.on_event("startup")
async def startup():
    db.init_db()
    ADMIN_IDS = [982854595]
    for tid in ADMIN_IDS:
        with db.get_db() as conn:
            conn.execute("UPDATE players SET is_admin = 1 WHERE telegram_id = ?", (tid,))
    if not BOT_TOKEN:
        print("BOT_TOKEN not set - dev mode")
    print("Football Mini App started")
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
