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
        self.last_logged_candle_time = None

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

    def get_htf_trend(self):
        """Checks H4 Trend using EMA 50"""
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H4, 0, 60)
        if rates is None or len(rates) < 50: return 0
        df = pd.DataFrame(rates)
        ema50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        current_price = df['close'].iloc[-1]
        return 1 if current_price > ema50 else -1

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
        
        # 0. Spread Filter
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info:
            current_spread = symbol_info.spread
            if current_spread > 700:
                logger.warning(f"[SYSTEM] Signal Suppressed: High Spread ({current_spread} pts > 700)")
                return None
        
        df_m15 = self.fetch_data(mt5.TIMEFRAME_M15, 200)
        
        if df_m15 is None or df_m15.empty or len(df_m15) < 10:
            return None

        pivots = self.detect_pivots(df_m15)
        
        # Strictly CLOSED candle analysis
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

        # Sweeps verified against CLOSED candle values
        sweep_bullish = False
        sweep_bearish = False
        
        # Logging structure/liquidity findings ONLY ONCE per candle
        if last_candle_time != self.last_logged_candle_time:
            if bos_bullish:
                log_thinking(f"[STRUCTURE] Bullish BOS: Candle closed at {last_closed_price} > Pivot {high_pivots[-1]['price']}")
            elif bos_bearish:
                log_thinking(f"[STRUCTURE] Bearish BOS: Candle closed at {last_closed_price} < Pivot {low_pivots[-1]['price']}")

            if self.pdl and (last_closed_candle['low'] < self.pdl < last_closed_price):
                sweep_bullish = True
                log_thinking(f"[LIQUIDITY] Bullish Sweep: Price took out PDL {self.pdl} and closed back.")
            elif self.pdh and (last_closed_candle['high'] > self.pdh > last_closed_price):
                sweep_bearish = True
                log_thinking(f"[LIQUIDITY] Bearish Sweep: Price swept PDH {self.pdh} and rejected.")
            
            self.last_logged_candle_time = last_candle_time
        else:
            # Re-detect sweeps for internal logic without re-logging
            if self.pdl and (last_closed_candle['low'] < self.pdl < last_closed_price):
                sweep_bullish = True
            elif self.pdh and (last_closed_candle['high'] > self.pdh > last_closed_price):
                sweep_bearish = True

        fvg_up = df_m15.iloc[-2]['low'] > df_m15.iloc[-4]['high']
        fvg_down = df_m15.iloc[-2]['high'] < df_m15.iloc[-4]['low']
        
        ob_open = None
        ob_low = None
        ob_high = None
        if bos_bullish:
            # Last down candle before bos
            ob_candle = df_m15.iloc[high_pivots[-1]['index']-1]
            ob_open = ob_candle['open']
            ob_low = ob_candle['low']
        elif bos_bearish:
            # Last up candle before bos
            ob_candle = df_m15.iloc[low_pivots[-1]['index']-1]
            ob_open = ob_candle['open']
            ob_high = ob_candle['high']

        # DXY Correlation
        dxy_trend = self.get_dxy_trend()
        
        # Dual Mode Logic
        execution_mode = "MARKET"
        signal_type = "NEUTRAL"
        entry_price = last_closed_price
        
        # 1. Market Execution Priority: Sweep
        if sweep_bullish:
            signal_type = "BUY"
            execution_mode = "MARKET"
        elif sweep_bearish:
            signal_type = "SELL"
            execution_mode = "MARKET"
        
        # 2. Limit Order Priority: BOS with valid OB
        elif (bos_bullish or bos_bearish) and ob_open:
            # Add 2-point front-running buffer (0.02 for Gold)
            buffer = 0.02
            entry_price = ob_open + buffer if bos_bullish else ob_open - buffer
            signal_type = "BUY LIMIT" if bos_bullish else "SELL LIMIT"
            execution_mode = "LIMIT"

        # Confluence Scoring
        score = 0
        confluences = []
        if sweep_bullish or sweep_bearish: score += 3; confluences.append("Liquidity Sweep")
        if bos_bullish or bos_bearish: score += 3; confluences.append("BOS Structure")
        if fvg_up or fvg_down: score += 2; confluences.append("FVG Gap")
        if ob_open: score += 2; confluences.append("Order Block")
        
        if (signal_type.startswith("BUY") and dxy_trend == 1) or (signal_type.startswith("SELL") and dxy_trend == -1):
            score -= 2
            confluences.append("⚠️ DXY Mismatch")
        elif dxy_trend != 0:
            confluences.append("DXY Verified")

        # HTF Context (H4 EMA 50)
        htf_trend = self.get_htf_trend()
        if htf_trend != 0:
            if (signal_type.startswith("BUY") and htf_trend == 1) or (signal_type.startswith("SELL") and htf_trend == -1):
                score += 2
                confluences.append("H4 Trend Align")
            else:
                score -= 2
                confluences.append("⚠️ H4 Counter-Trend")

        if score >= 6 and signal_type != "NEUTRAL":
            # 1. Structural SL Calculation
            buffer = 0.2 # $0.20 buffer as requested
            if signal_type.startswith("BUY"):
                # Use OB Low or Sweep Low
                struct_sl = ob_low if ob_low else last_closed_candle['low']
                sl = struct_sl - buffer
            else: # SELL
                struct_sl = ob_high if ob_high else last_closed_candle['high']
                sl = struct_sl + buffer

            # 2. Minimum SL Distance Rule (3.0$ / 300 points)
            MIN_SL_GOLD = 3.0
            current_dist = abs(entry_price - sl)
            
            if current_dist < MIN_SL_GOLD:
                if signal_type.startswith("BUY"):
                    sl = entry_price - MIN_SL_GOLD
                else:
                    sl = entry_price + MIN_SL_GOLD
                log_thinking(f"[RISK] SL adjusted to minimum {MIN_SL_GOLD}$ distance: {sl:.2f}")

            # 3. TP Calculation (Default 1:2 RR as minimum)
            # Ensure TP is calculated FROM the final SL distance
            final_sl_dist = abs(entry_price - sl)
            if signal_type.startswith("BUY"):
                tp = entry_price + (final_sl_dist * 2)
            else:
                tp = entry_price - (final_sl_dist * 2)

            # 4. Pip Calculation (1.00 move = 100 pips for Gold)
            sl_pips = abs(entry_price - sl) * 100
            tp_pips = abs(tp - entry_price) * 100

            return {
                "type": signal_type,
                "mode": execution_mode,
                "entry": entry_price,
                "sl": sl,
                "tp": tp,
                "sl_pips": sl_pips,
                "tp_pips": tp_pips,
                "score": score,
                "strategy": " + ".join(confluences),
                "candle_time": last_candle_time,
                "time": datetime.now(self.timezone).strftime("%H:%M:%S"),
                "news_active": False
            }
        
        return None
