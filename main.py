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
    
    last_analysis_time = 0
    analysis_interval = 60 # Check for new signals every 60 seconds (or on candle close)

    try:
        while True:
            # A. Get Live Prices for Tracker
            tick = mt5.symbol_info_tick(gold_symbol)
            if tick:
                closed_trades = tracker.update(tick.bid, tick.ask)
                for trade in closed_trades:
                    # Notify about trade outcome
                    exit_data = {
                        'result': trade['result'],
                        'pips': (trade['exit_price'] - trade['entry']) * 10 if trade['type'] == "BUY" else (trade['entry'] - trade['exit_price']) * 10,
                        'mae': trade['mae'],
                        'mfe': trade['mfe'],
                        'reason': trade['reason'],
                        'advice': trade['advice']
                    }
                    notifier.send_exit_alert(exit_data)
            
            # B. Periodic Analysis for New Signals
            current_time = time.time()
            if current_time - last_analysis_time > analysis_interval:
                signal = analyzer.analyze()
                if signal:
                    # Prevent duplicate signals (basic check - could be improved with state)
                    # For now, we only notify if score is high
                    if signal['score'] >= 7: # High fidelity threshold
                        notifier.send_signal(signal)
                        tracker.add_trade(signal)
                
                last_analysis_time = current_time

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
