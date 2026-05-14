"""
FastAPI backend для Football Mini App.

Все эндпоинты требуют заголовок X-Telegram-Init-Data с initData из Telegram WebApp.
"""

import os
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import database as db
from auth import verify_init_data
from distribute import distribute, optimize_preferences, team_summary

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

app = FastAPI(title="Football Mini App")


# ─── Auth dependency ─────────────────────────────────────────────

async def get_current_player(request: Request) -> dict:
    init_data = request.headers.get("X-Telegram-Init-Data", "")

    # 1. Стандартная Telegram верификация
    if init_data and BOT_TOKEN:
        user_data = verify_init_data(init_data, BOT_TOKEN)
        if user_data:
            return db.get_or_create_player(
                telegram_id=user_data["telegram_id"],
                username=user_data.get("username", ""),
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
            )

    # 2. Фолбэк: подписанный URL от бота
    import hashlib, hmac, time as _time
    user_header = request.headers.get("X-Telegram-User", "")
    if user_header and BOT_TOKEN:
        import json
        try:
            u = json.loads(user_header)
            uid = str(u.get("uid", ""))
            ts = str(u.get("ts", ""))
            sig = u.get("sig", "")
            # Проверяем подпись
            expected = hmac.new(
                BOT_TOKEN.encode(), f"{uid}:{ts}".encode(), hashlib.sha256
            ).hexdigest()[:32]
            if hmac.compare_digest(expected, sig):
                # Проверяем свежесть (24 часа)
                if abs(_time.time() - int(ts)) < 86400:
                    return db.get_or_create_player(
                        telegram_id=int(uid),
                        username=u.get("un", ""),
                        first_name=u.get("fn", ""),
                        last_name=u.get("ln", ""),
                    )
        except (json.JSONDecodeError, ValueError):
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


# ─── Endpoints: Игрок ───────────────────────────────────────────

@app.get("/api/me")
async def get_me(player: dict = Depends(get_current_player)):
    """Профиль текущего пользователя."""
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
    """Список всех зарегистрированных игроков."""
    players = db.get_all_players()
    return {"players": players}


# ─── Endpoints: Игра ────────────────────────────────────────────

@app.get("/api/game")
async def get_active_game(player: dict = Depends(get_current_player)):
    """Текущая активная игра."""
    game = db.get_active_game()
    if not game:
        return {"game": None, "players": [], "count": 0}
    players = db.get_registered_players(game["id"])
    count = len(players)
    is_registered = db.is_registered(game["id"], player["id"])
    return {
        "game": game,
        "players": players,
        "count": count,
        "is_registered": is_registered,
    }


@app.post("/api/game")
async def create_game(data: GameCreate, admin: dict = Depends(require_admin)):
    """Создать новую игру (только админ)."""
    game_id = db.create_game(data.date, data.time, data.location, data.max_players)
    return {"game_id": game_id, "status": "created"}


@app.post("/api/game/close")
async def close_game(admin: dict = Depends(require_admin)):
    """Закрыть запись на игру (только админ)."""
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    db.close_game(game["id"])
    return {"status": "closed"}


# ─── Endpoints: Запись ──────────────────────────────────────────

@app.post("/api/register")
async def register(player: dict = Depends(get_current_player)):
    """Записаться на активную игру."""
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")

    count = db.count_registrations(game["id"])
    if count >= game["max_players"]:
        raise HTTPException(status_code=400, detail="Game is full")

    added = db.register_player(game["id"], player["id"])
    return {
        "registered": added,
        "count": count + (1 if added else 0),
        "max": game["max_players"],
    }


@app.post("/api/unregister")
async def unregister(player: dict = Depends(get_current_player)):
    """Отписаться от активной игры."""
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    removed = db.unregister_player(game["id"], player["id"])
    count = db.count_registrations(game["id"])
    return {"unregistered": removed, "count": count}


# ─── Endpoints: Партнёр ─────────────────────────────────────────

@app.post("/api/preference")
async def set_preference(data: PreferenceUpdate,
                         player: dict = Depends(get_current_player)):
    """Указать предпочтительного партнёра."""
    db.set_preference(player["id"], data.partner_id)
    partner = db.get_player_by_id(data.partner_id)
    return {"status": "set", "partner": partner}


@app.delete("/api/preference")
async def clear_preference(player: dict = Depends(get_current_player)):
    """Убрать партнёра."""
    db.clear_preference(player["id"])
    return {"status": "cleared"}


# ─── Endpoints: Составы (Админ) ─────────────────────────────────

@app.post("/api/distribute")
async def distribute_teams(admin: dict = Depends(require_admin)):
    """Авто-распределение по командам (только админ)."""
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")

    players = db.get_registered_players(game["id"])
    if len(players) < 4:
        raise HTTPException(status_code=400, detail="Need at least 4 players")

    num_teams = 2 if len(players) <= 15 else (3 if len(players) <= 24 else 4)
    teams = distribute(players, num_teams)

    prefs = db.get_all_preferences()
    game_player_ids = {p["id"] for p in players}
    relevant_prefs = {k: v for k, v in prefs.items()
                      if k in game_player_ids and v in game_player_ids}

    teams, pref_logs = optimize_preferences(teams, relevant_prefs)
    db.save_teams(game["id"], teams)

    summary = team_summary(teams)
    return {"teams": summary, "preference_logs": pref_logs}


@app.get("/api/teams")
async def get_teams(player: dict = Depends(get_current_player)):
    """Получить текущие составы."""
    game = db.get_active_game()
    if not game:
        return {"teams": {}}
    teams = db.get_teams(game["id"])
    # Формируем summary
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
    """Поменять двух игроков командами (только админ)."""
    game = db.get_active_game()
    if not game:
        raise HTTPException(status_code=404, detail="No active game")
    ok = db.swap_players(game["id"], data.player1_id, data.player2_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot swap these players")
    return {"status": "swapped"}


# ─── Endpoints: Рейтинг (Админ) ─────────────────────────────────

@app.post("/api/rating")
async def update_rating(data: RatingUpdate, admin: dict = Depends(require_admin)):
    """Изменить рейтинг игрока (только админ)."""
    if not 1.0 <= data.rating <= 10.0:
        raise HTTPException(status_code=400, detail="Rating must be between 1.0 and 10.0")
    db.set_player_rating(data.player_id, data.rating)
    return {"status": "updated", "player_id": data.player_id, "rating": data.rating}


@app.post("/api/admin/grant")
async def grant_admin(data: RatingUpdate, admin: dict = Depends(require_admin)):
    """Дать/забрать права админа (player_id, rating не используется)."""
    db.set_admin(data.player_id, True)
    return {"status": "admin granted"}


# ─── Frontend ────────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    return FileResponse("frontend/index.html")


# Статика (CSS, JS, если будут отдельные файлы)
if os.path.exists("frontend"):
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ─── Startup ─────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    db.init_db()
    if not BOT_TOKEN:
        print("⚠️  BOT_TOKEN не задан — работаем в dev-режиме без проверки авторизации")
    print("✅ Football Mini App запущен")
