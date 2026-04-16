import os
import math
import hmac
import hashlib
import base64
import requests
import json
from typing import Dict, List
from datetime import datetime, timezone

OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_SECRET")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
TRADE_AMOUNT_USDT = float(os.getenv("TRADE_AMOUNT_USDT", "10"))
BASE_URL = "https://www.okx.com"

SYMBOLS = [
    "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT",
    "XRP-USDT", "ADA-USDT", "DOGE-USDT", "AVAX-USDT",
    "LINK-USDT", "DOT-USDT"
]

STOP_LOSS_PCT = 0.02
TAKE_PROFIT_PCT = 0.04

class TradingEngine:
    def __init__(self):
        self.api_key = OKX_API_KEY
        self.secret = OKX_SECRET
        self.passphrase = OKX_PASSPHRASE

    def _get_timestamp(self):
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    def _sign(self, timestamp, method, path, body=''):
        message = timestamp + method.upper() + path + (body or '')
        sig = hmac.new(self.secret.encode(), message.encode(), hashlib.sha256).digest()
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
            for item in data['data'][0]['details']:
                if float(item.get('availBal', 0)) > 0:
                    balances[item['ccy']] = float(item['availBal'])
        return balances

    def get_candles(self, inst_id: str, bar: str, limit: int = 100) -> list:
        r = requests.get(f"{BASE_URL}/api/v5/market/candles", params={
            "instId": inst_id, "bar": bar, "limit": str(limit)
        })
        r.raise_for_status()
        return [float(c[4]) for c in reversed(r.json().get('data', []))]

    def get_full_candles(self, inst_id: str, bar: str, limit: int = 100) -> list:
        r = requests.get(f"{BASE_URL}/api/v5/market/candles", params={
            "instId": inst_id, "bar": bar, "limit": str(limit)
        })
        r.raise_for_status()
        return list(reversed(r.json().get('data', [])))

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

    def _calculate_macd(self, closes: list):
        def ema(data, period):
            if len(data) < period:
                return data[-1] if data else 0
            k = 2 / (period + 1)
            val = sum(data[:period]) / period
            for p in data[period:]:
                val = p * k + val * (1 - k)
            return val
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        macd_line = ema12 - ema26
        macd_values = []
        for i in range(26, len(closes)):
            macd_values.append(ema(closes[:i+1], 12) - ema(closes[:i+1], 26))
        signal = ema(macd_values, 9) if len(macd_values) >= 9 else 0
        return round(macd_line, 4), round(signal, 4), round(macd_line - signal, 4)

    def _calculate_bollinger(self, closes: list, period: int = 20):
        if len(closes) < period:
            return closes[-1], closes[-1], closes[-1]
        recent = closes[-period:]
        sma = sum(recent) / period
        std = (sum((x - sma) ** 2 for x in recent) / period) ** 0.5
        return round(sma + 2*std, 2), round(sma, 2), round(sma - 2*std, 2)

    def _calculate_ema(self, closes: list, period: int) -> float:
        if len(closes) < period:
            return closes[-1] if closes else 0
        k = 2 / (period + 1)
        val = sum(closes[:period]) / period
        for p in closes[period:]:
            val = p * k + val * (1 - k)
        return round(val, 4)

    def _volume_signal(self, candles: list) -> str:
        if len(candles) < 20:
            return "NORMAL"
        volumes = [float(c[5]) for c in candles]
        avg_vol = sum(volumes[-20:-1]) / 19
        curr_vol = volumes[-1]
        if curr_vol > avg_vol * 1.5:
            return "HIGH"
        elif curr_vol < avg_vol * 0.5:
            return "LOW"
        return "NORMAL"

    def get_instrument_info(self, inst_id: str) -> dict:
        """Get min order size and lot size for instrument"""
        r = requests.get(f"{BASE_URL}/api/v5/public/instruments", params={
            "instType": "SPOT", "instId": inst_id
        })
        r.raise_for_status()
        data = r.json()
        if data.get('code') == '0' and data.get('data'):
            inst = data['data'][0]
            return {
                "min_sz": float(inst.get('minSz', 0.00001)),
                "lot_sz": float(inst.get('lotSz', 0.00001)),
            }
        return {"min_sz": 0.00001, "lot_sz": 0.00001}

    def get_market_data(self, inst_id: str) -> dict:
        ticker_r = requests.get(f"{BASE_URL}/api/v5/market/ticker", params={"instId": inst_id})
        ticker_r.raise_for_status()
        ticker = ticker_r.json()['data'][0]
        price = float(ticker['last'])

        closes_15m = self.get_candles(inst_id, "15m", 100)
        closes_1h = self.get_candles(inst_id, "1H", 100)
        closes_4h = self.get_candles(inst_id, "4H", 100)
        candles_1h_full = self.get_full_candles(inst_id, "1H", 100)

        rsi_15m = self._calculate_rsi(closes_15m)
        _, _, hist_15m = self._calculate_macd(closes_15m)
        rsi_1h = self._calculate_rsi(closes_1h)
        _, _, hist_1h = self._calculate_macd(closes_1h)
        bb_upper, bb_mid, bb_lower = self._calculate_bollinger(closes_1h)
        ema9 = self._calculate_ema(closes_1h, 9)
        ema21 = self._calculate_ema(closes_1h, 21)
        ema50 = self._calculate_ema(closes_1h, 50)
        ema200 = self._calculate_ema(closes_1h, 200)
        vol_signal = self._volume_signal(candles_1h_full)
        rsi_4h = self._calculate_rsi(closes_4h)
        _, _, hist_4h = self._calculate_macd(closes_4h)
        trend = "BULLISH" if ema9 > ema21 > ema50 else "BEARISH" if ema9 < ema21 < ema50 else "SIDEWAYS"

        return {
            "inst_id": inst_id,
            "price": price,
            "trend": trend,
            "volume_signal": vol_signal,
            "timeframes": {
                "15m": {"rsi": round(rsi_15m, 2), "macd_hist": hist_15m},
                "1h": {
                    "rsi": round(rsi_1h, 2), "macd_hist": hist_1h,
                    "bb_upper": bb_upper, "bb_mid": bb_mid, "bb_lower": bb_lower,
                    "ema9": ema9, "ema21": ema21, "ema50": ema50, "ema200": ema200,
                },
                "4h": {"rsi": round(rsi_4h, 2), "macd_hist": hist_4h},
            },
        }

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
                        "pnl": float(p.get('upl', 0)),
                    })
        return positions

    def place_order(self, inst_id: str, side: str, qty: float, price: float) -> dict:
        """Place spot market order — BUY uses USDT amount, SELL uses coin amount"""
        inst_info = self.get_instrument_info(inst_id)
        lot_sz = inst_info['lot_sz']
        min_sz = inst_info['min_sz']

        sl_price = round(price * (1 - STOP_LOSS_PCT), 6) if side.upper() == "BUY" else round(price * (1 + STOP_LOSS_PCT), 6)
        tp_price = round(price * (1 + TAKE_PROFIT_PCT), 6) if side.upper() == "BUY" else round(price * (1 - TAKE_PROFIT_PCT), 6)

        path = '/api/v5/trade/order'

        if side.upper() == "BUY":
            # For market BUY on spot: sz = amount in USDT, tgtCcy = quote_ccy
            order_body = {
                "instId": inst_id,
                "tdMode": "cash",
                "side": "buy",
                "ordType": "market",
                "sz": str(round(TRADE_AMOUNT_USDT, 2)),
                "tgtCcy": "quote_ccy",
            }
        else:
            # For market SELL on spot: sz = amount in base coin
            # Round to valid lot size
            decimals = len(str(lot_sz).rstrip('0').split('.')[-1]) if '.' in str(lot_sz) else 0
            rounded_qty = math.floor(qty / lot_sz) * lot_sz
            rounded_qty = round(rounded_qty, decimals)

            if rounded_qty < min_sz:
                return {"code": "error", "msg": f"Sell qty {rounded_qty} below minimum {min_sz}", "sl_price": sl_price, "tp_price": tp_price}

            order_body = {
                "instId": inst_id,
                "tdMode": "cash",
                "side": "sell",
                "ordType": "market",
                "sz": str(rounded_qty),
            }

        body = json.dumps(order_body)
        r = requests.post(BASE_URL + path, headers=self._headers('POST', path, body), data=body)
        r.raise_for_status()
        result = r.json()
        result['sl_price'] = sl_price
        result['tp_price'] = tp_price
        return result

    def get_usdt_balance(self) -> float:
        return float(self.get_balance().get("USDT", 0))
