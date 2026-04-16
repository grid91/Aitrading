import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from trading import TradingEngine, SYMBOLS
from ai_brain import AIBrain

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "5"))

trading = TradingEngine()
brain = AIBrain()

auto_trading_active = False
auto_task = None

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["💰 Balance", "📊 Positions"],
        ["🤖 Auto ON", "🛑 Auto OFF"],
        ["📈 Analyze", "📋 Status"],
        ["❌ Close All"],
    ],
    resize_keyboard=True
)

def restricted(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
            await (update.message or update.callback_query.message).reply_text("Unauthorized.")
            return
        return await func(update, context)
    return wrapper

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *AI Spot Trading Bot — OKX*\n"
        "💵 Trade size: $" + str(TRADE_AMOUNT_USDT) + " per trade\n"
        "🛡 SL: 2% | TP: 4%\n"
        "⏱ Scans every 15 min\n\n"
        "Use buttons below 👇",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD
    )

@restricted
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        bal = trading.get_balance()
        if not bal:
            await msg.reply_text("💰 No balance found.", reply_markup=MAIN_KEYBOARD)
            return
        lines = ["💰 *Balance:*\n"]
        for asset, amount in bal.items():
            lines.append("• " + asset + ": `" + str(round(amount, 4)) + "`")
        await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await msg.reply_text("❌ " + str(e), reply_markup=MAIN_KEYBOARD)

@restricted
async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        pos = trading.get_open_positions()
        if not pos:
            await msg.reply_text("📊 No open positions.", reply_markup=MAIN_KEYBOARD)
            return
        lines = ["📊 *Holdings:*\n"]
        for p in pos:
            coin = p['symbol'].replace('-USDT', '')
            lines.append("• " + coin + ": " + str(round(p['qty'], 6)) + " (~$" + str(round(p['value_usdt'], 2)) + ")")
        await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await msg.reply_text("❌ " + str(e), reply_markup=MAIN_KEYBOARD)

@restricted
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    await msg.reply_text("🔍 Scanning...", reply_markup=MAIN_KEYBOARD)
    try:
        lines = ["📈 *Analysis:*\n"]
        for inst_id in SYMBOLS:
            try:
                data = trading.get_market_data(inst_id)
                decision = await brain.analyze(inst_id, data)
                coin = inst_id.replace("-USDT", "")
                emoji = "🟢" if decision['action'] == "BUY" else "🔴" if decision['action'] == "SELL" else "⏸"
                rsi = data['timeframes']['1h']['rsi']
                conf = decision.get('confidence', 0)
                lines.append(emoji + " *" + coin + "* " + decision['action'] + " | RSI:" + str(rsi) + " | " + str(conf) + "%")
            except Exception as e:
                coin = inst_id.replace("-USDT", "")
                lines.append("⚠️ " + coin + ": Error")
        await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await msg.reply_text("❌ " + str(e), reply_markup=MAIN_KEYBOARD)

@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    state = "🟢 ON" if auto_trading_active else "🔴 OFF"
    usdt = trading.get_usdt_balance()
    pos = trading.get_open_positions()
    await msg.reply_text(
        "📋 *Status:*\n\n"
        "Mode: Spot Trading\n"
        "Auto: " + state + "\n"
        "Holdings: " + str(len(pos)) + "\n"
        "USDT: `$" + str(round(usdt, 2)) + "`\n"
        "Trade size: $" + str(TRADE_AMOUNT_USDT),
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD
    )

