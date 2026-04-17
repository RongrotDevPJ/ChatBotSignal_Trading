import MetaTrader5 as mt5
import time
import os
from dotenv import load_dotenv
from engine.analyzer import SMCAnalyzer
from engine.tracker import VirtualTracker
from utils.notifier import TelegramNotifier
from utils.logger import logger, log_thinking

# Load environment variables
load_dotenv()

def main():
    logger.info("[SYSTEM] Initializing XAUUSD SMC+ICT Professional Signal Bot...")
    
    # 1. MT5 Connectivity
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
    
    last_candle_id = None 
    last_heartbeat_time = 0

    try:
        while True:
            # 0. Heartbeat & Self-Healing (Resilience)
            current_time = time.time()
            if current_time - last_heartbeat_time > 10:
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

            # A. Get Live Prices for Tracker
            tick = mt5.symbol_info_tick(gold_symbol)
            if tick:
                closed_trades = tracker.update(tick.bid, tick.ask)
                for trade in closed_trades:
                    # SL distance for advice logic
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
            
            # B. Periodic Analysis & De-duplication
            signal = analyzer.analyze()
            if signal:
                candle_id = signal.get('candle_time')
                if candle_id != last_candle_id:
                    if signal['score'] >= 7:
                        notifier.send_signal(signal)
                        tracker.track(signal)
                        last_candle_id = candle_id
                        logger.info(f"[SYSTEM] Signal dispatched for candle {candle_id}")
                else:
                    pass

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
