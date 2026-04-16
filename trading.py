import os
import hmac
import hashlib
import base64
import time
import requests
import json
from typing import Dict, List
from datetime import datetime, timezone

OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
BASE_URL = "https://www.okx.com"

class TradingEngine:
    def __init__(self):
        self.api_key = OKX_API_KEY
        self.secret = OKX_SECRET
        self.passphrase = OKX_PASSPHRASE

    def _get_timestamp(self):
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    def _sign(self, timestamp, method, path, body=''):
        message = timestamp + method.upper() + path + (body or '')
        sig = hmac.new(
            self.secret.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        return base64.b64encode(sig).decode()

    def _headers(self, method, path, body=''):
        ts = self._get_timestamp()
        return {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': self._sign(ts, method, path, body),
            'OK-ACCESS-TIMESTAMP': ts,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json',
        }

    def get_balance(self) -> Dict[str, float]:
        path = '/api/v5/account/balance'
        r = requests.get(BASE_URL + path, headers=self._headers('GET', path))
        r.raise_for_status()
        data = r.json()
        balances = {}
        if data.get('code') == '0':
            details = data['data'][0]['details']
            for item in details:
                if float(item.get('availBal', 0)) > 0:
                    balances[item['ccy']] = float(item['availBal'])
        return balances

    def get_market_data(self, symbol: str) -> dict:
        # symbol format for OKX: BTC-USDT
        inst_id = symbol.replace('USDT', '-USDT')

        # Current price
        ticker_r = requests.get(f"{BASE_URL}/api/v5/market/ticker", params={"instId": inst_id})
        ticker_r.raise_for_status()
        ticker = ticker_r.json()['data'][0]
        price = float(ticker['last'])
        change_24h = float(ticker['sodUtc8']) if ticker.get('sodUtc8') else 0
        change_pct = round(((price - change_24h) / change_24h * 100) if change_24h else 0, 2)

        # Candlestick data for indicators
        candle_r = requests.get(f"{BASE_URL}/api/v5/market/candles", params={
            "instId": inst_id, "bar": "1H", "limit": "50"
        })
        candle_r.raise_for_status()
        candles = candle_r.json()['data']
        closes = [float(c[4]) for c in reversed(candles)]

        rsi = self._calculate_rsi(closes)
        sma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else price
        sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else price

        return {
            "symbol": symbol,
            "inst_id": inst_id,
            "price": price,
            "rsi": round(rsi, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "trend": "BULLISH" if sma20 > sma50 else "BEARISH",
            "change_24h": change_pct,
            "volume_24h": round(float(ticker.get('volCcy24h', 0)), 2),
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
        path = '/api/v5/account/positions'
        r = requests.get(BASE_URL + path, headers=self._headers('GET', path))
        r.raise_for_status()
        data = r.json()
        positions = []
        if data.get('code') == '0':
            for p in data['data']:
                if float(p.get('pos', 0)) != 0:
                    positions.append({
                        "symbol": p['instId'],
                        "side": p['posSide'],
                        "qty": float(p['pos']),
                        "entry_price": float(p.get('avgPx', 0)),
                    })
        return positions

    def place_order(self, inst_id: str, side: str, qty: float) -> dict:
        path = '/api/v5/trade/order'
        body = json.dumps({
            "instId": inst_id,
            "tdMode": "cash",
            "side": side.lower(),
            "ordType": "market",
            "sz": str(qty),
        })
        r = requests.post(
            BASE_URL + path,
            headers=self._headers('POST', path, body),
            data=body
        )
        r.raise_for_status()
        return r.json()

    def get_usdt_balance(self) -> float:
        balance = self.get_balance()
        return float(balance.get("USDT", 0))
