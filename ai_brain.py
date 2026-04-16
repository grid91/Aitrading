import os
import json
import requests
import anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "10"))
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

class AIBrain:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def get_crypto_news(self, symbol: str) -> str:
        """Fetch latest crypto news for the given symbol"""
        coin = symbol.replace("-USDT", "")
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
                    },
                    timeout=5
                )
                if r.status_code == 200:
                    articles = r.json().get("articles", [])
                    if articles:
                        headlines = [a['title'] for a in articles[:5]]
                        return "\n".join(f"- {h}" for h in headlines)
            # Fallback: CryptoPanic free API (no key needed)
            r = requests.get(
                f"https://cryptopanic.com/api/v1/posts/?auth_token=free&currencies={coin}&kind=news",
                timeout=5
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                headlines = [p['title'] for p in results[:5]]
                return "\n".join(f"- {h}" for h in headlines)
        except Exception:
            pass
        return "No recent news available"

    async def analyze(self, inst_id: str, market_data: dict) -> dict:
        coin = inst_id.replace("-USDT", "")
        news = self.get_crypto_news(inst_id)
        tf = market_data['timeframes']

        prompt = f"""You are an expert crypto trading AI with deep knowledge of technical analysis.
Analyze ALL of the following data and make a precise trading decision.

=== COIN: {inst_id} ===
Current Price: ${market_data['price']:,.4f}
Overall Trend: {market_data['trend']}
Volume Signal: {market_data['volume_signal']}

=== TECHNICAL INDICATORS ===

15-Minute Timeframe:
- RSI: {tf['15m']['rsi']}
- MACD Histogram: {tf['15m']['macd_hist']}

1-Hour Timeframe:
- RSI: {tf['1h']['rsi']}
- MACD Histogram: {tf['1h']['macd_hist']}
- Bollinger Upper: ${tf['1h']['bb_upper']}
- Bollinger Mid: ${tf['1h']['bb_mid']}
- Bollinger Lower: ${tf['1h']['bb_lower']}
- EMA 9: ${tf['1h']['ema9']}
- EMA 21: ${tf['1h']['ema21']}
- EMA 50: ${tf['1h']['ema50']}
- EMA 200: ${tf['1h']['ema200']}

4-Hour Timeframe:
- RSI: {tf['4h']['rsi']}
- MACD Histogram: {tf['4h']['macd_hist']}

=== LATEST NEWS ===
{news}

=== TRADING RULES ===
BUY signals (need at least 3 confirmations):
- RSI < 35 on 1h or 4h (oversold)
- MACD histogram turning positive
- Price near or below Bollinger lower band
- EMA9 crossing above EMA21
- Bullish trend
- Positive/neutral news sentiment
- High volume on upward movement

SELL signals (need at least 2 confirmations):
- RSI > 70 on 1h or 4h (overbought)
- MACD histogram turning negative
- Price near or above Bollinger upper band
- EMA9 crossing below EMA21
- Bearish news sentiment

HOLD when:
- Signals are mixed or unclear
- News is very negative (high risk)
- Volume is LOW (no conviction)
- Sideways trend with no clear direction

Trade size: ${TRADE_AMOUNT_USDT} USDT
Qty = {TRADE_AMOUNT_USDT} / current_price (round to 6 decimal places)

Respond ONLY with valid JSON:
{{
  "action": "BUY" or "SELL" or "HOLD",
  "qty": 0.000100,
  "confidence": 85,
  "signals_confirmed": 4,
  "reason": "RSI oversold 28 on 1h+4h, MACD turning bullish, price at BB lower, positive news",
  "news_sentiment": "POSITIVE" or "NEGATIVE" or "NEUTRAL",
  "risk_level": "LOW" or "MEDIUM" or "HIGH"
}}

Only trade if confidence >= 75 and signals_confirmed >= 3. Otherwise HOLD.
Only respond with the JSON object, nothing else."""

        message = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        decision = json.loads(raw)

        # Safety checks
        if decision.get("confidence", 0) < 75:
            decision["action"] = "HOLD"
            decision["reason"] += " (confidence below 75%)"

        if decision.get("signals_confirmed", 0) < 3:
            decision["action"] = "HOLD"
            decision["reason"] += " (insufficient signal confirmation)"

        if decision.get("risk_level") == "HIGH":
            decision["action"] = "HOLD"
            decision["reason"] += " (risk too high)"

        if decision.get("news_sentiment") == "NEGATIVE" and decision["action"] == "BUY":
            decision["action"] = "HOLD"
            decision["reason"] += " (negative news — avoiding buy)"

        return decision
