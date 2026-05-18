# Football Mini App — Полный контекст проекта

## Что это
Telegram Mini App для организации мини-футбола: запись на игры, рейтинги игроков, авто-разбивка по командам, гостевые игроки.

## Стек
- **Backend:** Python, FastAPI, SQLite
- **Frontend:** Single HTML file (ES5 JS, no build step), Telegram WebApp SDK
- **Hosting:** Railway (https://footballminiapp-production.up.railway.app)
- **Repo:** https://github.com/badjo11/football-miniapp

## Переменные окружения (Railway)
```
BOT_TOKEN = 8937301524:AAE9NJhUlf5n2oN8zhrd7Fg0jtNeQGvYmfs
WEBAPP_URL = https://footballminiapp-production.up.railway.app
```

## Структура файлов
```
football-miniapp/
├── main.py              # FastAPI сервер + встроенный Telegram бот
├── database.py          # SQLite: players, games, registrations, preferences, teams
├── distribute.py        # Алгоритм змейки + оптимизация пожеланий партнёров
├── auth.py              # Верификация Telegram initData (HMAC-SHA256)
├── bot.py               # НЕ ИСПОЛЬЗУЕТСЯ — бот встроен в main.py
├── frontend/
│   └── index.html       # SPA фронтенд (ES5, без фреймворков)
├── Procfile             # web: uvicorn main:app --host 0.0.0.0 --port ${PORT}
└── requirements.txt     # fastapi, uvicorn, python-telegram-bot
```

## Архитектура авторизации
Стандартный Telegram initData не работает через Railway/tunnels. Используется **подписанный URL**:
1. Бот генерирует URL с параметрами: `?uid=&un=&fn=&ln=&ts=&sig=`
2. `sig` = HMAC-SHA256(BOT_TOKEN, "uid:ts")[:32]
3. Frontend передаёт эти параметры как query params в каждый API-запрос
4. Backend проверяет подпись и свежесть (24 часа)
5. Также поддержан стандартный initData (заголовок X-Telegram-Init-Data) на случай если заработает

## База данных (SQLite)
### Таблицы:
- **players:** id, telegram_id (unique), username, first_name, last_name, rating (1.0-10.0), is_admin, created_at
- **games:** id, date, time, location, max_players, status ('open'/'closed'), created_at
- **registrations:** game_id, player_id (unique pair)
- **preferences:** player_id, partner_id (кто с кем хочет играть)
- **teams:** game_id, team_number, player_id

### Важно: Railway сбрасывает SQLite при каждом деплое. Нужна миграция на PostgreSQL для продакшена.

## Авто-админ
В `get_current_player()` (main.py) при авторизации через query params:
```python
if int(uid) in [982854595]:  # Telegram ID badjo11
    db.set_admin(player["id"], True)
    player["is_admin"] = 1
```

## API эндпоинты
| Метод | Путь | Описание | Доступ |
|-------|------|----------|--------|
| GET | /api/me | Профиль + активная игра | все |
| GET | /api/players | Все игроки | все |
| GET | /api/game | Активная игра + записавшиеся | все |
| GET | /api/teams | Текущие составы | все |
| POST | /api/register | Записаться | все |
| POST | /api/unregister | Отписаться | все |
| POST | /api/preference | Выбрать партнёра {partner_id} | все |
| DELETE | /api/preference | Убрать партнёра | все |
| POST | /api/game | Создать игру {date,time,location,max_players} | админ |
| POST | /api/game/close | Закрыть запись | админ |
| POST | /api/distribute | Авто-распределение | админ |
| POST | /api/rating | Изменить рейтинг {player_id, rating} | админ |
| POST | /api/swap | Поменять игроков {player1_id, player2_id} | админ |
| POST | /api/guest | Добавить гостя {name, rating} | админ |

## Алгоритм распределения (distribute.py)
- **Змейка:** сортировка по рейтингу desc, распределение 1→2→2→1→1→2...
- **Пожелания:** после змейки пытается свапнуть игроков с близким рейтингом (±1.5) чтобы выполнить preferences
- 2 команды при ≤15 игроков, 3 при ≤24, 4 при больше

## Frontend (index.html)
- **Написан на чистом ES5** (var, function, .then()) — без стрелочных функций, async/await, template literals. Это критично для совместимости с Telegram WebApp на телефонах.
- **5 экранов:** Игра, Состав, Команды, Рейтинг, Админ
- **Админ-панель:** создание игры, авто-распределение, слайдеры рейтингов, добавление гостей, закрытие записи
- Авторизация: берёт uid/sig из URL query params, передаёт в каждый fetch-запрос как query params
- Использует CSS-переменные Telegram для адаптации к теме пользователя (тёмная/светлая)
- **window.onerror и unhandledrejection** хендлеры для отладки — показывают ошибки красным экраном

## Telegram Bot (встроен в main.py)
- Запускается в отдельном потоке через `asyncio.new_event_loop()`
- Команда /start генерирует подписанный URL и отправляет кнопку WebApp
- `run_bot()` использует низкоуровневый API: `bot_app.initialize() → start() → updater.start_polling()`
- НЕ использует `run_polling()` напрямую (падает с "set_wakeup_fd only works in main thread")

## Гостевые игроки
- Админ добавляет через панель: имя + рейтинг
- Создаётся player с отрицательным telegram_id и last_name="(гость)"
- Автоматически записывается на текущую игру
- Участвует в распределении наравне со всеми

## Классы рейтинга
- S: 9.0–10.0 | A: 7.0–8.9 | B: 5.0–6.9 | C: <5.0

## Мини-футбол специфика
- Нет позиций (нападающий/защитник)
- Нет сильных сторон (скорость/удар)
- Только рейтинг и имя

## Известные проблемы / TODO
1. SQLite сбрасывается при деплое — нужен PostgreSQL
2. Стандартный Telegram initData приходит пустым через Railway — используем подписанный URL как workaround
3. Бот работает в daemon-треде — при падении не перезапускается
4. Нет истории игр / статистики побед
5. Нет уведомлений в группу при создании игры
