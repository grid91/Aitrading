import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from trading import TradingEngine, SYMBOLS, LEVERAGE
from ai_brain import AIBrain

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "10"))

trading = TradingEngine()
brain = AIBrain()

auto_trading_active = False
auto_task = None

# Persistent bottom keyboard — always visible
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["💰 Balance", "📊 Positions"],
        ["🤖 Auto ON", "🛑 Auto OFF"],
        ["📈 Analyze", "📋 Status"],
        ["❌ Close All"],
    ],
    resize_keyboard=True,

)

def get_inline_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("📊 Positions", callback_data="positions")],
        [InlineKeyboardButton("🤖 Auto ON", callback_data="auto_on"),
         InlineKeyboardButton("🛑 Auto OFF", callback_data="auto_off")],
        [InlineKeyboardButton("📈 Analyze", callback_data="analyze"),
         InlineKeyboardButton("📋 Status", callback_data="status")],
        [InlineKeyboardButton("❌ Close All", callback_data="close_all")],
    ])

def restricted(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
            await (update.message or update.callback_query.message).reply_text("⛔ Unauthorized.")
            return
        return await func(update, context)
    return wrapper

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *AI Futures Bot — OKX*\n"
        f"⚡ {LEVERAGE}x | 🛡 SL 2% | TP 4%\n"
        f"💵 ${TRADE_AMOUNT_USDT} → ${TRADE_AMOUNT_USDT * LEVERAGE} position\n\n"
        f"Use buttons below 👇",
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
            lines.append(f"• {asset}: `{amount:.4f}`")
        usdt = bal.get('USDT', 0)
        lines.append(f"\n⚡ Power: `${usdt * LEVERAGE:.2f}`")
        await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await msg.reply_text(f"❌ {e}", reply_markup=MAIN_KEYBOARD)

@restricted
async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        pos = trading.get_open_positions()
        if not pos:
            await msg.reply_text("📊 No open positions.", reply_markup=MAIN_KEYBOARD)
            return
        lines = ["📊 *Positions:*\n"]
        for p in pos:
            pnl_emoji = "🟢" if p['pnl'] >= 0 else "🔴"
            coin = p['symbol'].replace('-USDT-SWAP', '')
            lines.append(f"{pnl_emoji} *{coin}* {p['side']} | PnL: `${p['pnl']:.4f}`")
            if p['liq_price']:
                lines.append(f"   Liq: `${p['liq_price']:,.2f}`")
        await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await msg.reply_text(f"❌ {e}", reply_markup=MAIN_KEYBOARD)

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
                coin = inst_id.replace("-USDT-SWAP", "")
                emoji = "🟢" if decision['action'] == "BUY" else "🔴" if decision['action'] == "SELL" else "⏸"
                rsi = data['timeframes']['1h']['rsi']
                conf = decision.get('confidence', 0)
                lines.append(f"{emoji} *{coin}* {decision['action']} | RSI:{rsi} | {conf}%")
            except Exception as e:
                coin = inst_id.replace("-USDT-SWAP", "")
                lines.append(f"⚠️ {coin}: Error")
        await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await msg.reply_text(f"❌ {e}", reply_markup=MAIN_KEYBOARD)

@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    state = "🟢 ON" if auto_trading_active else "🔴 OFF"
    usdt = trading.get_usdt_balance()
    pos = trading.get_open_positions()
    await msg.reply_text(
        f"📋 *Status:*\n\n"
        f"Auto: {state}\n"
        f"Positions: {len(pos)}\n"
        f"USDT: `${usdt:.4f}`\n"
        f"Power: `${usdt * LEVERAGE:.2f}`\n"
        f"Leverage: {LEVERAGE}x",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD
    )

async def close_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        pos = trading.get_open_positions()
        if not pos:
            await msg.reply_text("📊 No positions to close.", reply_markup=MAIN_KEYBOARD)
            return
        for p in pos:
            trading.close_position(p['symbol'], p['side'], p['qty'])
        await msg.reply_text(f"✅ Closed {len(pos)} position(s).", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await msg.reply_text(f"❌ {e}", reply_markup=MAIN_KEYBOARD)

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
                    coin = inst_id.replace("-USDT-SWAP", "")

                    if inst_id in open_symbols and decision["action"] != "SELL":
                        continue

                    if decision["action"] in ["BUY", "SELL"]:
                        result = trading.place_order(inst_id, decision["action"], 0, data['price'])
                        await app.bot.send_message(chat_id, f"🔍 {coin} order result:
{str(result)[:500]}")
                        if result.get('code') == '0':
                            trades_made += 1
                            direction = "🟢 LONG" if decision["action"] == "BUY" else "🔴 SHORT"
                            await app.bot.send_message(
                                chat_id,
                                f"✅ *Trade!*\n"
                                f"{coin} {direction}\n"
                                f"@ ${data['price']:,.4f}\n"
                                f"SL: ${result.get('sl_price')} | TP: ${result.get('tp_price')}\n"
                                f"Conf: {decision.get('confidence')}%",
                                parse_mode="Markdown"
                            )
                        else:
                            await app.bot.send_message(chat_id, f"⚠️ {coin} failed: {result.get('msg', '?')}")
                except Exception as e:
                    logger.error(f"{inst_id}: {e}")
                await asyncio.sleep(2)

            await app.bot.send_message(chat_id, f"🔄 Scan done — {trades_made} trade(s) | Next in 15min")
        except Exception as e:
            await app.bot.send_message(chat_id, f"⚠️ {e}")
        await asyncio.sleep(900)

@restricted
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle persistent keyboard button taps"""
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
                f"🤖 *Auto ON!*\n⚡ {LEVERAGE}x | Scanning every 15min",
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
            await query.message.reply_text(
                f"🤖 *Auto ON!*\n⚡ {LEVERAGE}x | Scanning every 15min",
                parse_mode="Markdown", reply_markup=MAIN_KEYBOARD
            )
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
    logger.info("OKX Futures AI Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
