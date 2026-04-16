import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from trading import TradingEngine, SYMBOLS
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
    ]
    coins = " • ".join([s.replace("-USDT", "") for s in SYMBOLS])
    await update.message.reply_text(
        "🤖 *AI Trading Bot Pro — OKX*\n\n"
        f"📊 Coins: {coins}\n"
        "⏱ Timeframes: 15m + 1H + 4H\n"
        "📰 News analysis: Enabled\n"
        "🛡 Stop Loss: 2% | Take Profit: 4%\n\n"
        "Use the buttons below to control me:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@restricted
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    try:
        bal = trading.get_balance()
        if not bal:
            await msg.reply_text("💰 No balance found or account empty.")
            return
        text = "💰 *Your OKX Balance:*\n\n"
        for asset, amount in bal.items():
            text += f"• {asset}: `{amount:.4f}`\n"
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
                pnl_emoji = "🟢" if p['pnl'] >= 0 else "🔴"
                text += f"• {p['symbol']}: {p['qty']} @ ${p['entry_price']:,.4f} {pnl_emoji} PnL: ${p['pnl']:.2f}\n"
            await msg.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Error: {e}")

@restricted
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    await msg.reply_text("🔍 Analyzing 10 coins across 3 timeframes + news... please wait ~30s")
    try:
        results = []
        for inst_id in SYMBOLS:
            try:
                data = trading.get_market_data(inst_id)
                decision = await brain.analyze(inst_id, data)
                emoji = "🟢" if decision['action'] == "BUY" else "🔴" if decision['action'] == "SELL" else "⏸"
                coin = inst_id.replace("-USDT", "")
                results.append(
                    f"{emoji} *{coin}* — {decision['action']}\n"
                    f"Price: ${data['price']:,.4f} | RSI 1H: {data['timeframes']['1h']['rsi']}\n"
                    f"Confidence: {decision.get('confidence', 0)}% | News: {decision.get('news_sentiment', 'N/A')}\n"
                    f"_{decision['reason']}_"
                )
            except Exception as e:
                results.append(f"⚠️ {inst_id}: Error — {e}")

        # Split into 2 messages if too long
        half = len(results) // 2
        await msg.reply_text("📈 *AI Analysis — Part 1:*\n\n" + "\n\n".join(results[:half]), parse_mode="Markdown")
        await msg.reply_text("📈 *AI Analysis — Part 2:*\n\n" + "\n\n".join(results[half:]), parse_mode="Markdown")
    except Exception as e:
        await msg.reply_text(f"❌ Analysis error: {e}")

@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.callback_query.message
    state = "🟢 RUNNING" if auto_trading_active else "🔴 STOPPED"
    usdt = trading.get_usdt_balance()
    await msg.reply_text(
        f"📋 *Bot Status:*\n\n"
        f"Exchange: OKX\n"
        f"Auto Trading: {state}\n"
        f"Interval: Every 15 minutes\n"
        f"Coins: {len(SYMBOLS)} pairs\n"
        f"Timeframes: 15m + 1H + 4H\n"
        f"Stop Loss: 2% | Take Profit: 4%\n"
        f"USDT Available: ${usdt:.2f}",
        parse_mode="Markdown"
    )

async def auto_trade_loop(app: Application, chat_id: int):
    global auto_trading_active
    while auto_trading_active:
        try:
            await app.bot.send_message(chat_id, "🔄 *Auto scan starting — 10 coins...*", parse_mode="Markdown")
            trades_made = 0
            for inst_id in SYMBOLS:
                if not auto_trading_active:
                    break
                try:
                    data = trading.get_market_data(inst_id)
                    decision = await brain.analyze(inst_id, data)
                    coin = inst_id.replace("-USDT", "")

                    if decision["action"] in ["BUY", "SELL"]:
                        result = trading.place_order(inst_id, decision["action"], decision["qty"], data['price'])
                        code = result.get('code', '?')
                        if code == '0':
                            trades_made += 1
                            action_emoji = "🟢 BUY" if decision["action"] == "BUY" else "🔴 SELL"
                            await app.bot.send_message(
                                chat_id,
                                f"✅ *Trade Executed!*\n\n"
                                f"Coin: {coin}\n"
                                f"Action: {action_emoji}\n"
                                f"Price: ${data['price']:,.4f}\n"
                                f"Qty: {decision['qty']}\n"
                                f"Stop Loss: ${result.get('sl_price', 'N/A')}\n"
                                f"Take Profit: ${result.get('tp_price', 'N/A')}\n"
                                f"Confidence: {decision.get('confidence')}%\n"
                                f"News: {decision.get('news_sentiment', 'N/A')}\n"
                                f"Reason: _{decision['reason']}_",
                                parse_mode="Markdown"
                            )
                        else:
                            await app.bot.send_message(chat_id, f"⚠️ Order failed for {coin}: {result.get('msg', result)}")
                    else:
                        logger.info(f"HOLD {inst_id}: {decision['reason']}")
                except Exception as e:
                    logger.error(f"Error processing {inst_id}: {e}")
                await asyncio.sleep(2)  # Small delay between coins

            summary = f"✅ Scan complete — {trades_made} trade(s) executed. Next scan in 15 min."
            await app.bot.send_message(chat_id, summary)
        except Exception as e:
            await app.bot.send_message(chat_id, f"⚠️ Auto trade error: {e}")
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
    elif query.data == "auto_on":
        if not auto_trading_active:
            auto_trading_active = True
            auto_task = asyncio.create_task(auto_trade_loop(context.application, chat_id))
            await query.message.reply_text(
                "🤖 *Auto Trading ENABLED!*\n\n"
                "Scanning 10 coins every 15 minutes\n"
                "Using 15m + 1H + 4H signals\n"
                "News analysis active 📰\n"
                "Stop Loss: 2% | Take Profit: 4% 🛡",
                parse_mode="Markdown"
            )
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
    logger.info("AI Trading Bot Pro started!")
    app.run_polling()

if __name__ == "__main__":
    main()
