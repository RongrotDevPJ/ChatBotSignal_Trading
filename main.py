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

def detect_gold_symbol():
    """Tries to find the Gold symbol in MT5 Market Watch"""
    symbols = mt5.symbols_get()
    if not symbols:
        return None
    
    # Common Gold tickers
    gold_keywords = ["XAUUSD", "GOLD"]
    for sym in symbols:
        for key in gold_keywords:
            if key in sym.name.upper():
                # Check if visible/selectable
                if mt5.symbol_select(sym.name, True):
                    return sym.name
    return None

def main():
    logger.info("Initializing XAUUSD SMC+ICT Professional Signal Bot...")
    
    # 1. MT5 Connectivity
    if not mt5.initialize():
        logger.error(f"Failed to initialize MT5: {mt5.last_error()}")
        return

    # 2. Symbol Auto-detection
    gold_symbol = detect_gold_symbol()
    if not gold_symbol:
        logger.error("Could not find any Gold symbol (XAUUSD/GOLD) in your MT5 Market Watch.")
        mt5.shutdown()
        return
    
    logger.info(f"Bot connected! Using Symbol: {gold_symbol}")
    log_thinking(f"Found Gold symbol: {gold_symbol}")

    # 3. Initialize Components
    analyzer = SMCAnalyzer(gold_symbol)
    tracker = VirtualTracker()
    notifier = TelegramNotifier()
    
    last_candle_id = None # To prevent duplicate signals on the same candle
    last_heartbeat_time = 0

    try:
        while True:
            # 0. Heartbeat & Self-Healing
            current_time = time.time()
            if current_time - last_heartbeat_time > 10: # Check connection every 10s
                terminal_info = mt5.terminal_info()
                if not terminal_info or not terminal_info.connected:
                    logger.warning("MT5 Connection lost! Attempting self-healing...")
                    mt5.shutdown()
                    time.sleep(5)
                    if mt5.initialize():
                        logger.info("MT5 successfully re-initialized.")
                    else:
                        logger.error("Auto-initialization failed.")
                last_heartbeat_time = current_time

            # A. Get Live Prices for Tracker
            tick = mt5.symbol_info_tick(gold_symbol)
            if tick:
                closed_trades = tracker.update(tick.bid, tick.ask)
                for trade in closed_trades:
                    # Risk Calculation for 0.1 Lot on a $30 Account
                    # XAUUSD 0.1 Lot = 10 Ounces. 1 point move = $10.
                    # Price difference in points: abs(entry - exit)
                    # Loss = pips * 0.1 * lot_multiplier? No, let's use the formula:
                    # Risk = abs(entry - sl) * 0.1 * 100? 
                    # Actually, if price goes from 2000 to 1999, loss for 0.1 lot is $10.
                    # Lot size 0.1 is 10 units. 1 unit move = $10.
                    
                    exit_data = {
                        'result': trade['result'],
                        'pips': (trade['exit_price'] - trade['entry']) * 10 if trade['type'] == "BUY" else (trade['entry'] - trade['exit_price']) * 10,
                        'mae': trade['mae'],
                        'mfe': trade['mfe'],
                        'reason': trade['reason'],
                        'advice': trade['advice'],
                        'entry': trade['entry'],
                        'sl': trade['sl']
                    }
                    notifier.send_exit_alert(exit_data)
            
            # B. Periodic Analysis for New Signals
            signal = analyzer.analyze()
            if signal:
                candle_id = signal.get('candle_time')
                if candle_id != last_candle_id:
                    if signal['score'] >= 7: # High fidelity threshold
                        notifier.send_signal(signal)
                        tracker.add_trade(signal)
                        last_candle_id = candle_id
                        log_thinking(f"Signal sent for candle {candle_id}")
                else:
                    # Already sent for this candle
                    pass

            # Small sleep to prevent high CPU usage
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Main loop error: {e}", exc_info=True)
    finally:
        mt5.shutdown()
        logger.info("MT5 connection closed. Goodbye.")

if __name__ == "__main__":
    main()
