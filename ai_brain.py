import os
import json
import requests
import anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "5"))
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

class AIBrain:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def get_crypto_news(self, inst_id: str) -> str:
        coin = inst_id.replace("-USDT", "")
        try:
            if NEWS_API_KEY:
                r = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={"q": coin + " crypto", "sortBy": "publishedAt", "pageSize": 5, "apiKey": NEWS_API_KEY, "language": "en"},
                    timeout=5
                )
                if r.status_code == 200:
                    articles = r.json().get("articles", [])
                    if articles:
                        return "\n".join("- " + a['title'] for a in articles[:5])
            r = requests.get(
                "https://cryptopanic.com/api/v1/posts/?auth_token=free&currencies=" + coin + "&kind=news",
                timeout=5
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                return "\n".join("- " + p['title'] for p in results[:5])
        except Exception:
            pass
        return "No recent news"

    async def analyze(self, inst_id: str, market_data: dict) -> dict:
        news = self.get_crypto_news(inst_id)
        tf = market_data['timeframes']

        prompt = """You are an expert crypto spot trading AI.
Analyze this data and decide: BUY, SELL, or HOLD.

COIN: """ + inst_id + """
Price: $""" + str(market_data['price']) + """
Trend: """ + market_data['trend'] + """
Volume: """ + market_data['volume_signal'] + """

15m RSI: """ + str(tf['15m']['rsi']) + """ | MACD: """ + str(tf['15m']['macd_hist']) + """
1H  RSI: """ + str(tf['1h']['rsi']) + """ | MACD: """ + str(tf['1h']['macd_hist']) + """
    BB: """ + str(tf['1h']['bb_lower']) + """ / """ + str(tf['1h']['bb_mid']) + """ / """ + str(tf['1h']['bb_upper']) + """
    EMA9: """ + str(tf['1h']['ema9']) + """ EMA21: """ + str(tf['1h']['ema21']) + """ EMA50: """ + str(tf['1h']['ema50']) + """
4H  RSI: """ + str(tf['4h']['rsi']) + """ | MACD: """ + str(tf['4h']['macd_hist']) + """

NEWS: """ + news + """

RULES:
- BUY: RSI<40 on 1h+4h, MACD positive, price near BB lower, bullish EMAs
- SELL: RSI>65 on 1h+4h, MACD negative, price near BB upper
- HOLD: mixed or unclear signals
- Need 2+ confirmations
- Trade amount: $""" + str(TRADE_AMOUNT_USDT) + """ USDT

Respond ONLY with JSON:
{"action": "BUY" or "SELL" or "HOLD", "qty": 0.001, "confidence": 75, "signals_confirmed": 3, "reason": "short reason", "news_sentiment": "POSITIVE" or "NEGATIVE" or "NEUTRAL"}

qty = """ + str(TRADE_AMOUNT_USDT) + """ / price rounded to 6 decimals.
JSON only."""

        message = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        decision = json.loads(raw)

        if decision.get("confidence", 0) < 55:
            decision["action"] = "HOLD"
            decision["reason"] += " (low confidence)"

        if decision.get("signals_confirmed", 0) < 2:
            decision["action"] = "HOLD"
            decision["reason"] += " (weak signals)"

        if decision.get("news_sentiment") == "NEGATIVE" and decision["action"] == "BUY":
            decision["action"] = "HOLD"
            decision["reason"] += " (negative news)"

        return decision
