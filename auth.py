"""
Верификация Telegram initData через HMAC-SHA256.

Telegram подписывает данные пользователя токеном бота.
Мы проверяем подпись, чтобы убедиться, что данные настоящие.

Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs

# Время жизни initData (секунд). После этого считаем данные устаревшими.
MAX_AGE_SECONDS = 86400  # 24 часа


def verify_init_data(init_data_raw: str, bot_token: str) -> dict | None:
    """
    Проверяет подлинность Telegram initData.

    Возвращает dict с данными пользователя при успехе, None при провале.
    """
    try:
        parsed = parse_qs(init_data_raw, keep_blank_values=True)

        # Достаём hash из данных
        received_hash = parsed.get("hash", [None])[0]
        if not received_hash:
            return None

        # Проверяем auth_date (не слишком старый)
        auth_date_str = parsed.get("auth_date", [None])[0]
        if not auth_date_str:
            return None

        auth_date = int(auth_date_str)
        if time.time() - auth_date > MAX_AGE_SECONDS:
            return None

        # Формируем data_check_string:
        # сортируем все пары key=value (кроме hash) по алфавиту
        check_pairs = []
        for key, values in parsed.items():
            if key == "hash":
                continue
            check_pairs.append(f"{key}={values[0]}")
        check_pairs.sort()
        data_check_string = "\n".join(check_pairs)

        # Считаем HMAC-SHA256
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        # Парсим user
        user_raw = parsed.get("user", [None])[0]
        if not user_raw:
            return None

        user = json.loads(user_raw)
        return {
            "telegram_id": user["id"],
            "first_name": user.get("first_name", ""),
            "last_name": user.get("last_name", ""),
            "username": user.get("username", ""),
            "auth_date": auth_date,
        }

    except (ValueError, KeyError, json.JSONDecodeError):
        return None