@restricted
async def close_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        pos = trading.get_open_positions()
        if not pos:
            await msg.reply_text("📊 No positions to close.", reply_markup=MAIN_KEYBOARD)
            return
        closed = 0
        for p in pos:
            result = trading.place_order(p['symbol'], "SELL", p['qty'], p['entry_price'])
            if result.get('code') == '0':
                closed += 1
        await msg.reply_text("✅ Closed " + str(closed) + " position(s).", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await msg.reply_text("❌ " + str(e), reply_markup=MAIN_KEYBOARD)

async def auto_trade_loop(app: Application, chat_id: int):
    global auto_trading_active
    while auto_trading_active:
        try:
            open_positions = trading.get_open_positions()
            open_symbols = [p['symbol'] for p in open_positions]
            trades_made = 0

            for inst_id in SYMBOLS:
                if not auto_trading_active:
                    break
                try:
                    data = trading.get_market_data(inst_id)
                    decision = await brain.analyze(inst_id, data)
                    coin = inst_id.replace("-USDT", "")

                    # Skip if already holding this coin
                    if inst_id in open_symbols and decision['action'] == "BUY":
                        continue

                    if decision['action'] in ["BUY", "SELL"]:
                        # For SELL get current holding qty
                        qty = 0
                        if decision['action'] == "SELL":
                            for p in open_positions:
                                if p['symbol'] == inst_id:
                                    qty = p['qty']
                            if qty == 0:
                                continue

                        result = trading.place_order(inst_id, decision['action'], qty, data['price'])
                        if result.get('code') == '0':
                            trades_made += 1
                            action_emoji = "🟢 BUY" if decision['action'] == "BUY" else "🔴 SELL"
                            await app.bot.send_message(
                                chat_id,
                                "✅ *Trade Done!*\n"
                                + coin + " " + action_emoji + "\n"
                                "@ $" + str(round(data['price'], 4)) + "\n"
                                "Conf: " + str(decision.get('confidence')) + "%\n"
                                "_" + decision['reason'] + "_",
                                parse_mode="Markdown"
                            )
                        else:
                            err = result.get('data', [{}])
                            err_msg = err[0].get('sMsg', result.get('msg', '?')) if err else '?'
                            await app.bot.send_message(chat_id, "⚠️ " + coin + " failed: " + err_msg)
                except Exception as e:
                    logger.error(str(inst_id) + ": " + str(e))
                await asyncio.sleep(2)

            await app.bot.send_message(chat_id, "🔄 Scan done — " + str(trades_made) + " trade(s) | Next in 15min")
        except Exception as e:
            await app.bot.send_message(chat_id, "⚠️ " + str(e))
        await asyncio.sleep(900)

@restricted
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global auto_trading_active, auto_task
    text = update.message.text
    chat_id = update.message.chat_id

    if text == "💰 Balance":
        await balance(update, context)
    elif text == "📊 Positions":
        await positions(update, context)
    elif text == "📈 Analyze":
        await analyze(update, context)
    elif text == "📋 Status":
        await status(update, context)
    elif text == "❌ Close All":
        await close_all(update, context)
    elif text == "🤖 Auto ON":
        if not auto_trading_active:
            auto_trading_active = True
            auto_task = asyncio.create_task(auto_trade_loop(context.application, chat_id))
            await update.message.reply_text(
                "🤖 *Auto ON!*\nSpot trading every 15min",
                parse_mode="Markdown", reply_markup=MAIN_KEYBOARD
            )
        else:
            await update.message.reply_text("⚠️ Already running!", reply_markup=MAIN_KEYBOARD)
    elif text == "🛑 Auto OFF":
        auto_trading_active = False
        if auto_task:
            auto_task.cancel()
        await update.message.reply_text("🛑 Auto trading stopped.", reply_markup=MAIN_KEYBOARD)

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
    elif query.data == "close_all":
        await close_all(update, context)
    elif query.data == "auto_on":
        if not auto_trading_active:
            auto_trading_active = True
            auto_task = asyncio.create_task(auto_trade_loop(context.application, chat_id))
            await query.message.reply_text("🤖 *Auto ON!*\nSpot trading every 15min", parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
        else:
            await query.message.reply_text("⚠️ Already running!", reply_markup=MAIN_KEYBOARD)
    elif query.data == "auto_off":
        auto_trading_active = False
        if auto_task:
            auto_task.cancel()
        await query.message.reply_text("🛑 Auto trading stopped.", reply_markup=MAIN_KEYBOARD)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("OKX Spot AI Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
