import os
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras

    @contextmanager
    def get_db():
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _fetchone(cur):
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    def _fetchall(cur):
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]

    def _execute(db, sql, params=None):
        cur = db.cursor()
        cur.execute(sql, params or ())
        return cur

    _PH = "%s"  # PostgreSQL placeholder

else:
    import sqlite3

    @contextmanager
    def get_db():
        conn = sqlite3.connect("football.db")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _fetchone(cur):
        row = cur.fetchone()
        return dict(row) if row else None

    def _fetchall(cur):
        return [dict(r) for r in cur.fetchall()]

    def _execute(db, sql, params=None):
        return db.execute(sql, params or ())

    _PH = "?"  # SQLite placeholder


def _q(sql):
    """Replace ? placeholders with %s for PostgreSQL."""
    if _PH == "%s":
        return sql.replace("?", "%s")
    return sql


def init_db():
    with get_db() as db:
        if DATABASE_URL:
            # PostgreSQL
            cur = db.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    id          SERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    username    TEXT DEFAULT '',
                    first_name  TEXT DEFAULT '',
                    last_name   TEXT DEFAULT '',
                    rating      REAL DEFAULT 5.0,
                    is_admin    INTEGER DEFAULT 0,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS games (
                    id          SERIAL PRIMARY KEY,
                    date        TEXT NOT NULL,
                    time        TEXT NOT NULL,
                    location    TEXT NOT NULL,
                    status      TEXT DEFAULT 'active',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS teams (
                    game_id     INTEGER NOT NULL REFERENCES games(id),
                    team_number INTEGER NOT NULL,
                    player_id   INTEGER NOT NULL REFERENCES players(id),
                    PRIMARY KEY (game_id, player_id)
                );

                CREATE TABLE IF NOT EXISTS matches (
                    id          SERIAL PRIMARY KEY,
                    game_id     INTEGER NOT NULL REFERENCES games(id),
                    team_a      INTEGER NOT NULL,
                    team_b      INTEGER NOT NULL,
                    result      TEXT DEFAULT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS goals (
                    id               SERIAL PRIMARY KEY,
                    match_id         INTEGER NOT NULL REFERENCES matches(id),
                    player_id        INTEGER NOT NULL REFERENCES players(id),
                    assist_player_id INTEGER DEFAULT NULL REFERENCES players(id),
                    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            db.commit()
        else:
            # SQLite
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
        row = _fetchone(_execute(db, _q("SELECT * FROM players WHERE telegram_id = ?"), (telegram_id,)))
        if row:
            _execute(db, _q("UPDATE players SET username=?, first_name=?, last_name=? WHERE telegram_id=?"),
                     (username, first_name, last_name, telegram_id))
            row = _fetchone(_execute(db, _q("SELECT * FROM players WHERE telegram_id = ?"), (telegram_id,)))
        else:
            _execute(db, _q("INSERT INTO players (telegram_id, username, first_name, last_name) VALUES (?,?,?,?)"),
                     (telegram_id, username, first_name, last_name))
            row = _fetchone(_execute(db, _q("SELECT * FROM players WHERE telegram_id = ?"), (telegram_id,)))
        return row


def get_player_by_id(player_id: int) -> dict | None:
    with get_db() as db:
        return _fetchone(_execute(db, _q("SELECT * FROM players WHERE id = ?"), (player_id,)))


def get_all_players() -> list[dict]:
    with get_db() as db:
        return _fetchall(_execute(db, "SELECT * FROM players ORDER BY rating DESC"))


def set_player_rating(player_id: int, rating: float):
    with get_db() as db:
        _execute(db, _q("UPDATE players SET rating = ? WHERE id = ?"), (rating, player_id))


def delete_player(player_id: int):
    with get_db() as db:
        _execute(db, _q("DELETE FROM goals WHERE player_id=?"), (player_id,))
        _execute(db, _q("UPDATE goals SET assist_player_id=NULL WHERE assist_player_id=?"), (player_id,))
        _execute(db, _q("DELETE FROM teams WHERE player_id=?"), (player_id,))
        _execute(db, _q("DELETE FROM players WHERE id=?"), (player_id,))


def set_admin(player_id: int, is_admin: bool):
    with get_db() as db:
        _execute(db, _q("UPDATE players SET is_admin = ? WHERE id = ?"), (int(is_admin), player_id))


def is_admin(player_id: int) -> bool:
    with get_db() as db:
        row = _fetchone(_execute(db, _q("SELECT is_admin FROM players WHERE id = ?"), (player_id,)))
        return bool(row["is_admin"]) if row else False


# --- Games ---

def create_game(date: str, time: str, location: str) -> int:
    with get_db() as db:
        if DATABASE_URL:
            cur = _execute(db, _q("INSERT INTO games (date, time, location) VALUES (?,?,?) RETURNING id"),
                           (date, time, location))
            return cur.fetchone()[0]
        else:
            cur = _execute(db, _q("INSERT INTO games (date, time, location) VALUES (?,?,?)"),
                           (date, time, location))
            return cur.lastrowid


def get_active_game() -> dict | None:
    with get_db() as db:
        return _fetchone(_execute(db, "SELECT * FROM games WHERE status='active' ORDER BY id DESC LIMIT 1"))


def get_all_games() -> list[dict]:
    with get_db() as db:
        return _fetchall(_execute(db, "SELECT * FROM games ORDER BY id DESC"))


def get_game_by_id(game_id: int) -> dict | None:
    with get_db() as db:
        return _fetchone(_execute(db, _q("SELECT * FROM games WHERE id = ?"), (game_id,)))


def close_game(game_id: int):
    with get_db() as db:
        _execute(db, _q("UPDATE games SET status='closed' WHERE id=?"), (game_id,))


def delete_game(game_id: int):
    with get_db() as db:
        _execute(db, _q("DELETE FROM goals WHERE match_id IN (SELECT id FROM matches WHERE game_id=?)"), (game_id,))
        _execute(db, _q("DELETE FROM matches WHERE game_id=?"), (game_id,))
        _execute(db, _q("DELETE FROM teams WHERE game_id=?"), (game_id,))
        _execute(db, _q("DELETE FROM games WHERE id=?"), (game_id,))


# --- Teams ---

def save_teams(game_id: int, teams_data: dict):
    """teams_data: {team_number: [player_id, ...]}"""
    with get_db() as db:
        _execute(db, _q("DELETE FROM teams WHERE game_id=?"), (game_id,))
        for team_number, player_ids in teams_data.items():
            for pid in player_ids:
                _execute(db, _q("INSERT INTO teams (game_id, team_number, player_id) VALUES (?,?,?)"),
                         (game_id, int(team_number), pid))


def get_teams(game_id: int) -> dict[int, list[dict]]:
    with get_db() as db:
        rows = _fetchall(_execute(db, _q(
            """SELECT p.*, t.team_number FROM players p
               JOIN teams t ON t.player_id = p.id
               WHERE t.game_id = ?
               ORDER BY t.team_number, p.rating DESC"""),
            (game_id,)))
        result: dict[int, list[dict]] = {}
        for d in rows:
            tn = d.pop("team_number")
            result.setdefault(tn, []).append(d)
        return result


def get_player_team(game_id: int, player_id: int) -> int | None:
    with get_db() as db:
        row = _fetchone(_execute(db, _q(
            "SELECT team_number FROM teams WHERE game_id=? AND player_id=?"),
            (game_id, player_id)))
        return row["team_number"] if row else None


# --- Matches ---

def create_match(game_id: int, team_a: int, team_b: int, result: str | None = None) -> int:
    with get_db() as db:
        if DATABASE_URL:
            cur = _execute(db, _q("INSERT INTO matches (game_id, team_a, team_b, result) VALUES (?,?,?,?) RETURNING id"),
                           (game_id, team_a, team_b, result))
            return cur.fetchone()[0]
        else:
            cur = _execute(db, _q("INSERT INTO matches (game_id, team_a, team_b, result) VALUES (?,?,?,?)"),
                           (game_id, team_a, team_b, result))
            return cur.lastrowid


def update_match(match_id: int, result: str | None):
    with get_db() as db:
        _execute(db, _q("UPDATE matches SET result=? WHERE id=?"), (result, match_id))


def delete_match(match_id: int):
    with get_db() as db:
        _execute(db, _q("DELETE FROM goals WHERE match_id=?"), (match_id,))
        _execute(db, _q("DELETE FROM matches WHERE id=?"), (match_id,))


def get_matches(game_id: int) -> list[dict]:
    with get_db() as db:
        return _fetchall(_execute(db, _q("SELECT * FROM matches WHERE game_id=? ORDER BY id"), (game_id,)))


def get_match_by_id(match_id: int) -> dict | None:
    with get_db() as db:
        return _fetchone(_execute(db, _q("SELECT * FROM matches WHERE id=?"), (match_id,)))


# --- Goals ---

def add_goal(match_id: int, player_id: int, assist_player_id: int | None = None) -> int:
    with get_db() as db:
        if DATABASE_URL:
            cur = _execute(db, _q("INSERT INTO goals (match_id, player_id, assist_player_id) VALUES (?,?,?) RETURNING id"),
                           (match_id, player_id, assist_player_id))
            return cur.fetchone()[0]
        else:
            cur = _execute(db, _q("INSERT INTO goals (match_id, player_id, assist_player_id) VALUES (?,?,?)"),
                           (match_id, player_id, assist_player_id))
            return cur.lastrowid


def delete_goal(goal_id: int):
    with get_db() as db:
        _execute(db, _q("DELETE FROM goals WHERE id=?"), (goal_id,))


def get_goals(match_id: int) -> list[dict]:
    with get_db() as db:
        return _fetchall(_execute(db, _q(
            """SELECT g.id, g.match_id, g.player_id, g.assist_player_id,
                      p.first_name as scorer_first, p.last_name as scorer_last,
                      a.first_name as assist_first, a.last_name as assist_last
               FROM goals g
               JOIN players p ON p.id = g.player_id
               LEFT JOIN players a ON a.id = g.assist_player_id
               WHERE g.match_id = ?
               ORDER BY g.id"""),
            (match_id,)))


def get_game_goals(game_id: int) -> list[dict]:
    with get_db() as db:
        return _fetchall(_execute(db, _q(
            """SELECT g.id, g.match_id, g.player_id, g.assist_player_id,
                      p.first_name as scorer_first, p.last_name as scorer_last,
                      a.first_name as assist_first, a.last_name as assist_last
               FROM goals g
               JOIN matches m ON m.id = g.match_id
               JOIN players p ON p.id = g.player_id
               LEFT JOIN players a ON a.id = g.assist_player_id
               WHERE m.game_id = ?
               ORDER BY g.id"""),
            (game_id,)))


# --- Stats ---

def get_player_stats() -> list[dict]:
    with get_db() as db:
        players = _fetchall(_execute(db, "SELECT * FROM players ORDER BY rating DESC"))

        for p in players:
            pid = p["id"]

            matches_rows = _fetchall(_execute(db, _q(
                """SELECT m.id, m.team_a, m.team_b, m.result, t.team_number
                   FROM matches m
                   JOIN teams t ON t.game_id = m.game_id AND t.player_id = ?
                   WHERE m.result IS NOT NULL
                     AND (t.team_number = m.team_a OR t.team_number = m.team_b)"""),
                (pid,)))

            wins = 0
            draws = 0
            losses = 0
            for mr in matches_rows:
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

            row = _fetchone(_execute(db, _q("SELECT COUNT(*) as cnt FROM goals WHERE player_id=?"), (pid,)))
            p["goals"] = row["cnt"] if row else 0

            row = _fetchone(_execute(db, _q("SELECT COUNT(*) as cnt FROM goals WHERE assist_player_id=?"), (pid,)))
            p["assists"] = row["cnt"] if row else 0

        return players
