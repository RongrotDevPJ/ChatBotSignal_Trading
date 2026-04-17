import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import pytz
from utils.logger import logger, log_thinking

class SMCAnalyzer:
    def __init__(self, symbol="XAUUSD"):
        self.symbol = self._find_symbol(symbol, ["XAUUSD", "GOLD"])
        self.dxy = self._find_symbol("DXY", ["DXY", "USDX", "DX", "USDOLLAR"])
        self.timezone = pytz.timezone("Asia/Bangkok")
        
        # Daily Context Caching
        self.pdh = None
        self.pdl = None
        self.last_daily_sync_date = None

    def _find_symbol(self, default, keys):
        symbols = mt5.symbols_get()
        if not symbols: return default
        for sym in symbols:
            if any(k in sym.name.upper() for k in keys):
                if mt5.symbol_select(sym.name, True):
                    return sym.name
        return default

    def sync_daily_data(self):
        """Fetches PDH/PDL only once per day or upon init"""
        now_date = datetime.now(self.timezone).date()
        if self.last_daily_sync_date == now_date:
            return # Already cached

        logger.info("[SYSTEM] Syncing Daily Context (PDH/PDL)...")
        # Fetch last 2 daily bars (Previous day is index 1)
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_D1, 1, 1)
        if rates is not None and len(rates) > 0:
            self.pdh = float(rates[0]['high'])
            self.pdl = float(rates[0]['low'])
            self.last_daily_sync_date = now_date
            log_thinking(f"[LIQUIDITY] PDH Cached: {self.pdh} | PDL Cached: {self.pdl}")
        else:
            logger.error("[SYSTEM] Failed to fetch daily data for caching.")

    def fetch_data(self, timeframe, count=100):
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
        if rates is None:
            logger.error(f"[SYSTEM] Failed to fetch data for {self.symbol}")
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def get_dxy_trend(self):
        if not self.dxy: return 0
        rates = mt5.copy_rates_from_pos(self.dxy, mt5.TIMEFRAME_M15, 0, 3)
        if rates is None or len(rates) < 3: return 0
        return 1 if rates[-1]['close'] > rates[0]['open'] else -1

    def detect_pivots(self, df):
        """Detects Swing Highs and Lows using a 5-candle fractal (window=2)"""
        pivots = []
        for i in range(2, len(df) - 2):
            # Swing High
            if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[i-2] and \
               df['high'].iloc[i] > df['high'].iloc[i+1] and df['high'].iloc[i] > df['high'].iloc[i+2]:
                pivots.append({'type': 'HIGH', 'price': df['high'].iloc[i], 'index': i, 'time': df['time'].iloc[i]})
            
            # Swing Low
            if df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[i-2] and \
               df['low'].iloc[i] < df['low'].iloc[i+1] and df['low'].iloc[i] < df['low'].iloc[i+2]:
                pivots.append({'type': 'LOW', 'price': df['low'].iloc[i], 'index': i, 'time': df['time'].iloc[i]})
        return pivots

    def analyze(self):
        log_thinking("Scanning M15 Market Structure...")
        self.sync_daily_data()
        
        df = self.fetch_data(mt5.TIMEFRAME_M15, 200)
        if df is None: return None
        
        last_candle_time = int(df.iloc[-1]['time'].timestamp())
        pivots = self.detect_pivots(df)
        
        # 1. Structure Check (Mechanical BOS/CHoCH - Close Based)
        last_price = df.iloc[-1]['close']
        recent_highs = [p for p in pivots if p['type'] == 'HIGH']
        recent_lows = [p for p in pivots if p['type'] == 'LOW']
        
        bos_bullish = False
        bos_bearish = False
        if recent_highs and last_price > recent_highs[-1]['price']:
            bos_bullish = True
            log_thinking(f"[STRUCTURE] Bullish BOS detected at {last_price} > Pivot {recent_highs[-1]['price']}")
        elif recent_lows and last_price < recent_lows[-1]['price']:
            bos_bearish = True
            log_thinking(f"[STRUCTURE] Bearish BOS detected at {last_price} < Pivot {recent_lows[-1]['price']}")

        # 2. Liquidity Sweep Detection
        sweep_bullish = False
        sweep_bearish = False
        if self.pdl and (df.iloc[-1]['low'] < self.pdl < df.iloc[-1]['close']):
            sweep_bullish = True
            log_thinking(f"[LIQUIDITY] Bullish Sweep detected: Price dipped below PDL {self.pdl} and closed back.")
        if self.pdh and (df.iloc[-1]['high'] > self.pdh > df.iloc[-1]['close']):
            sweep_bearish = True
            log_thinking(f"[LIQUIDITY] Bearish Sweep detected: Price swept beyond PDH {self.pdh} and closed back.")

        # 3. FVG and Order Block (OB)
        # Simplified OB: Last candle of opposite color before BOS
        bullish_ob_detected = False
        bearish_ob_detected = False
        if bos_bullish and df.iloc[recent_highs[-1]['index']-1]['close'] < df.iloc[recent_highs[-1]['index']-1]['open']:
            bullish_ob_detected = True # Last down candle
        if bos_bearish and df.iloc[recent_lows[-1]['index']-1]['close'] > df.iloc[recent_lows[-1]['index']-1]['open']:
            bearish_ob_detected = True # Last up candle

        fvg_up = df.iloc[-1]['low'] > df.iloc[-3]['high']
        fvg_down = df.iloc[-1]['high'] < df.iloc[-3]['low']

        # 4. Scoring Algorithm
        score = 0
        confluences = []
        signal_type = "NEUTRAL"

        if sweep_bullish or sweep_bearish:
            score += 3
            confluences.append("Liquidity Sweep")
            signal_type = "BUY" if sweep_bullish else "SELL"
        
        if bos_bullish or bos_bearish:
            score += 3
            confluences.append(f"{'Bullish' if bos_bullish else 'Bearish'} BOS")
            if signal_type == "NEUTRAL": signal_type = "BUY" if bos_bullish else "SELL"
        
        if fvg_up or fvg_down:
            score += 2
            confluences.append("FVG Detected")

        if bullish_ob_detected or bearish_ob_detected:
            score += 2
            confluences.append("Order Block Found")

        # DXY Correlation
        dxy_trend = self.get_dxy_trend()
        if (signal_type == "BUY" and dxy_trend == 1) or (signal_type == "SELL" and dxy_trend == -1):
            score -= 2
            logger.info(f"[CORRELATION] DXY Mismatch. USD Strength opposes {signal_type}.")
            confluences.append("⚠️ DXY Opposing")
        elif dxy_trend != 0:
            confluences.append("DXY Confirmed")

        if score >= 6 and signal_type != "NEUTRAL":
            # Extra verification for 10/10
            if score >= 10: log_thinking(f"🏆 10/10 AI SIGNAL DETECTED: {signal_type}")
            
            entry = df.iloc[-1]['close']
            atr = (df['high'] - df['low']).rolling(14).mean().iloc[-1]
            sl = entry - (atr * 2) if signal_type == "BUY" else entry + (atr * 2)
            tp = entry + (atr * 4) if signal_type == "BUY" else entry - (atr * 4)

            return {
                "type": signal_type,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "score": score,
                "strategy": " + ".join(confluences),
                "candle_time": last_candle_time,
                "time": datetime.now(self.timezone).strftime("%H:%M:%S"),
                "news_active": False
            }
        
        return None
