"""
Team distribution using snake draft + preference optimization.

Snake draft (рейтинги убывают по змейке):
  Если 2 команды и 6 игроков с рейтингами [9,8,7,6,5,4]:
  Команда 1: 9, 6, 5  → сумма 20
  Команда 2: 8, 7, 4  → сумма 19
"""

import copy


def distribute(players: list[dict], num_teams: int = 2) -> list[list[dict]]:
    """
    Распределяет игроков по командам.
    Возвращает список команд, каждая — список игроков.
    """
    if not players:
        return [[] for _ in range(num_teams)]

    sorted_players = sorted(players, key=lambda p: p["rating"], reverse=True)
    teams: list[list[dict]] = [[] for _ in range(num_teams)]

    # Змейка
    direction = 1
    idx = 0
    for player in sorted_players:
        teams[idx].append(player)
        idx += direction
        if idx == num_teams:
            direction = -1
            idx = num_teams - 1
        elif idx == -1:
            direction = 1
            idx = 0

    return teams


def optimize_preferences(
    teams: list[list[dict]],
    preferences: dict[int, int],
) -> tuple[list[list[dict]], list[str]]:
    """
    Пытается выполнить пожелания партнёров через свапы игроков одного рейтинга.
    Возвращает (обновлённые команды, список результатов пожеланий).
    """
    teams = copy.deepcopy(teams)
    logs: list[str] = []

    for player_id, partner_id in preferences.items():
        player_team_idx = _find_team(teams, player_id)
        partner_team_idx = _find_team(teams, partner_id)

        if player_team_idx is None or partner_team_idx is None:
            continue  # кто-то не записан на эту игру

        if player_team_idx == partner_team_idx:
            logs.append(f"✅ Пожелание выполнено: {player_id} уже с {partner_id}")
            continue

        # Ищем кандидата для свапа в команде партнёра
        player = _get_player(teams[player_team_idx], player_id)
        swapped = _try_swap(teams, player, player_team_idx, partner_team_idx)

        if swapped:
            logs.append(f"✅ Пожелание выполнено: {player_id} переведён к {partner_id}")
        else:
            logs.append(f"⚠️ Не удалось выполнить: нет подходящего свапа для {player_id}")

    return teams, logs


def _find_team(teams: list[list[dict]], player_id: int) -> int | None:
    for i, team in enumerate(teams):
        if any(p["id"] == player_id for p in team):
            return i
    return None


def _get_player(team: list[dict], player_id: int) -> dict | None:
    for p in team:
        if p["id"] == player_id:
            return p
    return None


def _try_swap(
    teams: list[list[dict]],
    player: dict,
    from_team: int,
    to_team: int,
    rating_tolerance: float = 1.5,
) -> bool:
    """
    Ищет игрока в to_team с близким рейтингом и меняет местами.
    """
    for candidate in teams[to_team]:
        if abs(candidate["rating"] - player["rating"]) <= rating_tolerance:
            # Свап
            teams[from_team].remove(player)
            teams[to_team].remove(candidate)
            teams[from_team].append(candidate)
            teams[to_team].append(player)
            return True
    return False


def team_summary(teams: list[list[dict]]) -> list[dict]:
    """Возвращает краткую статистику по каждой команде."""
    result = []
    for i, team in enumerate(teams, start=1):
        total = sum(p["rating"] for p in team)
        avg = total / len(team) if team else 0
        result.append({
            "number": i,
            "players": team,
            "total_rating": round(total, 1),
            "avg_rating": round(avg, 1),
        })
    return result
