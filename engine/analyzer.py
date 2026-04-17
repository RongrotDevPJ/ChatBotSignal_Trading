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

    def _find_symbol(self, default, keys):
        """Tries to find a symbol match from a list of keywords"""
        symbols = mt5.symbols_get()
        if not symbols: return default
        for sym in symbols:
            if any(k in sym.name.upper() for k in keys):
                if mt5.symbol_select(sym.name, True):
                    return sym.name
        return default

    def fetch_data(self, timeframe, count=100):
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
        if rates is None:
            logger.error(f"[SYSTEM] Failed to fetch data for {self.symbol}")
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def get_dxy_trend(self):
        """Returns 1 for Bulls, -1 for Bears, 0 for Neutral"""
        if not self.dxy:
            logger.warning("[CORRELATION] DXY/USDX symbol not found or not selectable.")
            return 0
        
        rates = mt5.copy_rates_from_pos(self.dxy, mt5.TIMEFRAME_M15, 0, 3)
        if rates is None or len(rates) < 3: return 0
        
        if rates[-1]['close'] > rates[0]['open']:
            return 1
        elif rates[-1]['close'] < rates[0]['open']:
            return -1
        return 0

    def analyze(self):
        log_thinking("Scanning M15 Market Structure...")
        df_m15 = self.fetch_data(mt5.TIMEFRAME_M15, 100)
        if df_m15 is None: return None
        
        # Unique ID for candle (Open Time)
        last_candle_time = int(df_m15.iloc[-1]['time'].timestamp())
        
        # Simplified Logic
        fvg_up = df_m15.iloc[-1]['low'] > df_m15.iloc[-3]['high']
        fvg_down = df_m15.iloc[-1]['high'] < df_m15.iloc[-3]['low']
        
        score = 0
        confluences = []
        signal_type = "NEUTRAL"

        if fvg_up:
            score += 4
            confluences.append("Bullish FVG")
            signal_type = "BUY"
        elif fvg_down:
            score += 4
            confluences.append("Bearish FVG")
            signal_type = "SELL"

        # DXY Correlation
        dxy_trend = self.get_dxy_trend()
        if (signal_type == "BUY" and dxy_trend == 1) or (signal_type == "SELL" and dxy_trend == -1):
            score -= 2
            logger.info(f"[CORRELATION] Mismatch detected with {self.dxy}. USD Strength opposes Signal.")
            confluences.append("⚠️ DXY Opposing")
        elif dxy_trend != 0:
            confluences.append(f"DXY Confirmed ({'Bullish' if dxy_trend==1 else 'Bearish'})")

        if score >= 5 and signal_type != "NEUTRAL":
            entry = df_m15.iloc[-1]['close']
            atr = (df_m15['high'] - df_m15['low']).rolling(14).mean().iloc[-1]
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
                "news_active": False # Placeholder
            }
        
        return None
