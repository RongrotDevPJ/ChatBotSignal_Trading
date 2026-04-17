import MetaTrader5 as mt5
import time
import os
from dotenv import load_dotenv
from engine.analyzer import SMCAnalyzer
from engine.tracker import VirtualTracker
from utils.notifier import TelegramNotifier
from utils.logger import logger, log_thinking
import pytz
from datetime import datetime
from utils.reporter import WeeklyReporter

# Load environment variables
load_dotenv()

def main():
    logger.info("[SYSTEM] Initializing XAUUSD VPS Production Version...")
    
    # 1. MT5 Connectivity (Manual Terminal Login)
    if not mt5.initialize():
        logger.error(f"[SYSTEM] Failed to initialize MT5: {mt5.last_error()}")
        return

    # 2. Symbol Setup
    analyzer = SMCAnalyzer("XAUUSD")
    gold_symbol = analyzer.symbol
    
    if not gold_symbol:
        logger.error("[SYSTEM] Could not find any Gold symbol (XAUUSD/GOLD) in your MT5 Market Watch.")
        mt5.shutdown()
        return
    
    logger.info(f"[SYSTEM] Bot connected! Using Symbol: {gold_symbol}")

    # 3. Initialize Components
    tracker = VirtualTracker()
    notifier = TelegramNotifier()
    reporter = WeeklyReporter()
    last_reported_week = -1
    bkk_tz = pytz.timezone("Asia/Bangkok")
    
    # 4. Startup Notification
    startup_ctx = {
        'balance_msg': '$30 Micro-Calc Active',
        'frequency': '30s SMC Pulse'
    }
    notifier.send_startup_message(startup_ctx)
    logger.info("[SYSTEM] Startup notification sent to Telegram.")

    last_analysis_time = 0
    last_heartbeat_time = 0
    last_candle_id = None 

    try:
        while True:
            current_time = time.time()

            # Heartbeat & Self-Healing (Check every 10s)
            if current_time - last_heartbeat_time >= 10:
                terminal_info = mt5.terminal_info()
                if not terminal_info or not terminal_info.connected:
                    logger.warning("[SYSTEM] Connection lost! Attempting self-healing...")
                    mt5.shutdown()
                    time.sleep(5)
                    if mt5.initialize():
                        logger.info("[SYSTEM] MT5 successfully re-initialized.")
                    else:
                        logger.error("[SYSTEM] Auto-initialization failed.")
                last_heartbeat_time = current_time

            # A. High-Precision Tracker (Every 1s)
            tick = mt5.symbol_info_tick(gold_symbol)
            if tick:
                closed_trades = tracker.update(tick.bid, tick.ask)
                for trade in closed_trades:
                    price_diff = abs(trade['entry'] - trade['sl'])
                    exit_data = {
                        'result': trade['result'],
                        'pips': price_diff * 10,
                        'mae': trade['mae'],
                        'mfe': trade['mfe'],
                        'reason': trade['reason'],
                        'advice': trade['advice'],
                        'entry': trade['entry'],
                        'sl': trade['sl']
                    }
                    notifier.send_exit_alert(exit_data)
            
            # B. Low-CPU SMC Analysis (Every 30s)
            if current_time - last_analysis_time >= 30:
                signal = analyzer.analyze()
                if signal:
                    candle_id = signal.get('candle_time')
                    if signal['score'] >= 6:
                        direction = "BUY" if "BUY" in signal['type'] else "SELL"
                        
                        # Find existing trades with same direction
                        active_same_direction = [
                            t for t in tracker.active_trades 
                            if direction in t['type'] and t['status'] in ['PENDING', 'OPEN']
                        ]

                        is_new_signal = False

                        # Scenario 1: New signal is MARKET
                        if signal['mode'] == "MARKET":
                            # Cancel ALL existing PENDING orders on Market execution
                            tracker.cancel_all_pending()
                            is_new_signal = True

                        # Scenario 2: New signal is LIMIT
                        elif signal['mode'] == "LIMIT":
                            # Only execute if no active trades in this direction
                            if not active_same_direction:
                                is_new_signal = True
                            else:
                                if candle_id != last_candle_id:
                                    logger.debug(f"[SYSTEM] Skipped duplicate {direction} LIMIT order for candle {candle_id}. Trade already active.")

                        # Dispatch if logic clears
                        if is_new_signal and (candle_id != last_candle_id or signal['mode'] == "MARKET"):
                            notifier.send_signal(signal)
                            tracker.add_trade(signal)
                            last_candle_id = candle_id
                            logger.info(f"[SYSTEM] Signal dispatched for candle {candle_id} ({signal['mode']} {direction})")
                
                last_analysis_time = current_time

            # C. Zero-CPU Weekly Reporter (Friday 23:50 BKK Time)
            bkk_now = datetime.now(bkk_tz)
            current_week = bkk_now.isocalendar()[1]
            
            # Check if it's Friday (4) and 23:50+
            if bkk_now.weekday() == 4 and bkk_now.hour == 23 and bkk_now.minute >= 50:
                if current_week != last_reported_week:
                    logger.info("[SYSTEM] Triggering Weekly Summary Report...")
                    reporter.generate_and_send()
                    last_reported_week = current_week

            # 1s Pulse to keep Tracker precise and CPU low
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("[SYSTEM] Bot stopped by user.")
    except Exception as e:
        logger.error(f"[SYSTEM] Main loop error: {e}", exc_info=True)
    finally:
        mt5.shutdown()
        logger.info("[SYSTEM] MT5 connection closed. Goodbye.")

if __name__ == "__main__":
    main()
