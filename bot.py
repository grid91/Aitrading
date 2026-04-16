import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
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
    keyboard = [
        [InlineKeyboardButton("💰 Balance", callback_data="balance"),
         InlineKeyboardButton("📊 Positions", callback_data="positions")],
        [InlineKeyboardButton("🤖 Auto ON", callback_data="auto_on"),
         InlineKeyboardButton("🛑 Auto OFF", callback_data="auto_off")],
        [InlineKeyboardButton("📈 Analyze Market", callback_data="analyze"),
         InlineKeyboardButton("📋 Status", callback_data="status")],
        [InlineKeyboardButton("❌ Close All Positions", callback_data="close_all")],
    ]
    coins = " • ".join([s.replace("-USDT-SWAP", "") for s in SYMBOLS])
    await update.message.reply_text(
        f"🤖 *AI Futures Trading Bot — OKX*\n\n"
        f"📊 Coins: {coins}\n"
        f"⚡ Leverage: {LEVERAGE}x (Cross margin)\n"
        f"💵 Trade size: ${TRADE_AMOUNT_USDT} → controls ${TRADE_AMOUNT_USDT * LEVERAGE}\n"
        f"⏱ Timeframes: 15m + 1H + 4H\n"
        f"📰 News: Enabled\n"
        f"🛡 Stop Loss: 2% | Take Profit: 4%\n\n"
        f"Use the buttons below:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@restricted
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        bal = trading.get_balance()
        if not bal:
            await msg.reply_text("💰 No balance found.")
            return
        text = "💰 *Your OKX Futures Balance:*\n\n"
        for asset, amount in bal.items():
            text += f"• {asset}: `{amount:.4f}`\n"
        usdt = bal.get('USDT', 0)
        text += f"\n⚡ With {LEVERAGE}x leverage you control: `${usdt * LEVERAGE:.2f}`"
        await msg.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Error: {e}")

@restricted
async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        pos = trading.get_open_positions()
        if not pos:
            await msg.reply_text("📊 No open futures positions.")
        else:
            text = "📊 *Open Futures Positions:*\n\n"
            for p in pos:
                pnl_emoji = "🟢" if p['pnl'] >= 0 else "🔴"
                text += (
                    f"• {p['symbol'].replace('-USDT-SWAP', '')}: {p['side']}\n"
                    f"  Entry: ${p['entry_price']:,.4f} | Qty: {p['qty']}\n"
                    f"  {pnl_emoji} PnL: ${p['pnl']:.4f}"
                )
                if p['liq_price']:
                    text += f" | Liq: ${p['liq_price']:,.2f}"
                text += "\n\n"
            await msg.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Error: {e}")

@restricted
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    await msg.reply_text("🔍 Analyzing 10 coins across 3 timeframes + news... ~30s")
    try:
        results = []
        for inst_id in SYMBOLS:
            try:
                data = trading.get_market_data(inst_id)
                decision = await brain.analyze(inst_id, data)
                emoji = "🟢" if decision['action'] == "BUY" else "🔴" if decision['action'] == "SELL" else "⏸"
                coin = inst_id.replace("-USDT-SWAP", "")
                results.append(
                    f"{emoji} *{coin}* — {decision['action']}\n"
                    f"Price: ${data['price']:,.4f} | RSI 1H: {data['timeframes']['1h']['rsi']}\n"
                    f"Confidence: {decision.get('confidence', 0)}% | News: {decision.get('news_sentiment', 'N/A')}\n"
                    f"_{decision['reason']}_"
                )
            except Exception as e:
                results.append(f"⚠️ {inst_id.replace('-USDT-SWAP','')}: Error — {e}")

        half = len(results) // 2
        await msg.reply_text("📈 *AI Futures Analysis — Part 1:*\n\n" + "\n\n".join(results[:half]), parse_mode="Markdown")
        await msg.reply_text("📈 *AI Futures Analysis — Part 2:*\n\n" + "\n\n".join(results[half:]), parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Analysis error: {e}")

@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    state = "🟢 RUNNING" if auto_trading_active else "🔴 STOPPED"
    usdt = trading.get_usdt_balance()
    pos = trading.get_open_positions()
    await msg.reply_text(
        f"📋 *Bot Status:*\n\n"
        f"Exchange: OKX Futures\n"
        f"Leverage: {LEVERAGE}x Cross\n"
        f"Auto Trading: {state}\n"
        f"Open Positions: {len(pos)}\n"
        f"Interval: Every 15 minutes\n"
        f"Coins: {len(SYMBOLS)} pairs\n"
        f"Stop Loss: 2% | Take Profit: 4%\n"
        f"USDT Balance: ${usdt:.4f}\n"
        f"Buying Power: ${usdt * LEVERAGE:.2f}",
        parse_mode="Markdown"
    )

async def close_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.callback_query.message
    try:
        pos = trading.get_open_positions()
        if not pos:
            await msg.reply_text("📊 No open positions to close.")
            return
        await msg.reply_text(f"⚠️ Closing {len(pos)} position(s)...")
        for p in pos:
            trading.close_position(p['symbol'], p['side'], p['qty'])
        await msg.reply_text("✅ All positions closed!")
    except Exception as e:
        await msg.reply_text(f"❌ Error closing positions: {e}")

async def auto_trade_loop(app: Application, chat_id: int):
    global auto_trading_active
    while auto_trading_active:
        try:
            await app.bot.send_message(chat_id, "🔄 *Auto scan — 10 futures pairs...*", parse_mode="Markdown")
            trades_made = 0

            # Check existing positions first
            open_positions = trading.get_open_positions()
            open_symbols = [p['symbol'] for p in open_positions]

            for inst_id in SYMBOLS:
                if not auto_trading_active:
                    break
                try:
                    data = trading.get_market_data(inst_id)
                    decision = await brain.analyze(inst_id, data)
                    coin = inst_id.replace("-USDT-SWAP", "")

                    # Skip if already in position for this coin
                    if inst_id in open_symbols and decision["action"] != "SELL":
                        logger.info(f"Already in position for {inst_id}, skipping")
                        continue

                    if decision["action"] in ["BUY", "SELL"]:
                        result = trading.place_order(inst_id, decision["action"], 0, data['price'])
                        code = result.get('code', '?')
                        if code == '0':
                            trades_made += 1
                            action_emoji = "🟢 LONG" if decision["action"] == "BUY" else "🔴 SHORT"
                            notional = TRADE_AMOUNT_USDT * LEVERAGE
                            await app.bot.send_message(
                                chat_id,
                                f"✅ *Futures Trade Executed!*\n\n"
                                f"Coin: {coin}\n"
                                f"Direction: {action_emoji}\n"
                                f"Entry: ${data['price']:,.4f}\n"
                                f"Leverage: {LEVERAGE}x\n"
                                f"Margin used: ${TRADE_AMOUNT_USDT}\n"
                                f"Position size: ${notional:.2f}\n"
                                f"Stop Loss: ${result.get('sl_price', 'N/A')}\n"
                                f"Take Profit: ${result.get('tp_price', 'N/A')}\n"
                                f"Confidence: {decision.get('confidence')}%\n"
                                f"Reason: _{decision['reason']}_",
                                parse_mode="Markdown"
                            )
                        else:
                            await app.bot.send_message(chat_id, f"⚠️ Order failed {coin}: {result.get('msg', result)}")
                    else:
                        logger.info(f"HOLD {inst_id}: {decision['reason']}")
                except Exception as e:
                    logger.error(f"Error {inst_id}: {e}")
                await asyncio.sleep(2)

            await app.bot.send_message(
                chat_id,
                f"✅ Scan complete — {trades_made} trade(s) executed\nNext scan in 15 min ⏱"
            )
        except Exception as e:
            await app.bot.send_message(chat_id, f"⚠️ Error: {e}")
        await asyncio.sleep(900)

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
                f"🤖 *Futures Auto Trading ENABLED!*\n\n"
                f"⚡ Leverage: {LEVERAGE}x\n"
                f"💵 ${TRADE_AMOUNT_USDT} margin → ${TRADE_AMOUNT_USDT * LEVERAGE} position\n"
                f"🛡 Stop Loss: 2% | Take Profit: 4%\n"
                f"⏱ Scanning every 15 minutes",
                parse_mode="Markdown"
            )
        else:
            await query.message.reply_text("⚠️ Already running!")
    elif query.data == "auto_off":
        auto_trading_active = False
        if auto_task:
            auto_task.cancel()
        await query.message.reply_text("🛑 *Auto trading STOPPED.*\nYour open positions remain active.", parse_mode="Markdown")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("OKX Futures AI Bot started!")
    app.run_polling()

if __name__ == "__main__":
    main()
