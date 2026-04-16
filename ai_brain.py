import os
import json
import requests
import anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "10"))
LEVERAGE = int(os.getenv("LEVERAGE", "10"))
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

class AIBrain:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def get_crypto_news(self, inst_id: str) -> str:
        coin = inst_id.replace("-USDT-SWAP", "")
        try:
            if NEWS_API_KEY:
                r = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": f"{coin} crypto",
                        "sortBy": "publishedAt",
                        "pageSize": 5,
                        "apiKey": NEWS_API_KEY,
                        "language": "en"
                    }, timeout=5
                )
                if r.status_code == 200:
                    articles = r.json().get("articles", [])
                    if articles:
                        return "\n".join(f"- {a['title']}" for a in articles[:5])
            # Fallback: CryptoPanic
            r = requests.get(
                f"https://cryptopanic.com/api/v1/posts/?auth_token=free&currencies={coin}&kind=news",
                timeout=5
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                return "\n".join(f"- {p['title']}" for p in results[:5])
        except Exception:
            pass
        return "No recent news available"

    async def analyze(self, inst_id: str, market_data: dict) -> dict:
        coin = inst_id.replace("-USDT-SWAP", "")
        news = self.get_crypto_news(inst_id)
        tf = market_data['timeframes']
        notional = TRADE_AMOUNT_USDT * LEVERAGE

        prompt = f"""You are an expert crypto futures trading AI.
Analyze this data and decide: BUY (go long), SELL (go short), or HOLD.

COIN: {inst_id}
Price: ${market_data['price']:,.4f}
Trend: {market_data['trend']}
Volume: {market_data['volume_signal']}

15m — RSI: {tf['15m']['rsi']} | MACD: {tf['15m']['macd_hist']}
1H  — RSI: {tf['1h']['rsi']} | MACD: {tf['1h']['macd_hist']}
     BB Upper: ${tf['1h']['bb_upper']} | Mid: ${tf['1h']['bb_mid']} | Lower: ${tf['1h']['bb_lower']}
     EMA9: ${tf['1h']['ema9']} | EMA21: ${tf['1h']['ema21']} | EMA50: ${tf['1h']['ema50']}
4H  — RSI: {tf['4h']['rsi']} | MACD: {tf['4h']['macd_hist']}

NEWS:
{news}

RULES:
- BUY (long): RSI<35 on 1h+4h, MACD turning positive, price near BB lower, bullish EMAs, positive news
- SELL (short): RSI>70 on 1h+4h, MACD turning negative, price near BB upper, bearish EMAs
- HOLD: mixed signals, negative news on BUY, low volume, sideways trend
- Need 3+ confirmations to trade
- Futures: {LEVERAGE}x leverage, ${TRADE_AMOUNT_USDT} margin = ${notional} position

Respond ONLY with JSON:
{{
  "action": "BUY" or "SELL" or "HOLD",
  "qty": 0.001,
  "confidence": 85,
  "signals_confirmed": 4,
  "reason": "short reason here",
  "news_sentiment": "POSITIVE" or "NEGATIVE" or "NEUTRAL",
  "risk_level": "LOW" or "MEDIUM" or "HIGH"
}}

Only trade if confidence>=75 and signals_confirmed>=3. Otherwise HOLD.
qty = {TRADE_AMOUNT_USDT} / price rounded to 6 decimals.
JSON only, nothing else."""

        message = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        decision = json.loads(raw)

        # Safety checks
        if decision.get("confidence", 0) < 75:
            decision["action"] = "HOLD"
            decision["reason"] += " (low confidence)"

        if decision.get("signals_confirmed", 0) < 3:
            decision["action"] = "HOLD"
            decision["reason"] += " (not enough signals)"

        if decision.get("risk_level") == "HIGH":
            decision["action"] = "HOLD"
            decision["reason"] += " (high risk)"

        if decision.get("news_sentiment") == "NEGATIVE" and decision["action"] == "BUY":
            decision["action"] = "HOLD"
            decision["reason"] += " (negative news)"

        return decision
