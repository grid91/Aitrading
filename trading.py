import os
import hmac
import hashlib
import time
import requests
from typing import Dict, List

BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")
BASE_URL = "https://api.binance.com"

class TradingEngine:
    def __init__(self):
        self.api_key = BINANCE_API_KEY
        self.secret = BINANCE_SECRET
        self.headers = {"X-MBX-APIKEY": self.api_key}

    def _sign(self, params: dict) -> dict:
        params["timestamp"] = int(time.time() * 1000)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        sig = hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def get_balance(self) -> Dict[str, float]:
        params = self._sign({})
        r = requests.get(f"{BASE_URL}/api/v3/account", headers=self.headers, params=params)
        r.raise_for_status()
        data = r.json()
        return {b["asset"]: b["free"] for b in data["balances"] if float(b["free"]) > 0}

    def get_market_data(self, symbol: str) -> dict:
        # Get current price
        price_r = requests.get(f"{BASE_URL}/api/v3/ticker/price", params={"symbol": symbol})
        price_r.raise_for_status()
        price = float(price_r.json()["price"])

        # Get klines (candlestick data) for indicators
        kline_r = requests.get(f"{BASE_URL}/api/v3/klines", params={
            "symbol": symbol, "interval": "1h", "limit": 50
        })
        kline_r.raise_for_status()
        klines = kline_r.json()
        closes = [float(k[4]) for k in klines]

        # Calculate RSI
        rsi = self._calculate_rsi(closes)

        # Calculate simple moving averages
        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / 50

        # 24h change
        stats_r = requests.get(f"{BASE_URL}/api/v3/ticker/24hr", params={"symbol": symbol})
        stats_r.raise_for_status()
        stats = stats_r.json()

        return {
            "symbol": symbol,
            "price": price,
            "rsi": round(rsi, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "trend": "BULLISH" if sma20 > sma50 else "BEARISH",
            "change_24h": round(float(stats["priceChangePercent"]), 2),
            "volume_24h": round(float(stats["quoteVolume"]), 2),
        }

    def _calculate_rsi(self, closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i+1] - closes[i] for i in range(len(closes)-1)]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def get_open_positions(self) -> List[dict]:
        """Get current non-zero balances as positions"""
        balance = self.get_balance()
        positions = []
        for asset, amount in balance.items():
            if asset == "USDT":
                continue
            symbol = f"{asset}USDT"
            try:
                price_r = requests.get(f"{BASE_URL}/api/v3/ticker/price", params={"symbol": symbol})
                if price_r.status_code == 200:
                    price = float(price_r.json()["price"])
                    positions.append({
                        "symbol": symbol,
                        "side": "LONG",
                        "qty": float(amount),
                        "entry_price": price,
                        "value_usdt": float(amount) * price
                    })
            except:
                pass
        return positions

    def place_order(self, symbol: str, side: str, qty: float) -> dict:
        """Place a market order on Binance"""
        params = self._sign({
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
        })
        r = requests.post(f"{BASE_URL}/api/v3/order", headers=self.headers, params=params)
        r.raise_for_status()
        return r.json()

    def get_usdt_balance(self) -> float:
        balance = self.get_balance()
        return float(balance.get("USDT", 0))
