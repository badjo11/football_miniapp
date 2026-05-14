import os
import hashlib
import hmac
import time
from urllib.parse import urlencode
from telegram import Update, WebAppInfo, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-app.railway.app")


def make_signed_url(user):
    ts = str(int(time.time()))
    data = f"{user.id}:{ts}"
    sig = hmac.new(BOT_TOKEN.encode(), data.encode(), hashlib.sha256).hexdigest()[:32]
    params = urlencode({
        "uid": user.id,
        "un": user.username or "",
        "fn": user.first_name or "",
        "ln": user.last_name or "",
        "ts": ts,
        "sig": sig,
    })
    return f"{WEBAPP_URL}?{params}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    url = make_signed_url(user)
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(
            text="⚽ Открыть Football App",
            web_app=WebAppInfo(url=url),
        )]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        "👋 Привет! Нажми кнопку ниже ⚽",
        reply_markup=keyboard,
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Установите BOT_TOKEN")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print(f"🤖 Бот запущен. Mini App URL: {WEBAPP_URL}")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()