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
        
        # Daily Context Caching (PDH/PDL)
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
        now_date = datetime.now(self.timezone).date()
        if self.last_daily_sync_date == now_date and self.pdh is not None:
            return 

        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_D1, 1, 1)
        if rates is not None and len(rates) > 0:
            self.pdh = float(rates[0]['high'])
            self.pdl = float(rates[0]['low'])
            self.last_daily_sync_date = now_date
            log_thinking(f"[LIQUIDITY] Cached PDH: {self.pdh} | PDL: {self.pdl}")
        else:
            logger.error("[SYSTEM] Failed to sync Daily context data.")

    def fetch_data(self, timeframe, count=200):
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
        if rates is None: return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def get_dxy_trend(self):
        if not self.dxy: return 0
        rates = mt5.copy_rates_from_pos(self.dxy, mt5.TIMEFRAME_M15, 0, 3)
        if rates is None or len(rates) < 3: return 0
        return 1 if rates[-1]['close'] > rates[0]['open'] else -1

    def detect_pivots(self, df):
        pivots = []
        for i in range(2, len(df) - 2):
            if df['high'].iloc[i] > df['high'].iloc[i-1] and df['high'].iloc[i] > df['high'].iloc[i-2] and \
               df['high'].iloc[i] > df['high'].iloc[i+1] and df['high'].iloc[i] > df['high'].iloc[i+2]:
                pivots.append({'type': 'HIGH', 'price': df['high'].iloc[i], 'index': i})
            
            if df['low'].iloc[i] < df['low'].iloc[i-1] and df['low'].iloc[i] < df['low'].iloc[i-2] and \
               df['low'].iloc[i] < df['low'].iloc[i+1] and df['low'].iloc[i] < df['low'].iloc[i+2]:
                pivots.append({'type': 'LOW', 'price': df['low'].iloc[i], 'index': i})
        return pivots

    def analyze(self):
        self.sync_daily_data()
        df_m15 = self.fetch_data(mt5.TIMEFRAME_M15, 200)
        
        if df_m15 is None or df_m15.empty or len(df_m15) < 10:
            return None

        pivots = self.detect_pivots(df_m15)
        
        # [FIX] Use iloc[-2] for strictly CLOSED candle analysis
        last_closed_candle = df_m15.iloc[-2]
        last_closed_price = last_closed_candle['close']
        last_candle_time = int(last_closed_candle['time'].timestamp())
        
        high_pivots = [p for p in pivots if p['type'] == 'HIGH']
        low_pivots = [p for p in pivots if p['type'] == 'LOW']
        
        bos_bullish = False
        bos_bearish = False
        
        if high_pivots and last_closed_price > high_pivots[-1]['price']:
            bos_bullish = True
            log_thinking(f"[STRUCTURE] Bullish BOS: Candle closed at {last_closed_price} > Pivot {high_pivots[-1]['price']}")
        elif low_pivots and last_closed_price < low_pivots[-1]['price']:
            bos_bearish = True
            log_thinking(f"[STRUCTURE] Bearish BOS: Candle closed at {last_closed_price} < Pivot {low_pivots[-1]['price']}")

        # [FIX] Sweeps must verify against CLOSED candle values
        sweep_bullish = False
        sweep_bearish = False
        if self.pdl and (last_closed_candle['low'] < self.pdl < last_closed_price):
            sweep_bullish = True
            log_thinking(f"[LIQUIDITY] Bullish Sweep: Price took out PDL {self.pdl} and closed back.")
        elif self.pdh and (last_closed_candle['high'] > self.pdh > last_closed_price):
            sweep_bearish = True
            log_thinking(f"[LIQUIDITY] Bearish Sweep: Price swept PDH {self.pdh} and rejected.")

        fvg_up = df_m15.iloc[-2]['low'] > df_m15.iloc[-4]['high']
        fvg_down = df_m15.iloc[-2]['high'] < df_m15.iloc[-4]['low']
        
        ob_found = False
        if bos_bullish and df_m15.iloc[high_pivots[-1]['index']-1]['close'] < df_m15.iloc[high_pivots[-1]['index']-1]['open']:
            ob_found = True
        elif bos_bearish and df_m15.iloc[low_pivots[-1]['index']-1]['close'] > df_m15.iloc[low_pivots[-1]['index']-1]['open']:
            ob_found = True

        score = 0
        confluences = []
        signal_type = "NEUTRAL"

        if sweep_bullish or sweep_bearish:
            score += 3
            confluences.append("Liquidity Sweep")
            signal_type = "BUY" if sweep_bullish else "SELL"
        
        if bos_bullish or bos_bearish:
            score += 3
            confluences.append("BOS Structure")
            if signal_type == "NEUTRAL": signal_type = "BUY" if bos_bullish else "SELL"
            
        if fvg_up or fvg_down:
            score += 2
            confluences.append("FVG Gap")
            
        if ob_found:
            score += 2
            confluences.append("Order Block")

        dxy_trend = self.get_dxy_trend()
        if (signal_type == "BUY" and dxy_trend == 1) or (signal_type == "SELL" and dxy_trend == -1):
            score -= 2
            logger.info(f"[CORRELATION] Score Penalty (-2): DXY Trend opposes {signal_type} signal.")
            confluences.append("⚠️ DXY Mismatch")
        elif dxy_trend != 0:
            confluences.append("DXY Verified")

        if score >= 6 and signal_type != "NEUTRAL":
            if score >= 10: 
                log_thinking(f"🏆 [BRAIN] 10/10 AI Score achieved for {signal_type}")
            
            atr = (df_m15['high'] - df_m15['low']).rolling(14).mean().iloc[-1]
            sl = last_closed_price - (atr * 2) if signal_type == "BUY" else last_closed_price + (atr * 2)
            tp = last_closed_price + (atr * 4) if signal_type == "BUY" else last_closed_price - (atr * 4)

            return {
                "type": signal_type, "entry": last_closed_price, "sl": sl, "tp": tp,
                "score": score, "strategy": " + ".join(confluences),
                "candle_time": last_candle_time, "time": datetime.now(self.timezone).strftime("%H:%M:%S"),
                "news_active": False
            }
        
        return None
