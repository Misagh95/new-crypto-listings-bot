"""
New Crypto Listings Monitor Bot
Tracks new exchange listings by monitoring CoinGecko and exchange announcement feeds.
Features: track new coins, exchange listing alerts, keyword filters, periodic checks.
"""
import os
import json
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATA_DIR = os.getenv("DATA_DIR", ".")
os.makedirs(DATA_DIR, exist_ok=True)

ADMIN_IDS = [x.strip() for x in os.getenv("ADMIN_CHAT_ID", "").split(",") if x.strip()]
DATA_FILE = os.path.join(DATA_DIR, "listings_tracked.json")
SENT_FILE = os.path.join(DATA_DIR, "listings_sent.json")

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "15"))
COINGECKO_API = os.getenv("COINGECKO_API", "https://api.coingecko.com/api/v3")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

tracked_chats: Dict[str, Dict[str, Any]] = {}
known_coins: Set[str] = set()
sent_listings: Set[str] = set()


def load_json(path: str, default: Any) -> Any:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load {path}: {e}")
            return default
    return default


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_state() -> None:
    global tracked_chats, known_coins, sent_listings
    tracked_chats = load_json(DATA_FILE, {})
    known_coins = set(load_json(os.path.join(DATA_DIR, "known_coins.json"), []))
    sent_listings = set(load_json(SENT_FILE, []))


def save_state() -> None:
    save_json(DATA_FILE, tracked_chats)
    save_json(os.path.join(DATA_DIR, "known_coins.json"), list(known_coins))
    save_json(SENT_FILE, list(sent_listings)[-3000:])


def is_admin(chat_id: Any) -> bool:
    if not ADMIN_IDS:
        return True
    return str(chat_id) in ADMIN_IDS


def to_chat_id(value: Any) -> Any:
    try:
        return int(value)
    except Exception:
        return value


coingecko_headers = {}
if COINGECKO_API_KEY:
    coingecko_headers["x-cg-demo-api-key"] = COINGECKO_API_KEY


async def fetch_coingecko(endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
    url = f"{COINGECKO_API}{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.get(url, params=params, headers=coingecko_headers)
            if r.status_code == 200:
                return r.json()
            logger.warning(f"CoinGecko error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.warning(f"CoinGecko request failed: {e}")
    return None


async def fetch_new_coins() -> List[Dict[str, Any]]:
    """Fetch recently added coins from CoinGecko."""
    data = await fetch_coingecko(
        "/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": "250",
            "page": "1",
            "sparkline": "false",
            "price_change_percentage": "24h",
        },
    )
    if not data:
        return []
    new_coins = []
    for coin in data:
        cid = coin.get("id")
        if cid and cid not in known_coins:
            new_coins.append(coin)
    return new_coins


async def fetch_recently_added() -> List[Dict[str, Any]]:
    """Alternative: use recently added endpoint if available."""
    # CoinGecko doesn't have a dedicated endpoint, so we simulate by date.
    data = await fetch_coingecko(
        "/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_asc",
            "per_page": "100",
            "page": "1",
        },
    )
    if not data:
        return []
    # Heuristic: coins with very low market cap could be newly added
    return [c for c in data if c.get("market_cap", 0) and c.get("id") not in known_coins]


# =============================
# Commands
# =============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    text = (
        "🆕 <b>New Crypto Listings Bot</b>\n\n"
        "Commands:\n"
        "/watch - Subscribe this chat to new listing alerts\n"
        "/unwatch - Unsubscribe this chat\n"
        "/keywords <a,b> - Filter listings by keywords\n"
        "/status - Show your settings\n"
        "/latest - Show recently detected listings"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    key = str(chat_id)
    tracked_chats.setdefault(key, {"keywords": []})
    save_state()
    await update.message.reply_text("✅ This chat will receive new listing alerts.")


async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    key = str(chat_id)
    if key in tracked_chats:
        del tracked_chats[key]
        save_state()
    await update.message.reply_text("✅ Unsubscribed from new listing alerts.")


