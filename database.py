import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = "football.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS players (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username    TEXT DEFAULT '',
                first_name  TEXT DEFAULT '',
                last_name   TEXT DEFAULT '',
                rating      REAL DEFAULT 5.0,
                is_admin    INTEGER DEFAULT 0,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS games (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                time        TEXT NOT NULL,
                location    TEXT NOT NULL,
                max_players INTEGER DEFAULT 20,
                status      TEXT DEFAULT 'open',
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS registrations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id     INTEGER NOT NULL,
                player_id   INTEGER NOT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(game_id, player_id),
                FOREIGN KEY (game_id) REFERENCES games(id),
                FOREIGN KEY (player_id) REFERENCES players(id)
            );

            CREATE TABLE IF NOT EXISTS preferences (
                player_id   INTEGER NOT NULL,
                partner_id  INTEGER NOT NULL,
                PRIMARY KEY (player_id, partner_id),
                FOREIGN KEY (player_id) REFERENCES players(id),
                FOREIGN KEY (partner_id) REFERENCES players(id)
            );

            CREATE TABLE IF NOT EXISTS teams (
                game_id     INTEGER NOT NULL,
                team_number INTEGER NOT NULL,
                player_id   INTEGER NOT NULL,
                PRIMARY KEY (game_id, player_id),
                FOREIGN KEY (game_id) REFERENCES games(id),
                FOREIGN KEY (player_id) REFERENCES players(id)
            );
        """)


# ─── Players ─────────────────────────────────────────────────────

def get_or_create_player(telegram_id: int, username: str = "",
                         first_name: str = "", last_name: str = "") -> dict:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row:
            # Обновляем имя/username если изменились
            db.execute(
                "UPDATE players SET username=?, first_name=?, last_name=? WHERE telegram_id=?",
                (username, first_name, last_name, telegram_id),
            )
            row = db.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
        else:
            db.execute(
                "INSERT INTO players (telegram_id, username, first_name, last_name) VALUES (?,?,?,?)",
                (telegram_id, username, first_name, last_name),
            )
            row = db.execute(
                "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
            ).fetchone()
        return dict(row)


def get_player_by_id(player_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        return dict(row) if row else None


def get_all_players() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM players ORDER BY rating DESC").fetchall()
        return [dict(r) for r in rows]


def set_player_rating(player_id: int, rating: float):
    with get_db() as db:
        db.execute("UPDATE players SET rating = ? WHERE id = ?", (rating, player_id))


def set_admin(player_id: int, is_admin: bool):
    with get_db() as db:
        db.execute("UPDATE players SET is_admin = ? WHERE id = ?", (int(is_admin), player_id))


def is_admin(player_id: int) -> bool:
    with get_db() as db:
        row = db.execute("SELECT is_admin FROM players WHERE id = ?", (player_id,)).fetchone()
        return bool(row["is_admin"]) if row else False


# ─── Games ───────────────────────────────────────────────────────

def create_game(date: str, time: str, location: str, max_players: int) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO games (date, time, location, max_players) VALUES (?,?,?,?)",
            (date, time, location, max_players),
        )
        return cur.lastrowid


def get_active_game() -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM games WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_all_games() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM games ORDER BY id DESC LIMIT 20").fetchall()
        return [dict(r) for r in rows]


def close_game(game_id: int):
    with get_db() as db:
        db.execute("UPDATE games SET status='closed' WHERE id=?", (game_id,))


# ─── Registrations ──────────────────────────────────────────────

def register_player(game_id: int, player_id: int) -> bool:
    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM registrations WHERE game_id=? AND player_id=?",
            (game_id, player_id),
        ).fetchone()
        if existing:
            return False
        db.execute(
            "INSERT INTO registrations (game_id, player_id) VALUES (?,?)",
            (game_id, player_id),
        )
        return True


def unregister_player(game_id: int, player_id: int) -> bool:
    with get_db() as db:
        cur = db.execute(
            "DELETE FROM registrations WHERE game_id=? AND player_id=?",
            (game_id, player_id),
        )
        return cur.rowcount > 0


def get_registered_players(game_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            """SELECT p.* FROM players p
               JOIN registrations r ON r.player_id = p.id
               WHERE r.game_id = ?
               ORDER BY p.rating DESC""",
            (game_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def is_registered(game_id: int, player_id: int) -> bool:
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM registrations WHERE game_id=? AND player_id=?",
            (game_id, player_id),
        ).fetchone()
        return row is not None


def count_registrations(game_id: int) -> int:
    with get_db() as db:
        return db.execute(
            "SELECT COUNT(*) FROM registrations WHERE game_id=?", (game_id,)
        ).fetchone()[0]


# ─── Preferences ────────────────────────────────────────────────

def set_preference(player_id: int, partner_id: int):
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO preferences (player_id, partner_id) VALUES (?,?)",
            (player_id, partner_id),
        )


def get_preference(player_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            """SELECT p.* FROM players p
               JOIN preferences pr ON pr.partner_id = p.id
               WHERE pr.player_id = ?""",
            (player_id,),
        ).fetchone()
        return dict(row) if row else None


def clear_preference(player_id: int):
    with get_db() as db:
        db.execute("DELETE FROM preferences WHERE player_id=?", (player_id,))


def get_all_preferences() -> dict[int, int]:
    with get_db() as db:
        rows = db.execute("SELECT player_id, partner_id FROM preferences").fetchall()
        return {r["player_id"]: r["partner_id"] for r in rows}


# ─── Teams ──────────────────────────────────────────────────────

def save_teams(game_id: int, teams: list[list[dict]]):
    with get_db() as db:
        db.execute("DELETE FROM teams WHERE game_id=?", (game_id,))
        for team_number, players in enumerate(teams, start=1):
            for player in players:
                db.execute(
                    "INSERT INTO teams (game_id, team_number, player_id) VALUES (?,?,?)",
                    (game_id, team_number, player["id"]),
                )


def get_teams(game_id: int) -> dict[int, list[dict]]:
    with get_db() as db:
        rows = db.execute(
            """SELECT p.*, t.team_number FROM players p
               JOIN teams t ON t.player_id = p.id
               WHERE t.game_id = ?
               ORDER BY t.team_number, p.rating DESC""",
            (game_id,),
        ).fetchall()
        result: dict[int, list[dict]] = {}
        for r in rows:
            d = dict(r)
            tn = d.pop("team_number")
            result.setdefault(tn, []).append(d)
        return result


def swap_players(game_id: int, player1_id: int, player2_id: int) -> bool:
    with get_db() as db:
        t1 = db.execute(
            "SELECT team_number FROM teams WHERE game_id=? AND player_id=?",
            (game_id, player1_id),
        ).fetchone()
        t2 = db.execute(
            "SELECT team_number FROM teams WHERE game_id=? AND player_id=?",
            (game_id, player2_id),
        ).fetchone()
        if not t1 or not t2 or t1["team_number"] == t2["team_number"]:
            return False
        db.execute(
            "UPDATE teams SET team_number=? WHERE game_id=? AND player_id=?",
            (t2["team_number"], game_id, player1_id),
        )
        db.execute(
            "UPDATE teams SET team_number=? WHERE game_id=? AND player_id=?",
            (t1["team_number"], game_id, player2_id),
        )
        return True
