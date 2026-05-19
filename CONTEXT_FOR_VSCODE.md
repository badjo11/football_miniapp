# Football Mini App — Контекст для разработки

## Репозиторий
https://github.com/badjo11/football_miniapp

## Стек
Python, FastAPI, SQLite, Telegram WebApp SDK, Railway
Frontend: один файл frontend/index.html на чистом ES5 (var, .then(), без стрелочных функций)

## Переменные окружения (Railway)
BOT_TOKEN, WEBAPP_URL = https://footballminiapp-production.up.railway.app

## Авторизация
Стандартный Telegram initData не работает через Railway. Используется подписанный URL:
- Бот генерирует URL: ?uid=&un=&fn=&ln=&ts=&sig=
- sig = HMAC-SHA256(BOT_TOKEN, "uid:ts")[:32]
- Frontend передаёт параметры как query params в каждый API-запрос
- Backend проверяет подпись и свежесть (24ч)
- Авто-админ: telegram_id 982854595 (badjo11)

## Текущая структура БД
- players: id, telegram_id, username, first_name, last_name, rating, is_admin
- games: id, date, time, location, status (open/closed)
- teams: game_id, team_number, player_id
- matches: id, game_id, team_a, team_b, result (team_a/team_b/draw/null)
- goals: id, match_id, player_id, assist_player_id

## Текущие API эндпоинты
GET /api/me, /api/players, /api/stats, /api/games, /api/game, /api/game/{id}, /api/teams/{id}, /api/goals/{id}
POST /api/game, /api/game/close, /api/teams/{id}, /api/match, /api/goal, /api/rating, /api/guest
PUT /api/match/{id}
DELETE /api/game/{id}, /api/match/{id}, /api/goal/{id}, /api/player/{id}

## Бот
Встроен в main.py, работает в отдельном потоке (asyncio.new_event_loop).
Использует низкоуровневый API: bot_app.initialize() → start() → updater.start_polling()
НЕ run_polling() — падает с "set_wakeup_fd only works in main thread".

## Проблема
Во время игр сложно записывать статистику — админ сам играет. Набирать текст неудобно, ошибки в именах.

## НОВАЯ ФИЧА: Бот с кнопками для записи матчей в группе

Бот добавляется в Telegram-группу. Любой участник (не только админ) может записывать через inline-кнопки.

### Флоу:

1. Кто угодно пишет /матч в группе
2. Бот показывает inline-кнопки с парами команд (берёт из teams текущей игры):
   [Команда 1 vs Команда 2]
   [Команда 1 vs Команда 3]
   [Команда 2 vs Команда 3]

3. Тапнули пару → бот показывает кнопки результата:
   [🏆 Команда 1]  [🤝 Ничья]  [🏆 Команда 2]

4. Тапнули результат → бот создаёт match в БД, показывает кнопки с игроками обеих команд:
   "Кто забил?"
   [Азамат] [Данияр] [Марат] [Канат]
   [Готово ✓]

5. Тапнули игрока (гол) → бот спрашивает ассист, показывает остальных игроков:
   "Ассист?"
   [Данияр] [Марат] [Канат] [Без ассиста]

6. Записано, снова показывает список игроков для следующего гола
   "Голы: Азамат (ас. Данияр). Ещё?"
   [Азамат] [Данияр] [Марат] [Канат]
   [Готово ✓]

7. Нажали Готово → матч завершён, summary в чат

### Технические требования:
- Использовать CallbackQueryHandler для inline-кнопок
- Состояние матча хранить в памяти (dict по chat_id) или в БД
- API-эндпоинты для голов/матчей УЖЕ ЕСТЬ — бот вызывает database.py напрямую (он в том же процессе)
- Любой участник группы может нажимать кнопки (не только админ)
- Бот должен работать в том же треде что сейчас (run_bot в main.py)
- Добавить новые хендлеры в _run() рядом с CommandHandler("start")

### Пример callback_data формат:
- "match:1:2" → создать матч команда 1 vs команда 2
- "result:{match_id}:team_a" → команда A победила
- "result:{match_id}:draw" → ничья
- "goal:{match_id}:{player_id}" → гол
- "assist:{match_id}:{goal_id}:{player_id}" → ассист
- "assist:{match_id}:{goal_id}:none" → без ассиста
- "done:{match_id}" → завершить запись голов

### SQLite сбрасывается при деплое!
Нужна миграция на PostgreSQL. Railway даёт бесплатный PostgreSQL.
