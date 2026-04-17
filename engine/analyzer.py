import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import pytz
from utils.logger import logger, log_thinking

class SMCAnalyzer:
    def __init__(self, symbol="XAUUSD"):
        self.symbol = symbol
        self.timezone = pytz.timezone("Asia/Bangkok")

    def fetch_data(self, timeframe, count=100):
        """Fetches OHLC data from MT5"""
        log_thinking(f"Fetching {count} bars for {self.symbol} on {timeframe}")
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
        if rates is None:
            logger.error(f"Failed to fetch data for {self.symbol}, error: {mt5.last_error()}")
            return None
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def is_kill_zone(self):
        """Checks if current BKK time is in ICT Kill Zone"""
        now = datetime.now(self.timezone)
        current_time = now.strftime("%H:%M")
        
        london = "14:00" <= current_time <= "17:00"
        new_york = "19:00" <= current_time <= "22:00"
        
        if london: return "London Kill Zone"
        if new_york: return "New York Kill Zone"
        return None

    def detect_fvg(self, df):
        """Detects Fair Value Gaps in the dataframe"""
        # Bearish FVG: High[2] < Low[0]
        # Bullish FVG: Low[2] > High[0]
        fvgs = []
        for i in range(2, len(df)):
            # Bearish
            if df.iloc[i-2]['high'] < df.iloc[i]['low']:
                fvgs.append({'type': 'BULLISH', 'top': df.iloc[i]['low'], 'bottom': df.iloc[i-2]['high'], 'index': i-1})
            # Bullish
            elif df.iloc[i-2]['low'] > df.iloc[i]['high']:
                fvgs.append({'type': 'BEARISH', 'top': df.iloc[i-2]['low'], 'bottom': df.iloc[i]['high'], 'index': i-1})
        return fvgs

    def detect_structures(self, df):
        """Detects Swing Highs/Lows and BOS"""
        # Simple swing detection using rolling windows
        df['is_high'] = (df['high'] == df['high'].rolling(window=5, center=True).max())
        df['is_low'] = (df['low'] == df['low'].rolling(window=5, center=True).min())
        
        swings = df[(df['is_high']) | (df['is_low'])].copy()
        return swings

    def find_dxy_symbol(self):
        """Tries to find the DXY/USDX symbol"""
        symbols = mt5.symbols_get()
        for sym in symbols:
            if sym.name.upper() in ["DXY", "USDX", "USDOLLAR"]:
                return sym.name
        return None

    def get_dxy_trend(self):
        """Returns 1 for Uptrend, -1 for Downtrend, 0 for Neutral"""
        dxy = self.find_dxy_symbol()
        if not dxy:
            logger.warning("DXY/USDX symbol not found for correlation check.")
            return 0
        
        rates = mt5.copy_rates_from_pos(dxy, mt5.TIMEFRAME_M15, 0, 3)
        if rates is None or len(rates) < 3:
            return 0
        
        # Simple trend: Close > Open of the cluster or higher highs
        if rates[-1]['close'] > rates[0]['open']:
            return 1 # Bullish
        elif rates[-1]['close'] < rates[0]['open']:
            return -1 # Bearish
        return 0

    def check_news_active(self):
        """Placeholder for News check logic"""
        # In production, this would query an economic calendar API
        # Return True if high-impact news is within +/- 30 mins
        import os
        return os.getenv("NEWS_ACTIVE_DEBUG", "FALSE").upper() == "TRUE"

    def analyze(self):
        """Main analysis logic"""
        log_thinking("Starting full analysis cycle...")
        
        # 1. Fetch M15 for Structure
        df_m15 = self.fetch_data(mt5.TIMEFRAME_M15, 100)
        if df_m15 is None: return None
        
        last_candle_time = int(df_m15.iloc[-1]['time'].timestamp())
        
        # 2. Basic Analysis
        fvgs = self.detect_fvg(df_m15)
        swings = self.detect_structures(df_m15)
        kill_zone = self.is_kill_zone()
        dxy_trend = self.get_dxy_trend()
        news_active = self.check_news_active()
        
        last_price = df_m15.iloc[-1]['close']
        
        score = 0
        reasons = []
        
        if fvgs and abs(fvgs[-1]['index'] - len(df_m15)) < 5:
            score += 3
            reasons.append(f"Recent FVG Found ({fvgs[-1]['type']})")
            
        if kill_zone:
            score += 2
            reasons.append(f"Active {kill_zone}")
            
        # Simplified signal type based on FVG
        signal_type = "NEUTRAL"
        if fvgs:
            signal_type = fvgs[-1]['type']
            
        # 3. DXY Correlation Check
        if signal_type == "BULLISH" and dxy_trend == 1:
            score -= 2
            reasons.append("⚠️ DXY Correlation Mismatch (USD Strong)")
        elif signal_type == "BEARISH" and dxy_trend == -1:
            score -= 2
            reasons.append("⚠️ DXY Correlation Mismatch (USD Weak)")
        elif dxy_trend != 0:
            reasons.append(f"DXY Trend Confirmed ({'Bullish' if dxy_trend==1 else 'Bearish'})")

        # 4. Signal Generation
        if score >= 5 and signal_type != "NEUTRAL":
            # Suggest SL/TP based on ATR
            atr = (df_m15['high'] - df_m15['low']).rolling(14).mean().iloc[-1]
            sl = last_price - (atr * 2) if signal_type == "BULLISH" else last_price + (atr * 2)
            tp = last_price + (atr * 4) if signal_type == "BULLISH" else last_price - (atr * 4)
            
            signal = {
                'type': "BUY" if signal_type == "BULLISH" else "SELL",
                'entry': last_price,
                'sl': sl,
                'tp': tp,
                'score': score,
                'strategy': " + ".join(reasons),
                'time': datetime.now(self.timezone).strftime("%H:%M:%S"),
                'candle_time': last_candle_time,
                'news_active': news_active
            }
            log_thinking(f"Signal Generated: {signal['type']} with Score {score} (Candle: {last_candle_time})")
            return signal
            
        return None
