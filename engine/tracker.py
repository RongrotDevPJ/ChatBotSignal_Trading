import json
import os
import pytz
from datetime import datetime
from utils.logger import logger, log_thinking


class VirtualTracker:
    def __init__(self, history_file='logs/trade_history.json'):
        self.history_file = history_file
        self.active_trades = []
        self._bkk_tz = pytz.timezone("Asia/Bangkok")
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
                    self.active_trades = [t for t in data if t.get('status') in ['OPEN', 'PENDING']]
                    if self.active_trades:
                        logger.info(f"[SYSTEM] Recovered {len(self.active_trades)} virtual trades from history.")
            except Exception as e:
                logger.error(f"[SYSTEM] Failed to load history: {e}")

    # ── FIX #1: Kill Zone Trigger Guard ──────────────────────────
    def _is_in_killzone(self):
        """Returns True if current BKK time is within an active Kill Zone."""
        now = datetime.now(self._bkk_tz)
        t = now.strftime("%H:%M")
        return ("14:00" <= t < "17:30") or ("19:00" <= t < "22:30")

    def add_trade(self, signal_data, message_id=None, candle_id=None):
        """Adds a new trade. LIMIT orders start as PENDING."""
        is_limit = "LIMIT" in signal_data['type']
        trade = {
            'id': datetime.now().strftime("%Y%m%d%H%M%S"),
            'type': signal_data['type'],
            'mode': signal_data.get('mode', 'MARKET'),
            'entry': signal_data['entry'],
            'sl': signal_data['sl'],
            'tp1': signal_data.get('tp1'),
            'tp2': signal_data.get('tp2'),
            'sl_pips': signal_data.get('sl_pips', 0.0),
            'tp1_pips': signal_data.get('tp1_pips', 0.0),
            'tp2_pips': signal_data.get('tp2_pips', 0.0),
            'score': signal_data.get('score', 0),
            'open_time': signal_data['time'],
            'trigger_time': None,
            'mae': 0.0,
            'mfe': 0.0,
            'tp1_hit': False,
            'be_notified': False,
            'status': 'PENDING' if is_limit else 'OPEN',
            'message_id': message_id,
            'candle_id': candle_id,
            'session': signal_data.get('session', 'UNKNOWN'),
            'dxy_trend': signal_data.get('dxy_trend', 0),
            'htf_trend': signal_data.get('htf_trend', 0),
            'h1_bias': signal_data.get('h1_bias', 0),
            'confluence_count': signal_data.get('confluence_count', 0),
            'spread_at_entry': signal_data.get('spread_at_entry', 0),
            'time_in_trade_minutes': 0,
            # FIX #9 — ML-ready fields
            'candle_body_ratio': signal_data.get('candle_body_ratio', 0.0),
            'day_of_week': signal_data.get('day_of_week', -1),
            'atr_14_m15': signal_data.get('atr_14_m15', 0.0),
            'pivot_distance_pips': signal_data.get('pivot_distance_pips', 0.0),
        }
        self.active_trades.append(trade)
        self._sync_to_file(trade, is_new=True)
        log_thinking(f"Virtual Trade Registered: {trade['type']} @ {trade['entry']} ({trade['status']})")

    def update(self, current_bid, current_ask):
        """Updates prices. Triggers PENDING orders if hit and handles expiry/BE."""
        closed_trades = []
        triggered_trades = []
        expired_trades = []
        be_trades = []

        now = datetime.now()
        expiry_hours = int(os.getenv("SIGNAL_EXPIRY_HOURS", 24))
        stale_limit_hours = float(os.getenv("STALE_LIMIT_HOURS", 2.0))

        for trade in self.active_trades[:]:

            # ── 1. Handle Pending Order ──────────────────────────
            if trade['status'] == 'PENDING':
                try:
                    open_dt = datetime.strptime(trade['id'], "%Y%m%d%H%M%S")
                    age_hours = (now - open_dt).total_seconds() / 3600

                    # FIX #2 — Stale LIMIT Auto-Cancel (runs before 24h expiry)
                    if age_hours >= stale_limit_hours:
                        trade['status'] = 'CANCELLED'
                        trade['reason'] = f"LIMIT order stale (>{stale_limit_hours:.1f}h without trigger)"
                        trade['close_time'] = datetime.now().strftime("%H:%M:%S")
                        expired_trades.append(trade)
                        self._sync_to_file(trade, is_new=False)
                        self.active_trades.remove(trade)
                        log_thinking(f"[SYSTEM] PENDING {trade['id']} stale-cancelled after {age_hours:.1f}h.")
                        continue

                    # Standard 24h expiry
                    if age_hours >= expiry_hours:
                        trade['status'] = 'CANCELLED'
                        trade['reason'] = "Signal Expired"
                        trade['close_time'] = datetime.now().strftime("%H:%M:%S")
                        expired_trades.append(trade)
                        self._sync_to_file(trade, is_new=False)
                        self.active_trades.remove(trade)
                        continue
                except Exception:
                    pass

                # Price-trigger check
                triggered = False
                if "BUY LIMIT" in trade['type'] and current_ask <= trade['entry']:
                    triggered = True
                elif "SELL LIMIT" in trade['type'] and current_bid >= trade['entry']:
                    triggered = True

                if triggered:
                    # FIX #1 — Kill Zone Trigger Guard
                    if not self._is_in_killzone():
                        trade['status'] = 'CANCELLED'
                        trade['reason'] = "Triggered outside Kill Zone window"
                        trade['close_time'] = datetime.now().strftime("%H:%M:%S")
                        expired_trades.append(trade)
                        self._sync_to_file(trade, is_new=False)
                        self.active_trades.remove(trade)
                        log_thinking(f"[SYSTEM] PENDING {trade['id']} cancelled: triggered outside Kill Zone.")
                        continue

                    trade['status'] = 'OPEN'
                    trade['trigger_time'] = datetime.now().strftime("%H:%M:%S")
                    triggered_trades.append(trade)
                    self._sync_to_file(trade, is_new=False)
                    log_thinking(f"[SYSTEM] PENDING {trade['type']} Triggered @ {trade['entry']}")
                else:
                    continue  # Skip MAE/MFE for still-pending orders

            # ── 2. Handle Open Order Monitoring ─────────────────
            if trade['status'] == 'OPEN':
                if "BUY" in trade['type']:
                    floating_pips = (current_bid - trade['entry']) * 100
                    adverse = min(0, floating_pips)
                    favorable = max(0, floating_pips)
                    if current_bid <= trade['sl']:
                        self._close_trade(trade, "LOSS", current_bid, closed_trades)
                    else:
                        tp2 = trade.get('tp2', trade.get('tp'))
                        if tp2 and current_bid >= tp2:
                            self._close_trade(trade, "WIN", current_bid, closed_trades)
                else:  # SELL
                    floating_pips = (trade['entry'] - current_ask) * 100
                    adverse = min(0, floating_pips)
                    favorable = max(0, floating_pips)
                    if current_ask >= trade['sl']:
                        self._close_trade(trade, "LOSS", current_ask, closed_trades)
                    else:
                        tp2 = trade.get('tp2', trade.get('tp'))
                        if tp2 and current_ask <= tp2:
                            self._close_trade(trade, "WIN", current_ask, closed_trades)

                # TP1 / Break-Even Alert
                if not trade.get('tp1_hit', False) and not trade.get('be_notified', False):
                    tp1 = trade.get('tp1', trade.get('tp'))
                    if tp1:
                        if ("BUY" in trade['type'] and current_bid >= tp1) or \
                           ("SELL" in trade['type'] and current_ask <= tp1):
                            trade['tp1_hit'] = True
                            trade['be_notified'] = True
                            trade['sl'] = trade['entry']
                            be_trades.append(trade)
                            self._sync_to_file(trade, is_new=False)
                            log_thinking(f"[SYSTEM] TP1 HIT for {trade['id']}. SL moved to entry: {trade['entry']}")

                # Update MAE/MFE only for still-open trades
                if trade['status'] == 'OPEN':
                    trade['mae'] = max(trade['mae'], abs(adverse))
                    trade['mfe'] = max(trade['mfe'], favorable)

        for t in closed_trades:
            if t in self.active_trades:
                self.active_trades.remove(t)

        return closed_trades, triggered_trades, expired_trades, be_trades

    def _close_trade(self, trade, result, exit_price, closed_list):
        if result == "LOSS" and trade.get('be_notified', False):
            result = "BREAK-EVEN"
        trade['status'] = 'CLOSED'
        trade['result'] = result
        trade['exit_price'] = exit_price
        trade['close_time'] = datetime.now().strftime("%H:%M:%S")
        try:
            open_dt = datetime.strptime(trade['id'], "%Y%m%d%H%M%S")
            trade['time_in_trade_minutes'] = int((datetime.now() - open_dt).total_seconds() / 60)
        except Exception:
            trade['time_in_trade_minutes'] = 0
        trade['reason'] = self._analyze_exit(trade)
        trade['advice'] = self._get_advice(trade)
        self._sync_to_file(trade, is_new=False)
        closed_list.append(trade)
        log_thinking(f"Virtual Trade Closed: {result} with MAE: {trade['mae']:.1f} pips")

    def _analyze_exit(self, trade):
        if trade['result'] == "BREAK-EVEN":
            return "Price reached break-even threshold but reversed to entry."
        if trade['result'] == "LOSS":
            if trade['mfe'] > 10:
                return "Price was in profit but reversed. Possibly Liquidity Grab or News."
            return "Stop Loss triggered. Structure was likely invalidated."
        return "Target reached successfully."

    def _get_advice(self, trade):
        if trade['result'] == "BREAK-EVEN":
            return "Good capital preservation. BE protected against the reversal."
        if trade['result'] == "LOSS":
            return "Consider trailing stop or wider SL based on recent OB."
        return "Strategy working as intended."

    def cancel_all_pending(self):
        """Cancels all currently pending trades in history."""
        for trade in self.active_trades[:]:
            if trade['status'] == 'PENDING':
                trade['status'] = 'CANCELLED'
                trade['close_time'] = datetime.now().strftime("%H:%M:%S")
                self._sync_to_file(trade, is_new=False)
                self.active_trades.remove(trade)
                log_thinking(f"[SYSTEM] Virtual PENDING order {trade['id']} has been CANCELLED.")

    def override_trade(self, trade, reason):
        """Cancels a specific pending trade with a given reason."""
        trade['status'] = 'CANCELLED'
        trade['reason'] = reason
        trade['close_time'] = datetime.now().strftime("%H:%M:%S")
        self._sync_to_file(trade, is_new=False)
        if trade in self.active_trades:
            self.active_trades.remove(trade)
        log_thinking(f"[SYSTEM] Virtual PENDING order {trade['id']} has been CANCELLED (Override).")

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
