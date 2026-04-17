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
        if not os.path.exists(self.history_file):
            with open(self.history_file, 'w') as f:
                json.dump([], f)
        
    def add_trade(self, signal_data):
        """Adds a new virtual trade from a signal"""
        trade = {
            'id': datetime.now().strftime("%Y%m%d%H%M%S"),
            'type': signal_data['type'],
            'entry': signal_data['entry'],
            'sl': signal_data['sl'],
            'tp': signal_data['tp'],
            'open_time': signal_data['time'],
            'mae': 0.0, # Max Adverse Excursion (pips)
            'mfe': 0.0, # Max Favorable Excursion (pips)
            'status': 'OPEN'
        }
        self.active_trades.append(trade)
        log_thinking(f"Virtual Trade Started: {trade['type']} @ {trade['entry']}")

    def update(self, current_bid, current_ask):
        """Updates active trades with current market prices"""
        closed_trades = []
        
        for trade in self.active_trades:
            # For BUY: Adverse is Bid falling below entry. Favorable is Bid rising above entry.
            # For SELL: Adverse is Ask rising above entry. Favorable is Ask falling below entry.
            
            if trade['type'] == "BUY":
                floating_pips = (current_bid - trade['entry']) * 10 # Assuming Gold 2 decimals (10 points = 1 pip)
                # Note: MT5 Gold usually has 2 decimals, so 0.01 = 1 point. 0.10 = 1 pip.
                # Correcting: Gold 1900.00 -> 1900.01 is 1 point. 10 points = 1 pip usually.
                adverse = min(0, floating_pips)
                favorable = max(0, floating_pips)
                
                # Check Exit
                if current_bid <= trade['sl']:
                    self._close_trade(trade, "LOSS", current_bid, closed_trades)
                elif current_bid >= trade['tp']:
                    self._close_trade(trade, "WIN", current_bid, closed_trades)
                    
            else: # SELL
                floating_pips = (trade['entry'] - current_ask) * 10
                adverse = min(0, (trade['entry'] - current_ask) * 10) # Ask rising makes floating pips more negative
                # Wait, logic check: 
                # BUY: current_bid - entry. If bid=10, entry=12, pips=-2. MAE should be 2.
                # SELL: entry - current_ask. If ask=14, entry=12, pips=-2. MAE should be 2.
                
                favorable = max(0, floating_pips)
                
                # Check Exit
                if current_ask >= trade['sl']:
                    self._close_trade(trade, "LOSS", current_ask, closed_trades)
                elif current_ask <= trade['tp']:
                    self._close_trade(trade, "WIN", current_ask, closed_trades)

            # Update MAE/MFE (Stored as positive pips for deviation)
            trade['mae'] = max(trade['mae'], abs(min(0, floating_pips)))
            trade['mfe'] = max(trade['mfe'], favorable)

        # Remove closed trades
        for t in closed_trades:
            if t in self.active_trades:
                self.active_trades.remove(t)
                
        return closed_trades

    def _close_trade(self, trade, result, exit_price, closed_list):
        trade['status'] = 'CLOSED'
        trade['result'] = result
        trade['exit_price'] = exit_price
        trade['close_time'] = datetime.now().strftime("%H:%M:%S")
        
        # Simple Analysis
        trade['reason'] = self._analyze_exit(trade)
        trade['advice'] = self._get_advice(trade)
        
        # Persistence
        self._save_to_history(trade)
        closed_list.append(trade)
        log_thinking(f"Virtual Trade Closed: {result} with MAE: {trade['mae']:.1f}")

    def _analyze_exit(self, trade):
        if trade['result'] == "LOSS" and trade['mfe'] > 10: # If it was up 10 pips before losing
            return "Price was in profit but reversed. Possibly Liquidity Grab or News."
        if trade['result'] == "LOSS" and trade['mae'] > 0:
            return "Direct hit to SL. Structure was likely invalidated."
        return "Target reached successfully."

    def _get_advice(self, trade):
        if trade['result'] == "LOSS":
            return "Consider trailing stop or wider SL based on recent OB."
        return "Strategy working as intended."

    def _save_to_history(self, trade):
        try:
            with open(self.history_file, 'r+') as f:
                data = json.load(f)
                data.append(trade)
                f.seek(0)
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save trade history: {e}")
