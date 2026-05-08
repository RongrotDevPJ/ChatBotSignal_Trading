import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
import pytz
from utils.logger import logger, log_thinking
from utils.news_filter import NewsFilter


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
        self.last_market_signal_candle = None
        self.last_killzone_log_time = None
        self.news_filter = NewsFilter()

    def _find_symbol(self, default, keys):
        symbols = mt5.symbols_get()
        if not symbols:
            return default
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
        if rates is None:
            return None
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def get_dxy_trend(self):
        if not self.dxy:
            return 0
        rates = mt5.copy_rates_from_pos(self.dxy, mt5.TIMEFRAME_M15, 0, 3)
        if rates is None or len(rates) < 3:
            return 0
        return 1 if rates[-1]['close'] > rates[0]['open'] else -1

    def get_htf_trend(self):
        """Checks H4 Trend using EMA 50."""
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H4, 0, 60)
        if rates is None or len(rates) < 50:
            return 0
        df = pd.DataFrame(rates)
        ema50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        current_price = df['close'].iloc[-1]
        return 1 if current_price > ema50 else -1

    # ── FIX #7 — H1 Bias Layer ───────────────────────────────────
    def get_h1_bias(self):
        """
        Returns H1 market bias using Higher High/Higher Low or Lower High/Lower Low.
        1 = Bullish, -1 = Bearish, 0 = Ranging
        """
        rates = mt5.copy_rates_from_pos(self.symbol, mt5.TIMEFRAME_H1, 0, 20)
        if rates is None or len(rates) < 10:
            return 0
        df = pd.DataFrame(rates)
        highs = df['high'].values[-6:]
        lows  = df['low'].values[-6:]

        hh = highs[-1] > highs[-3] > highs[-5]
        hl = lows[-1]  > lows[-3]  > lows[-5]
        lh = highs[-1] < highs[-3] < highs[-5]
        ll = lows[-1]  < lows[-3]  < lows[-5]

        if hh and hl:
            return 1
        if lh and ll:
            return -1
        return 0

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

    # ── FIX #3 — True OB Candle Finder ──────────────────────────
    def _find_ob_candle(self, df, pivot_index, direction="bullish"):
        """
        Scans backwards from a pivot to find the true Order Block candle —
        the last opposing candle before the impulsive move.
          - Bullish BOS  → last bearish candle (close < open)
          - Bearish BOS  → last bullish candle (close > open)
        Falls back to pivot_index-1 if none found within 10 bars.
        """
        search_start = pivot_index - 1
        search_end   = max(0, pivot_index - 10)
        for i in range(search_start, search_end - 1, -1):
            candle = df.iloc[i]
            if direction == "bullish" and candle['close'] < candle['open']:
                return candle
            if direction == "bearish" and candle['close'] > candle['open']:
                return candle
        return df.iloc[max(0, pivot_index - 1)]  # safe fallback

    # ── FIX #6 — BOS Body-Ratio Filter ──────────────────────────
    def _is_strong_bos_candle(self, candle, min_body_ratio=0.5):
        """
        Returns True only if the BOS candle body is >= 50% of its total range.
        Rejects doji/spinning-top fake-breaks.
        """
        body = abs(candle['close'] - candle['open'])
        total_range = candle['high'] - candle['low']
        if total_range == 0:
            return False
        return (body / total_range) >= min_body_ratio

    # ── FIX #8 — Internal Range Liquidity Detection ─────────────
    def detect_internal_liquidity(self, df, lookback=20):
        """
        Detects internal liquidity pools: equal highs (sell-side) and
        equal lows (buy-side) within the last `lookback` candles.
        Returns (eq_high_levels, eq_low_levels) as lists of price levels.
        """
        highs = df['high'].iloc[-lookback:].values
        lows  = df['low'].iloc[-lookback:].values
        tolerance = 0.15  # $0.15 tolerance for Gold

        eq_high_levels = []
        for i in range(len(highs)):
            for j in range(i + 1, len(highs)):
                if abs(highs[i] - highs[j]) <= tolerance:
                    eq_high_levels.append(round((highs[i] + highs[j]) / 2, 2))

        eq_low_levels = []
        for i in range(len(lows)):
            for j in range(i + 1, len(lows)):
                if abs(lows[i] - lows[j]) <= tolerance:
                    eq_low_levels.append(round((lows[i] + lows[j]) / 2, 2))

        return list(set(eq_high_levels)), list(set(eq_low_levels))

    def is_within_kill_zone(self):
        now = datetime.now(self.timezone)
        time_str = now.strftime("%H:%M")
        if "14:00" <= time_str < "17:30":
            return True
        if "19:00" <= time_str < "22:30":
            return True
        return False

    def analyze(self):
        if self.news_filter.is_news_active():
            return None

        if not self.is_within_kill_zone():
            now = datetime.now(self.timezone)
            if self.last_killzone_log_time is None or self.last_killzone_log_time.hour != now.hour:
                logger.info("[SYSTEM] Market is outside of Kill Zones. Waiting for liquidity.")
                self.last_killzone_log_time = now
            return None

        self.sync_daily_data()

        # 0. Spread Filter
        symbol_info = mt5.symbol_info(self.symbol)
        current_spread = 0
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
        last_closed_price  = last_closed_candle['close']
        last_candle_time   = int(last_closed_candle['time'].timestamp())

        high_pivots = [p for p in pivots if p['type'] == 'HIGH']
        low_pivots  = [p for p in pivots if p['type'] == 'LOW']

        bos_bullish = False
        bos_bearish = False

        # ── FIX #6 — BOS Body-Ratio Gate applied here ───────────
        if high_pivots and last_closed_price > high_pivots[-1]['price']:
            if self._is_strong_bos_candle(last_closed_candle):
                bos_bullish = True
        elif low_pivots and last_closed_price < low_pivots[-1]['price']:
            if self._is_strong_bos_candle(last_closed_candle):
                bos_bearish = True

        sweep_bullish = False
        sweep_bearish = False

        # Log ONCE per candle
        if last_candle_time != self.last_logged_candle_time:
            if bos_bullish and high_pivots:
                log_thinking(f"[STRUCTURE] Bullish BOS: Candle closed at {last_closed_price} > Pivot {high_pivots[-1]['price']}")
            elif bos_bearish and low_pivots:
                log_thinking(f"[STRUCTURE] Bearish BOS: Candle closed at {last_closed_price} < Pivot {low_pivots[-1]['price']}")

            if self.pdl and (last_closed_candle['low'] < self.pdl < last_closed_price):
                sweep_bullish = True
                log_thinking(f"[LIQUIDITY] Bullish Sweep: Price took out PDL {self.pdl} and closed back.")
            elif self.pdh and (last_closed_candle['high'] > self.pdh > last_closed_price):
                sweep_bearish = True
                log_thinking(f"[LIQUIDITY] Bearish Sweep: Price swept PDH {self.pdh} and rejected.")

            self.last_logged_candle_time = last_candle_time
        else:
            if self.pdl and (last_closed_candle['low'] < self.pdl < last_closed_price):
                sweep_bullish = True
            elif self.pdh and (last_closed_candle['high'] > self.pdh > last_closed_price):
                sweep_bearish = True

        fvg_up   = df_m15.iloc[-2]['low']  > df_m15.iloc[-4]['high']
        fvg_down = df_m15.iloc[-2]['high'] < df_m15.iloc[-4]['low']

        # ── FIX #3 — True OB Candle via _find_ob_candle ─────────
        ob_open = None
        ob_low  = None
        ob_high = None
        if bos_bullish and high_pivots:
            ob_candle = self._find_ob_candle(df_m15, high_pivots[-1]['index'], direction="bullish")
            ob_open = ob_candle['open']
            ob_low  = ob_candle['low']
        elif bos_bearish and low_pivots:
            ob_candle = self._find_ob_candle(df_m15, low_pivots[-1]['index'], direction="bearish")
            ob_open = ob_candle['open']
            ob_high = ob_candle['high']

        dxy_trend = self.get_dxy_trend()
        h1_bias   = self.get_h1_bias()

        execution_mode = "MARKET"
        signal_type    = "NEUTRAL"
        entry_price    = last_closed_price

        tick = mt5.symbol_info_tick(self.symbol)

        # 1. Market Execution Priority: Sweep
        if sweep_bullish:
            signal_type    = "BUY"
            execution_mode = "MARKET"
            if tick: entry_price = tick.ask
        elif sweep_bearish:
            signal_type    = "SELL"
            execution_mode = "MARKET"
            if tick: entry_price = tick.bid

        # 2. Limit Order Priority: BOS with valid OB
        elif (bos_bullish or bos_bearish) and ob_open:
            buffer      = 0.02
            entry_price = ob_open + buffer if bos_bullish else ob_open - buffer
            signal_type    = "BUY LIMIT" if bos_bullish else "SELL LIMIT"
            execution_mode = "LIMIT"

        # Confluence Scoring
        score = 0
        confluences = []
        if sweep_bullish or sweep_bearish:
            score += 3; confluences.append("Liquidity Sweep")
        if bos_bullish or bos_bearish:
            score += 3; confluences.append("BOS Structure")
        if fvg_up or fvg_down:
            score += 2; confluences.append("FVG Gap")
        if ob_open:
            score += 2; confluences.append("Order Block")

        # DXY Correlation
        if (signal_type.startswith("BUY") and dxy_trend == 1) or \
           (signal_type.startswith("SELL") and dxy_trend == -1):
            score -= 2; confluences.append("⚠️ DXY Mismatch")
        elif dxy_trend != 0:
            confluences.append("DXY Verified")

        # H4 EMA50 Trend
        htf_trend = self.get_htf_trend()
        if htf_trend != 0:
            if (signal_type.startswith("BUY") and htf_trend == 1) or \
               (signal_type.startswith("SELL") and htf_trend == -1):
                score += 2; confluences.append("H4 Trend Align")
            else:
                score -= 2; confluences.append("⚠️ H4 Counter-Trend")

        # ── FIX #7 — H1 Bias Layer ──────────────────────────────
        if h1_bias != 0:
            if (signal_type.startswith("BUY") and h1_bias == 1) or \
               (signal_type.startswith("SELL") and h1_bias == -1):
                score += 1; confluences.append("H1 Bias Align")
            else:
                score -= 1; confluences.append("⚠️ H1 Counter-Bias")

        # ── FIX #8 — Internal Liquidity Scoring ─────────────────
        eq_highs, eq_lows = self.detect_internal_liquidity(df_m15)
        INTERNAL_LIQ_DIST_PIPS = 50
        liq_confirmed = False
        if signal_type.startswith("BUY") and eq_lows:
            if any(abs(entry_price - lvl) * 100 <= INTERNAL_LIQ_DIST_PIPS for lvl in eq_lows):
                liq_confirmed = True
        elif signal_type.startswith("SELL") and eq_highs:
            if any(abs(entry_price - lvl) * 100 <= INTERNAL_LIQ_DIST_PIPS for lvl in eq_highs):
                liq_confirmed = True
        if liq_confirmed:
            score += 2; confluences.append("Internal Liquidity")

        # ── FIX #4 — Counter-HTF Score Gate ─────────────────────
        # MARKET orders trading against the H4 trend require score >= 8
        MIN_SCORE = 6
        if execution_mode == "MARKET" and htf_trend != 0:
            htf_mismatch = (
                (signal_type.startswith("BUY")  and htf_trend == -1) or
                (signal_type.startswith("SELL") and htf_trend == 1)
            )
            if htf_mismatch:
                MIN_SCORE = 8
                log_thinking(f"[RISK] Counter-HTF MARKET signal detected. Score gate raised to {MIN_SCORE}.")

        if score >= MIN_SCORE and signal_type != "NEUTRAL":
            # 1. Structural SL Calculation
            buffer = 0.2
            if signal_type.startswith("BUY"):
                struct_sl = ob_low if ob_low else last_closed_candle['low']
                sl = struct_sl - buffer
            else:
                struct_sl = ob_high if ob_high else last_closed_candle['high']
                sl = struct_sl + buffer

            # ── FIX #5 — Adaptive Minimum SL ────────────────────
            # LIMIT entries get a 1.5× minimum to survive OB volatility
            MIN_SL_GOLD = 3.0
            effective_min_sl = MIN_SL_GOLD * (1.5 if execution_mode == "LIMIT" else 1.0)
            current_dist = abs(entry_price - sl)

            if current_dist < effective_min_sl:
                if signal_type.startswith("BUY"):
                    sl = entry_price - effective_min_sl
                else:
                    sl = entry_price + effective_min_sl
                log_thinking(
                    f"[RISK] SL adjusted to {'LIMIT' if execution_mode == 'LIMIT' else 'MARKET'} "
                    f"minimum {effective_min_sl:.1f}$ distance: {sl:.2f}"
                )

            # 3. TP Calculation (TP1 at 1:1, TP2 at 1:2)
            final_sl_dist = abs(entry_price - sl)
            if signal_type.startswith("BUY"):
                tp1 = entry_price + final_sl_dist
                tp2 = entry_price + (final_sl_dist * 2)
            else:
                tp1 = entry_price - final_sl_dist
                tp2 = entry_price - (final_sl_dist * 2)

            sl_pips  = abs(entry_price - sl) * 100
            tp1_pips = abs(tp1 - entry_price) * 100
            tp2_pips = abs(tp2 - entry_price) * 100

            # Session
            now_hour = datetime.now(self.timezone).hour
            if 6 <= now_hour < 14:   session = "ASIAN"
            elif 14 <= now_hour < 19: session = "LONDON"
            else:                      session = "NY"

            if execution_mode == "MARKET":
                if self.last_market_signal_candle == last_candle_time:
                    logger.warning("[SYSTEM] Signal Suppressed: Market order already executed on this candle.")
                    return None
                self.last_market_signal_candle = last_candle_time

            # ── FIX #9 — 5 New ML-Ready Fields ──────────────────
            candle_body  = abs(last_closed_candle['close'] - last_closed_candle['open'])
            candle_range = last_closed_candle['high'] - last_closed_candle['low']
            candle_body_ratio = round(candle_body / candle_range, 4) if candle_range > 0 else 0.0

            day_of_week = datetime.now(self.timezone).weekday()

            # 14-period ATR on M15
            highs_arr  = df_m15['high'].values[-15:]
            lows_arr   = df_m15['low'].values[-15:]
            closes_arr = df_m15['close'].values[-15:]
            trs = [
                max(highs_arr[i] - lows_arr[i],
                    abs(highs_arr[i] - closes_arr[i-1]),
                    abs(lows_arr[i]  - closes_arr[i-1]))
                for i in range(1, 15)
            ]
            atr_14_m15 = round(sum(trs) / 14, 4)

            if bos_bullish and high_pivots:
                pivot_distance_pips = round((last_closed_price - high_pivots[-1]['price']) * 100, 1)
            elif bos_bearish and low_pivots:
                pivot_distance_pips = round((low_pivots[-1]['price'] - last_closed_price) * 100, 1)
            else:
                pivot_distance_pips = 0.0

            return {
                "type": signal_type,
                "mode": execution_mode,
                "entry": entry_price,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "sl_pips": sl_pips,
                "tp1_pips": tp1_pips,
                "tp2_pips": tp2_pips,
                "score": score,
                "strategy": " + ".join(confluences),
                "candle_time": last_candle_time,
                "time": datetime.now(self.timezone).strftime("%H:%M:%S"),
                "news_active": False,
                "session": session,
                "dxy_trend": dxy_trend,
                "htf_trend": htf_trend,
                "h1_bias": h1_bias,
                "confluence_count": len(confluences),
                "spread_at_entry": current_spread,
                # ML fields
                "candle_body_ratio": candle_body_ratio,
                "day_of_week": day_of_week,
                "atr_14_m15": atr_14_m15,
                "pivot_distance_pips": pivot_distance_pips,
            }

        return None
