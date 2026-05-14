# ⚽ Football Mini App

Telegram Mini App для организации мини-футбола: запись, рейтинги, авто-разбивка по командам.

Открывается прямо в Telegram — авторизация автоматическая, без логина и пароля.

---

## Как это работает

```
Игрок нажимает кнопку в боте
        ↓
Telegram открывает сайт внутри себя
        ↓
Telegram передаёт initData (id, имя, username)
        ↓
Сервер проверяет подпись HMAC-SHA256
        ↓
Игрок авторизован — видит приложение
```

---

## Структура проекта

```
├── main.py          ← FastAPI сервер (API + раздаёт фронтенд)
├── bot.py           ← Telegram-бот (кнопка для открытия Mini App)
├── auth.py          ← Верификация Telegram initData
├── database.py      ← SQLite: игроки, игры, составы
├── distribute.py    ← Алгоритм разбивки по командам
├── frontend/
│   └── index.html   ← Фронтенд (SPA)
├── requirements.txt
└── README.md
```

---

## Быстрый старт

### 1. Создать бота у @BotFather

Написать `/newbot`, получить токен.

### 2. Установить зависимости

```bash
pip install -r requirements.txt
```

### 3. Локальная разработка (без Telegram)

```bash
# Без BOT_TOKEN — сервер работает в dev-режиме (без проверки авторизации)
uvicorn main:app --reload --port 8000
```

Открыть http://localhost:8000 — приложение работает с тестовым пользователем.

### 4. Деплой на Railway

1. Залить код на GitHub
2. На [railway.app](https://railway.app): New Project → Deploy from GitHub
3. Переменные окружения:
   - `BOT_TOKEN` = токен бота
   - `WEBAPP_URL` = https://your-app.railway.app
4. Start command:
   ```
   uvicorn main:app --host 0.0.0.0 --port $PORT
   ```

### 5. Запустить бота

```bash
BOT_TOKEN=... WEBAPP_URL=https://your-app.railway.app python bot.py
```

### 6. Сделать себя админом

```bash
# В Python-консоли или отдельном скрипте:
python -c "
import database as db
db.init_db()
db.set_admin(1, True)  # player id = 1 (первый зарегистрированный)
"
```

Или через SQLite напрямую:
```sql
UPDATE players SET is_admin = 1 WHERE telegram_id = ВАШ_TELEGRAM_ID;
```

---

## Экраны приложения

### Игрок видит:
- **Игра** — активная игра, запись/отписка, выбор партнёра
- **Состав** — список записавшихся по классам рейтинга
- **Команды** — распределённые составы
- **Рейтинг** — все игроки и их рейтинги

### Администратор дополнительно видит:
- **Админ** — создание игры, авто-распределение, изменение рейтингов, закрытие записи

---

## API эндпоинты

Все запросы требуют заголовок `X-Telegram-Init-Data`.

| Метод | Путь | Описание | Доступ |
|---|---|---|---|
| GET | `/api/me` | Профиль текущего игрока | все |
| GET | `/api/game` | Активная игра + записавшиеся | все |
| GET | `/api/players` | Все игроки | все |
| GET | `/api/teams` | Текущие составы | все |
| POST | `/api/register` | Записаться | все |
| POST | `/api/unregister` | Отписаться | все |
| POST | `/api/preference` | Выбрать партнёра | все |
| DELETE | `/api/preference` | Убрать партнёра | все |
| POST | `/api/game` | Создать игру | админ |
| POST | `/api/game/close` | Закрыть запись | админ |
| POST | `/api/distribute` | Авто-распределение | админ |
| POST | `/api/rating` | Изменить рейтинг | админ |
| POST | `/api/swap` | Поменять игроков | админ |

---

## Деплой на VPS

```bash
# Установить
pip install -r requirements.txt

# Systemd сервис для API
cat > /etc/systemd/system/football-api.service << EOF
[Unit]
Description=Football Mini App API
After=network.target

[Service]
WorkingDirectory=/home/user/miniapp
ExecStart=/usr/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Environment=BOT_TOKEN=ВАШ_ТОКЕН
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Systemd сервис для бота
cat > /etc/systemd/system/football-bot.service << EOF
[Unit]
Description=Football Telegram Bot
After=network.target

[Service]
WorkingDirectory=/home/user/miniapp
ExecStart=/usr/bin/python3 bot.py
Environment=BOT_TOKEN=ВАШ_ТОКЕН
Environment=WEBAPP_URL=https://your-domain.com
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl enable football-api football-bot
systemctl start football-api football-bot
```

HTTPS обязателен (Telegram требует). Используй Nginx + Let's Encrypt:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```