async def cmd_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_admin(chat_id):
        return
    key = str(chat_id)
    tracked_chats.setdefault(key, {"keywords": []})
    if not context.args:
        kws = tracked_chats[key].get("keywords", [])
        text = f"🔑 Keywords: {', '.join(kws)}" if kws else "🔑 No keywords (all listings sent)."
        await update.message.reply_text(text)
        return
    raw = " ".join(context.args)
    if raw.lower() in ("clear", "none"):
        tracked_chats[key]["keywords"] = []
    else:
        tracked_chats[key]["keywords"] = [k.strip() for k in raw.split(",") if k.strip()]
    save_state()
    await update.message.reply_text(
        f"✅ Keywords updated: {', '.join(tracked_chats[key]['keywords'])}"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    key = str(update.effective_chat.id)
    cfg = tracked_chats.get(key, {})
    text = (
        f"📊 <b>Status</b>\n\n"
        f"Subscribed: <b>{'Yes' if key in tracked_chats else 'No'}</b>\n"
        f"Keywords: {', '.join(cfg.get('keywords', [])) or 'None'}\n"
        f"Tracked coins: {len(known_coins)}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    new_coins = await fetch_new_coins()
    if not new_coins:
        await update.message.reply_text("📭 No new listings detected recently.")
        return
    lines = ["🆕 <b>Recently Detected Listings:</b>\n"]
    for i, c in enumerate(new_coins[:10], 1):
        ch = c.get("price_change_percentage_24h") or 0
        emoji = "🟢" if ch >= 0 else "🔴"
        lines.append(
            f"{i}. <b>{c['name']}</b> ({c['symbol'].upper()})\n"
            f"   ${c.get('current_price', 0):,.6f} | {emoji} {ch:+.2f}% | Cap: ${c.get('market_cap', 0):,.0f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# =============================
# Background Monitoring
# =============================

async def send_listing_alert(app: Application, chat_id: Any, coin: Dict[str, Any]) -> None:
    key = str(chat_id)
    cfg = tracked_chats.get(key, {})
    kws = cfg.get("keywords", [])
    text_to_check = f"{coin.get('name', '')} {coin.get('symbol', '')}".lower()
    if kws and not any(k.lower() in text_to_check for k in kws):
        return
    ch = coin.get("price_change_percentage_24h") or 0
    emoji = "🟢" if ch >= 0 else "🔴"
    text = (
        f"🆕 <b>New Listing Detected!</b>\n\n"
        f"<b>{coin['name']} ({coin['symbol'].upper()})</b>\n"
        f"Price: <b>${coin.get('current_price', 0):,.6f}</b>\n"
        f"24h Change: {emoji} {ch:+.2f}%\n"
        f"Market Cap: ${coin.get('market_cap', 0):,.0f}\n"
        f"Volume: ${coin.get('total_volume', 0):,.0f}\n\n"
        f"CoinGecko: https://www.coingecko.com/en/coins/{coin['id']}"
    )
    try:
        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"Listing alert send failed {chat_id}: {e}")


async def listing_monitor(app: Application) -> None:
    # First run: populate known coins without sending alerts
    first_run = True
    while True:
        try:
            new_coins = await fetch_new_coins()
            if first_run:
                for coin in new_coins:
                    known_coins.add(coin["id"])
                save_state()
                first_run = False
                logger.info(f"Initial coin cache built: {len(known_coins)} coins")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            if new_coins:
                logger.info(f"New coins detected: {len(new_coins)}")
                for coin in new_coins:
                    coin_id = coin["id"]
                    if coin_id in known_coins or coin_id in sent_listings:
                        continue
                    sent_listings.add(coin_id)
                    for chat_key in list(tracked_chats.keys()):
                        chat_id = to_chat_id(chat_key)
                        await send_listing_alert(app, chat_id, coin)
                        await asyncio.sleep(0.3)
                    known_coins.add(coin_id)
                save_state()
        except Exception as e:
            logger.error(f"Listing monitor error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


async def post_init(application: Application) -> None:
    asyncio.create_task(listing_monitor(application))
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("watch", "Subscribe to listing alerts"),
        BotCommand("unwatch", "Unsubscribe from alerts"),
        BotCommand("keywords", "Set keyword filters"),
        BotCommand("status", "Show status"),
        BotCommand("latest", "Show recently detected listings"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("New listings bot initialized.")


def main() -> None:
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is missing!")
        return
    load_state()

    application = Application.builder().token(TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("watch", cmd_watch))
    application.add_handler(CommandHandler("unwatch", cmd_unwatch))
    application.add_handler(CommandHandler("keywords", cmd_keywords))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("latest", cmd_latest))

    application.run_polling()


if __name__ == "__main__":
    main()
