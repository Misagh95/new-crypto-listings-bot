# New Crypto Listings Bot

A Telegram bot that detects newly listed cryptocurrencies on CoinGecko and sends alerts.

## Features

- `/watch` — Subscribe this chat to new listing alerts
- `/unwatch` — Unsubscribe
- `/keywords <a,b>` — Filter listings by keywords
- `/status` — Show settings
- `/latest` — Show recently detected listings

## Environment Variables

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
ADMIN_CHAT_ID=123456789
DATA_DIR=.
CHECK_INTERVAL=300
HTTP_TIMEOUT=15
COINGECKO_API_KEY=your_key  # Optional, increases rate limits
COINGECKO_API=https://api.coingecko.com/api/v3
```

## Install & Run

```bash
pip install -r requirements.txt
python bot.py
```

## Deploy

This project includes a `Dockerfile` and `render.yaml` for quick deployment on Render.com or any Docker-compatible host.

See the root `DEPLOY.md` for detailed instructions.
