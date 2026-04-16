import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from trading import TradingEngine
from ai_brain import AIBrain

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))

trading = TradingEngine()
brain = AIBrain()

auto_trading_active = False
auto_task = None

def restricted(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
            await update.message.reply_text("⛔ Unauthorized.")
            return
        return await func(update, context)
    return wrapper

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("📊 Positions", callback_data="positions")],
        [InlineKeyboardButton("🤖 Auto ON", callback_data="auto_on"),
         InlineKeyboardButton("🛑 Auto OFF", callback_data="auto_off")],
        [InlineKeyboardButton("📈 Analyze Market", callback_data="analyze"),
         InlineKeyboardButton("📋 Status", callback_data="status")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 *AI Trading Bot Active!*\n\n"
        "I will analyze the market every 15 minutes and trade automatically.\n\n"
        "Use the buttons below to control me:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

@restricted
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        bal = trading.get_balance()
        text = "💰 *Your Binance Balance:*\n\n"
        for asset, amount in bal.items():
            if float(amount) > 0:
                text += f"• {asset}: `{float(amount):.4f}`\n"
        await msg.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Error fetching balance: {e}")

@restricted
async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        pos = trading.get_open_positions()
        if not pos:
            await msg.reply_text("📊 No open positions currently.")
        else:
            text = "📊 *Open Positions:*\n\n"
            for p in pos:
                text += f"• {p['symbol']}: {p['side']} {p['qty']} @ ${p['entry_price']}\n"
            await msg.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Error: {e}")

@restricted
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    await msg.reply_text("🔍 Analyzing market... please wait.")
    try:
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
        results = []
        for symbol in symbols:
            data = trading.get_market_data(symbol)
            decision = await brain.analyze(symbol, data)
            results.append(f"*{symbol}*: {decision['action']} — {decision['reason']}")
        text = "📈 *AI Market Analysis:*\n\n" + "\n\n".join(results)
        await msg.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Analysis error: {e}")

@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    state = "🟢 RUNNING" if auto_trading_active else "🔴 STOPPED"
    await msg.reply_text(
        f"📋 *Bot Status:*\n\n"
        f"Auto Trading: {state}\n"
        f"Checking every: 15 minutes\n"
        f"Pairs: BTC, ETH, BNB",
        parse_mode="Markdown"
    )

async def auto_trade_loop(app: Application, chat_id: int):
    global auto_trading_active
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    while auto_trading_active:
        try:
            await app.bot.send_message(chat_id, "🔄 Running auto analysis...")
            for symbol in symbols:
                data = trading.get_market_data(symbol)
                decision = await brain.analyze(symbol, data)
                if decision["action"] in ["BUY", "SELL"]:
                    result = trading.place_order(symbol, decision["action"], decision["qty"])
                    await app.bot.send_message(
                        chat_id,
                        f"✅ *Trade Executed!*\n"
                        f"Pair: {symbol}\n"
                        f"Action: {decision['action']}\n"
                        f"Qty: {decision['qty']}\n"
                        f"Reason: {decision['reason']}\n"
                        f"Order ID: {result.get('orderId', 'N/A')}",
                        parse_mode="Markdown"
                    )
                else:
                    await app.bot.send_message(chat_id, f"⏸ {symbol}: HOLD — {decision['reason']}")
        except Exception as e:
            await app.bot.send_message(chat_id, f"⚠️ Auto trade error: {e}")
        await asyncio.sleep(900)  # 15 minutes

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_trading_active, auto_task
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "balance":
        await balance(update, context)
    elif query.data == "positions":
        await positions(update, context)
    elif query.data == "analyze":
        await analyze(update, context)
    elif query.data == "status":
        await status(update, context)
    elif query.data == "auto_on":
        if not auto_trading_active:
            auto_trading_active = True
            auto_task = asyncio.create_task(auto_trade_loop(context.application, chat_id))
            await query.message.reply_text("🤖 *Auto trading ENABLED!*\nI'll analyze every 15 min and trade automatically.", parse_mode="Markdown")
        else:
            await query.message.reply_text("⚠️ Auto trading is already running!")
    elif query.data == "auto_off":
        auto_trading_active = False
        if auto_task:
            auto_task.cancel()
        await query.message.reply_text("🛑 *Auto trading STOPPED.*", parse_mode="Markdown")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
