import os
import json
import anthropic

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "10"))  # Default $10 per trade

class AIBrain:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    async def analyze(self, symbol: str, market_data: dict) -> dict:
        prompt = f"""You are an expert crypto trading AI. Analyze this market data and decide whether to BUY, SELL, or HOLD.

Symbol: {symbol}
Current Price: ${market_data['price']}
RSI (14): {market_data['rsi']}
SMA 20: ${market_data['sma20']}
SMA 50: ${market_data['sma50']}
Trend: {market_data['trend']}
24h Change: {market_data['change_24h']}%
24h Volume: ${market_data['volume_24h']:,.0f}

Trading Rules:
- BUY when: RSI < 35 (oversold) AND trend is BULLISH AND price > SMA20
- SELL when: RSI > 70 (overbought) OR trend turned BEARISH
- HOLD when: market is uncertain or already in position
- Never risk more than 2% of portfolio per trade
- Trade amount: ${TRADE_AMOUNT_USDT} USDT worth

Respond ONLY with a valid JSON object like this:
{{
  "action": "BUY" or "SELL" or "HOLD",
  "qty": 0.0001,
  "confidence": 85,
  "reason": "RSI oversold at 28, bullish trend confirmed"
}}

qty should be the amount of the BASE asset to buy/sell (e.g. for BTCUSDT, qty is in BTC).
Calculate qty as: {TRADE_AMOUNT_USDT} / current_price, rounded to 5 decimal places.
Only respond with the JSON, nothing else."""

        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = message.content[0].text.strip()
        # Clean up markdown if present
        raw = raw.replace("```json", "").replace("```", "").strip()
        decision = json.loads(raw)

        # Safety check - never trade if confidence < 70
        if decision.get("confidence", 0) < 70:
            decision["action"] = "HOLD"
            decision["reason"] += " (confidence too low)"

        return decision
