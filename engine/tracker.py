import json
import os
from datetime import datetime
from utils.logger import logger, log_thinking

class VirtualTracker:
    def __init__(self, history_file='logs/trade_history.json'):
        self.history_file = history_file
        self.active_trades = []
        self._load_history()

    def _load_history(self):
        """Loads OPEN or PENDING trades from history on startup"""
        if not os.path.exists(self.history_file):
            with open(self.history_file, 'w') as f:
                json.dump([], f)
        else:
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    # Pull both OPEN and PENDING back to memory
                    self.active_trades = [t for t in data if t.get('status') in ['OPEN', 'PENDING']]
                    if self.active_trades:
                        logger.info(f"[SYSTEM] Recovered {len(self.active_trades)} virtual trades from history.")
            except Exception as e:
                logger.error(f"[SYSTEM] Failed to load history: {e}")
        
    def add_trade(self, signal_data):
        """Adds a new trade. LIMIT orders start as PENDING."""
        is_limit = "LIMIT" in signal_data['type']
        
        trade = {
            'id': datetime.now().strftime("%Y%m%d%H%M%S"),
            'type': signal_data['type'],
            'mode': signal_data.get('mode', 'MARKET'),
            'entry': signal_data['entry'],
            'sl': signal_data['sl'],
            'tp': signal_data['tp'],
            'open_time': signal_data['time'],
            'trigger_time': None,
            'mae': 0.0,
            'mfe': 0.0,
            'status': 'PENDING' if is_limit else 'OPEN'
        }
        
        self.active_trades.append(trade)
        self._sync_to_file(trade, is_new=True)
        log_thinking(f"Virtual Trade Registered: {trade['type']} @ {trade['entry']} ({trade['status']})")

    def update(self, current_bid, current_ask):
        """Updates prices. Triggers PENDING orders if hit."""
        closed_trades = []
        
        for trade in self.active_trades:
            # 1. Handle Pending Order Activation
            if trade['status'] == 'PENDING':
                triggered = False
                if "BUY LIMIT" in trade['type'] and current_ask <= trade['entry']:
                    triggered = True
                elif "SELL LIMIT" in trade['type'] and current_bid >= trade['entry']:
                    triggered = True
                
                if triggered:
                    trade['status'] = 'OPEN'
                    trade['trigger_time'] = datetime.now().strftime("%H:%M:%S")
                    self._sync_to_file(trade, is_new=False)
                    log_thinking(f"[SYSTEM] PENDING {trade['type']} Triggered @ {trade['entry']}")
                else:
                    continue # Skip MAE/MFE tracking for pending

            # 2. Handle Open Order Monitoring
            if trade['status'] == 'OPEN':
                if "BUY" in trade['type']:
                    floating_pips = (current_bid - trade['entry']) * 10 
                    adverse = min(0, floating_pips)
                    favorable = max(0, floating_pips)
                    
                    if current_bid <= trade['sl']:
                        self._close_trade(trade, "LOSS", current_bid, closed_trades)
                    elif current_bid >= trade['tp']:
                        self._close_trade(trade, "WIN", current_bid, closed_trades)
                        
                else: # SELL
                    floating_pips = (trade['entry'] - current_ask) * 10
                    adverse = min(0, floating_pips) 
                    favorable = max(0, floating_pips)
                    
                    if current_ask >= trade['sl']:
                        self._close_trade(trade, "LOSS", current_ask, closed_trades)
                    elif current_ask <= trade['tp']:
                        self._close_trade(trade, "WIN", current_ask, closed_trades)

                # Update MAE/MFE 
                trade['mae'] = max(trade['mae'], abs(adverse))
                trade['mfe'] = max(trade['mfe'], favorable)

        for t in closed_trades:
            if t in self.active_trades:
                self.active_trades.remove(t)
                
        return closed_trades

    def _close_trade(self, trade, result, exit_price, closed_list):
        trade['status'] = 'CLOSED'
        trade['result'] = result
        trade['exit_price'] = exit_price
        trade['close_time'] = datetime.now().strftime("%H:%M:%S")
        
        trade['reason'] = self._analyze_exit(trade)
        trade['advice'] = self._get_advice(trade)
        
        self._sync_to_file(trade, is_new=False)
        closed_list.append(trade)
        log_thinking(f"Virtual Trade Closed: {result} with MAE: {trade['mae']:.1f} pips")

    def _analyze_exit(self, trade):
        if trade['result'] == "LOSS" and trade['mfe'] > 10:
            return "Price was in profit but reversed. Possibly Liquidity Grab or News."
        if trade['result'] == "LOSS" and trade['mae'] > 0:
            return "Direct hit to SL. Structure was likely invalidated."
        return "Target reached successfully."

    def _get_advice(self, trade):
        if trade['result'] == "LOSS":
            return "Consider trailing stop or wider SL based on recent OB."
        return "Strategy working as intended."

    def cancel_all_pending(self):
        """Cancels all currently pending trades in history."""
        for trade in self.active_trades[:]: # Use slice to allow removal if needed
            if trade['status'] == 'PENDING':
                trade['status'] = 'CANCELLED'
                trade['close_time'] = datetime.now().strftime("%H:%M:%S")
                self._sync_to_file(trade, is_new=False)
                self.active_trades.remove(trade)
                log_thinking(f"[SYSTEM] Virtual PENDING order {trade['id']} has been CANCELLED.")

    def _sync_to_file(self, trade, is_new=False):
        try:
            with open(self.history_file, 'r') as f:
                data = json.load(f)
            
            if is_new:
                data.append(trade)
            else:
                for i, t in enumerate(data):
                    if t['id'] == trade['id']:
                        data[i] = trade
                        break
                        
            with open(self.history_file, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to sync trade history: {e}")
