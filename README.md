# 🤖 AI Crypto Trading Bot (Telegram + Binance + Claude AI)

Fully automatic crypto trading bot controlled via Telegram, powered by Claude AI.

## Features
- 🧠 AI-powered trade decisions (Claude Sonnet)
- 📱 Full Telegram control from your phone
- 📊 Real-time Binance market data
- 🔄 Auto trades every 15 minutes
- 💰 Balance & position tracking
- 🛡️ Built-in risk management

## Setup on Railway

### Environment Variables (add these in Railway)

| Variable | Value |
|---|---|
| `TELEGRAM_TOKEN` | Your token from @BotFather |
| `BINANCE_API_KEY` | Your Binance API key |
| `BINANCE_SECRET` | Your Binance secret key |
| `ANTHROPIC_API_KEY` | Your Claude API key |
| `ALLOWED_USER_ID` | Your Telegram user ID (get from @userinfobot) |
| `TRADE_AMOUNT_USDT` | Amount per trade in USDT (e.g. 10) |

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Start bot & show control panel |
| `/balance` | Show Binance balance |
| `/positions` | Show open positions |
| `/analyze` | Run AI market analysis |
| `/status` | Show bot status |

## ⚠️ Disclaimer
This bot trades real money. Use at your own risk. Start with small amounts.
