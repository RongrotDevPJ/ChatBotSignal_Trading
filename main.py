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
        'mode': 'Institutional Signal Provider',
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
                closed_trades, triggered_trades, expired_trades, be_trades = tracker.update(tick.bid, tick.ask)
                
                # 1. Handle Triggered (PENDING -> OPEN)
                for trade in triggered_trades:
                    notifier.send_status_update(trade, "⚡ ACTIVATED (Price Hit)")

                # 2. Handle Closed
                for trade in closed_trades:
                    price_diff = abs(trade['entry'] - trade['sl'])
                    exit_data = {
                        'result': trade['result'],
                        'pips': price_diff * 100, # Updated to 100x multiplier
                        'mae': trade['mae'],
                        'mfe': trade['mfe'],
                        'reason': trade['reason'],
                        'advice': trade['advice'],
                        'entry': trade['entry'],
                        'sl': trade['sl']
                    }
                    notifier.send_exit_alert(exit_data)

                # 3. Handle Expired
                for trade in expired_trades:
                    notifier.send_status_update(trade, "🚫 SIGNAL EXPIRED")

                # 4. Handle Break-Even Alert
                for trade in be_trades:
                    notifier.send_status_update(trade, "⚡ MOVE SL TO ENTRY (BE)")
            
            # B. Low-CPU SMC Analysis (Every 30s)
            if current_time - last_analysis_time >= 30:
                signal = analyzer.analyze()
                if signal:
                    candle_id = signal.get('candle_time')
                    if signal['score'] >= 6:
                        direction = "BUY" if "BUY" in signal['type'] else "SELL"
                        
                        # Handle same-candle LIMIT -> MARKET upgrade (preserved logic)
                        if signal['mode'] == "MARKET" and candle_id == last_candle_id:
                            existing_pending = next((
                                t for t in tracker.active_trades 
                                if t['candle_id'] == candle_id and t['status'] == 'PENDING' and direction in t['type']
                            ), None)
                            
                            if existing_pending:
                                existing_pending['status'] = 'OPEN'
                                existing_pending['mode'] = 'MARKET'
                                existing_pending['entry'] = signal['entry']
                                existing_pending['sl'] = signal['sl']
                                existing_pending['tp'] = signal['tp']
                                existing_pending['trigger_time'] = datetime.now().strftime("%H:%M:%S")
                                tracker._sync_to_file(existing_pending, is_new=False)
                                notifier.send_status_update(existing_pending, "⚡ UPGRADED TO MARKET (Sweep Detected)")
                                logger.info(f"[SYSTEM] Signal upgraded to MARKET for candle {candle_id} | MSG_ID: {existing_pending['message_id']}")
                                continue # We are done with this signal

                        # If not an upgrade, treat it as a new signal candidate
                        # Skip exact duplicate LIMIT signals (same candle, same direction)
                        if signal['mode'] == "LIMIT" and candle_id == last_candle_id:
                            # We already dispatched a limit for this candle in this direction, skip
                            logger.debug(f"[SYSTEM] Skipped duplicate {direction} LIMIT order for candle {candle_id}.")
                            continue

                        # Apply Smart Override Logic
                        active_trades = tracker.active_trades
                        max_signals = int(os.getenv("MAX_ACTIVE_SIGNALS", 2))
                        new_score = signal.get('score', 0)
                        
                        trade_to_override = None
                        can_dispatch = False
                        
                        same_dir_pending = [t for t in active_trades if t['status'] == 'PENDING' and direction in t['type']]
                        active_pending = [t for t in active_trades if t['status'] == 'PENDING']
                        
                        # Rule A: Same-Direction Override
                        if same_dir_pending:
                            target = same_dir_pending[0]
                            if new_score >= target.get('score', 0):
                                can_dispatch = True
                                trade_to_override = target
                            else:
                                logger.info(f"[SYSTEM] Skipped new {direction} signal. Existing PENDING has higher/equal score ({target.get('score')} >= {new_score}).")
                        
                        # Rule B: Capacity Override
                        elif len(active_trades) >= max_signals:
                            if active_pending:
                                lowest_pending = min(active_pending, key=lambda x: x.get('score', 0))
                                if new_score > lowest_pending.get('score', 0):
                                    can_dispatch = True
                                    trade_to_override = lowest_pending
                                else:
                                    logger.info(f"[SYSTEM] Skipped signal. At capacity and new score ({new_score}) is not strictly higher than lowest pending ({lowest_pending.get('score')}).")
                            else:
                                logger.info("[SYSTEM] Skipped signal. At capacity and all active trades are OPEN (untouchable).")
                                
                        # Standard Dispatch
                        else:
                            can_dispatch = True

                        if can_dispatch:
                            if trade_to_override:
                                # Execute the override
                                notifier.send_status_update(trade_to_override, "🚫 SIGNAL CANCELLED (Overridden)")
                                tracker.override_trade(trade_to_override, "Overridden by a higher-probability setup.")
                            
                            # Dispatch the new signal
                            msg_id = notifier.send_signal(signal)
                            tracker.add_trade(signal, message_id=msg_id, candle_id=candle_id)
                            last_candle_id = candle_id
                            logger.info(f"[SYSTEM] NEW Signal dispatched for candle {candle_id} ({signal['mode']} {direction}) | MSG_ID: {msg_id}")
                
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
