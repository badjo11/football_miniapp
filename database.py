import sqlite3
from contextlib import contextmanager

DB_PATH = "football.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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
                status      TEXT DEFAULT 'active',
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS teams (
                game_id     INTEGER NOT NULL,
                team_number INTEGER NOT NULL,
                player_id   INTEGER NOT NULL,
                PRIMARY KEY (game_id, player_id),
                FOREIGN KEY (game_id) REFERENCES games(id),
                FOREIGN KEY (player_id) REFERENCES players(id)
            );

            CREATE TABLE IF NOT EXISTS matches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id     INTEGER NOT NULL,
                team_a      INTEGER NOT NULL,
                team_b      INTEGER NOT NULL,
                result      TEXT DEFAULT NULL,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (game_id) REFERENCES games(id)
            );

            CREATE TABLE IF NOT EXISTS goals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id        INTEGER NOT NULL,
                player_id       INTEGER NOT NULL,
                assist_player_id INTEGER DEFAULT NULL,
                created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(id),
                FOREIGN KEY (player_id) REFERENCES players(id),
                FOREIGN KEY (assist_player_id) REFERENCES players(id)
            );
        """)


# --- Players ---

def get_or_create_player(telegram_id: int, username: str = "",
                         first_name: str = "", last_name: str = "") -> dict:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM players WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row:
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


# --- Games ---

def create_game(date: str, time: str, location: str) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO games (date, time, location) VALUES (?,?,?)",
            (date, time, location),
        )
        return cur.lastrowid


def get_active_game() -> dict | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM games WHERE status='active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def get_all_games() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM games ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_game_by_id(game_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        return dict(row) if row else None


def close_game(game_id: int):
    with get_db() as db:
        db.execute("UPDATE games SET status='closed' WHERE id=?", (game_id,))


def delete_game(game_id: int):
    with get_db() as db:
        db.execute("DELETE FROM goals WHERE match_id IN (SELECT id FROM matches WHERE game_id=?)", (game_id,))
        db.execute("DELETE FROM matches WHERE game_id=?", (game_id,))
        db.execute("DELETE FROM teams WHERE game_id=?", (game_id,))
        db.execute("DELETE FROM games WHERE id=?", (game_id,))


# --- Teams ---

def save_teams(game_id: int, teams_data: dict):
    """teams_data: {team_number: [player_id, ...]}"""
    with get_db() as db:
        db.execute("DELETE FROM teams WHERE game_id=?", (game_id,))
        for team_number, player_ids in teams_data.items():
            for pid in player_ids:
                db.execute(
                    "INSERT INTO teams (game_id, team_number, player_id) VALUES (?,?,?)",
                    (game_id, int(team_number), pid),
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


def get_player_team(game_id: int, player_id: int) -> int | None:
    with get_db() as db:
        row = db.execute(
            "SELECT team_number FROM teams WHERE game_id=? AND player_id=?",
            (game_id, player_id),
        ).fetchone()
        return row["team_number"] if row else None


# --- Matches ---

def create_match(game_id: int, team_a: int, team_b: int, result: str | None = None) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO matches (game_id, team_a, team_b, result) VALUES (?,?,?,?)",
            (game_id, team_a, team_b, result),
        )
        return cur.lastrowid


def update_match(match_id: int, result: str | None):
    with get_db() as db:
        db.execute("UPDATE matches SET result=? WHERE id=?", (result, match_id))


def delete_match(match_id: int):
    with get_db() as db:
        db.execute("DELETE FROM goals WHERE match_id=?", (match_id,))
        db.execute("DELETE FROM matches WHERE id=?", (match_id,))


def get_matches(game_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM matches WHERE game_id=? ORDER BY id",
            (game_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_match_by_id(match_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        return dict(row) if row else None


# --- Goals ---

def add_goal(match_id: int, player_id: int, assist_player_id: int | None = None) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO goals (match_id, player_id, assist_player_id) VALUES (?,?,?)",
            (match_id, player_id, assist_player_id),
        )
        return cur.lastrowid


def delete_goal(goal_id: int):
    with get_db() as db:
        db.execute("DELETE FROM goals WHERE id=?", (goal_id,))


def get_goals(match_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            """SELECT g.id, g.match_id, g.player_id, g.assist_player_id,
                      p.first_name as scorer_first, p.last_name as scorer_last,
                      a.first_name as assist_first, a.last_name as assist_last
               FROM goals g
               JOIN players p ON p.id = g.player_id
               LEFT JOIN players a ON a.id = g.assist_player_id
               WHERE g.match_id = ?
               ORDER BY g.id""",
            (match_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_game_goals(game_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            """SELECT g.id, g.match_id, g.player_id, g.assist_player_id,
                      p.first_name as scorer_first, p.last_name as scorer_last,
                      a.first_name as assist_first, a.last_name as assist_last
               FROM goals g
               JOIN matches m ON m.id = g.match_id
               JOIN players p ON p.id = g.player_id
               LEFT JOIN players a ON a.id = g.assist_player_id
               WHERE m.game_id = ?
               ORDER BY g.id""",
            (game_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# --- Stats ---

def get_player_stats() -> list[dict]:
    """
    Returns aggregated stats for all players:
    matches, wins, draws, losses, goals, assists
    """
    with get_db() as db:
        # Get all players
        players = db.execute("SELECT * FROM players ORDER BY rating DESC").fetchall()
        players = [dict(p) for p in players]

        for p in players:
            pid = p["id"]

            # Count matches played (player was in a team that played a match with a result)
            matches_rows = db.execute(
                """SELECT m.id, m.team_a, m.team_b, m.result, t.team_number
                   FROM matches m
                   JOIN teams t ON t.game_id = m.game_id AND t.player_id = ?
                   WHERE m.result IS NOT NULL
                     AND (t.team_number = m.team_a OR t.team_number = m.team_b)""",
                (pid,),
            ).fetchall()

            wins = 0
            draws = 0
            losses = 0
            for mr in matches_rows:
                mr = dict(mr)
                my_team = mr["team_number"]
                if mr["result"] == "draw":
                    draws += 1
                elif mr["result"] == "team_a" and my_team == mr["team_a"]:
                    wins += 1
                elif mr["result"] == "team_b" and my_team == mr["team_b"]:
                    wins += 1
                else:
                    losses += 1

            p["matches"] = len(matches_rows)
            p["wins"] = wins
            p["draws"] = draws
            p["losses"] = losses

            # Goals
            goals_count = db.execute(
                "SELECT COUNT(*) FROM goals WHERE player_id=?", (pid,)
            ).fetchone()[0]
            p["goals"] = goals_count

            # Assists
            assists_count = db.execute(
                "SELECT COUNT(*) FROM goals WHERE assist_player_id=?", (pid,)
            ).fetchone()[0]
            p["assists"] = assists_count

        return players
