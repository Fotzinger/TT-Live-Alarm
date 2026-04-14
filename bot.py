import asyncio
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent
from TikTokLive.client.errors import UserOfflineError

load_dotenv()

TOKEN = "8757795761:AAGf-IHOka-5HfXz83ivYDkkCOqMDDssN-A"
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

USERS_FILE = Path("users.json")

monitor_tasks = {}

# Status pro User
live_announced = {}
offline_since = {}

# Einstellungen
CHECK_DELAY_OFFLINE = 90
CHECK_DELAY_ERROR = 120
OFFLINE_RESET_SECONDS = 5 * 60  # 5 Minuten


def load_users():
    if not USERS_FILE.exists():
        return []
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return sorted(set(str(x).strip().lower() for x in data if str(x).strip()))


def save_users(users):
    cleaned = sorted(set(u.strip().lower() for u in users if u.strip()))
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)


def send(msg):
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg},
        timeout=20
    )
    response.raise_for_status()


def profile_link(username):
    return f"https://www.tiktok.com/@{username}"


def should_send_live_notification(username):
    return not live_announced.get(username, False)


def mark_live(username):
    live_announced[username] = True
    offline_since[username] = None


def mark_offline_observation(username):
    now = time.time()

    if live_announced.get(username, False):
        if offline_since.get(username) is None:
            offline_since[username] = now
        elif now - offline_since[username] >= OFFLINE_RESET_SECONDS:
            live_announced[username] = False
            offline_since[username] = None
            print(f"[SESSION ZURUECKGESETZT] @{username}")
    else:
        offline_since[username] = None


def create_client(username):
    client = TikTokLiveClient(unique_id=f"@{username}")

    if username not in live_announced:
        live_announced[username] = False
    if username not in offline_since:
        offline_since[username] = None

    @client.on(ConnectEvent)
    async def on_connect(event):
        # Sobald der User wieder live erreichbar ist, Offline-Timer zurücksetzen
        offline_since[username] = None

        if should_send_live_notification(username):
            send(
                f"🟢 @{username} ist LIVE!\n"
                f"{profile_link(username)}"
            )
            mark_live(username)
            print(f"[LIVE GEMELDET] @{username}")
        else:
            print(f"[IGNORIERT] @{username} - gleiche Live-Session")

    return client


async def monitor(username):
    while True:
        try:
            client = create_client(username)
            await client.start()

            # Falls start() normal endet, vorsichtig als Offline-Beobachtung zählen
            mark_offline_observation(username)
            await asyncio.sleep(CHECK_DELAY_OFFLINE)

        except UserOfflineError:
            mark_offline_observation(username)
            await asyncio.sleep(CHECK_DELAY_OFFLINE)

        except Exception as e:
            print(f"[FEHLER] @{username}: {e}")
            await asyncio.sleep(CHECK_DELAY_ERROR)


async def ensure_monitor_running(username):
    username = username.strip().lower()
    if not username:
        return

    existing = monitor_tasks.get(username)
    if existing and not existing.done():
        return

    monitor_tasks[username] = asyncio.create_task(monitor(username))


async def stop_monitor(username):
    username = username.strip().lower()
    task = monitor_tasks.pop(username, None)
    if task:
        task.cancel()

    live_announced.pop(username, None)
    offline_since.pop(username, None)


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Nutze: /add username")
        return

    username = context.args[0].replace("@", "").strip().lower()
    users = load_users()

    if username in users:
        await update.message.reply_text("Schon drin.")
        return

    users.append(username)
    save_users(users)
    await ensure_monitor_running(username)

    await update.message.reply_text(f"✅ {username} hinzugefügt")


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Nutze: /remove username")
        return

    username = context.args[0].replace("@", "").strip().lower()
    users = load_users()

    if username in users:
        users.remove(username)
        save_users(users)

    await stop_monitor(username)
    await update.message.reply_text(f"❌ {username} entfernt")


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    if users:
        await update.message.reply_text("\n".join(users))
    else:
        await update.message.reply_text("Keine User")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hallo 👋\n\n"
        "Befehle:\n"
        "/add username\n"
        "/remove username\n"
        "/list"
    )


async def on_startup(app: Application):
    users = load_users()
    print(f"[GELADENE USER] {users}")
    for username in users:
        await ensure_monitor_running(username)


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", list_users))

    app.post_init = on_startup

    print("Bot läuft...")
    app.run_polling()


if __name__ == "__main__":
    main()
