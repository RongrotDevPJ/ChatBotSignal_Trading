import json
import os
import requests
from datetime import datetime, timedelta
from utils.logger import logger

class WeeklyReporter:
    def __init__(self, history_file='logs/trade_history.json'):
        self.history_file = history_file
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def generate_and_send(self):
        if not os.path.exists(self.history_file):
            logger.warning("[REPORTER] No trade history found to report.")
            return

        try:
            with open(self.history_file, 'r') as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"[REPORTER] Failed to read history: {e}")
            return

        now = datetime.now()
        seven_days_ago = now - timedelta(days=7)

        # Filter for trades closed in the last 7 days
        recent_closed_trades = []
        for t in data:
            if t.get('status') == 'CLOSED':
                try:
                    # 'id' is format '%Y%m%d%H%M%S'
                    trade_time = datetime.strptime(t['id'], "%Y%m%d%H%M%S")
                    if trade_time >= seven_days_ago:
                        recent_closed_trades.append(t)
                except Exception as e:
                    logger.debug(f"[REPORTER] Could not parse trade ID {t.get('id')} as datetime: {e}")

        total_trades = len(recent_closed_trades)
        if total_trades == 0:
            logger.info("[REPORTER] No closed trades in the past 7 days.")
            self._send("📊 <b>WEEKLY PERFORMANCE REPORT</b> 📊\n\nNo trades were closed this week.")
            return

        wins = 0
        losses = 0
        bes = 0
        net_pips = 0.0

        session_stats = {
            'ASIAN': {'pips': 0.0, 'wins': 0, 'total': 0},
            'LONDON': {'pips': 0.0, 'wins': 0, 'total': 0},
            'NY': {'pips': 0.0, 'wins': 0, 'total': 0},
            'UNKNOWN': {'pips': 0.0, 'wins': 0, 'total': 0}
        }

        for t in recent_closed_trades:
            result = t.get('result', '')
            trade_type = t.get('type', '')
            session = t.get('session', 'UNKNOWN')
            
            pips = 0.0
            if result == 'WIN':
                wins += 1
                if 'BUY' in trade_type:
                    pips = (t['exit_price'] - t['entry']) * 100
                elif 'SELL' in trade_type:
                    pips = (t['entry'] - t['exit_price']) * 100
            elif result == 'LOSS':
                losses += 1
                if 'BUY' in trade_type:
                    pips = (t['exit_price'] - t['entry']) * 100
                elif 'SELL' in trade_type:
                    pips = (t['entry'] - t['exit_price']) * 100
            elif result == 'BREAK-EVEN':
                bes += 1
                pips = 0.0
            
            net_pips += pips
            
            if session not in session_stats:
                session_stats[session] = {'pips': 0.0, 'wins': 0, 'total': 0}
                
            session_stats[session]['pips'] += pips
            session_stats[session]['total'] += 1
            if result == 'WIN':
                session_stats[session]['wins'] += 1

        win_rate = (wins / total_trades) * 100

        # Determine Best Session
        best_session_name = "N/A"
        best_session_pips = float('-inf')
        best_session_winrate = -1

        for session_name, stats in session_stats.items():
            if stats['total'] > 0 and session_name != 'UNKNOWN':
                s_winrate = (stats['wins'] / stats['total']) * 100
                s_pips = stats['pips']
                
                if s_pips > best_session_pips:
                    best_session_pips = s_pips
                    best_session_winrate = s_winrate
                    best_session_name = session_name
                elif s_pips == best_session_pips:
                    if s_winrate > best_session_winrate:
                        best_session_winrate = s_winrate
                        best_session_name = session_name

        if best_session_name == "N/A":
            best_session_name = "NONE"
        else:
            best_session_name = best_session_name.upper()

        start_date_str = seven_days_ago.strftime('%Y-%m-%d')
        end_date_str = now.strftime('%Y-%m-%d')

        msg = (
            f"📊 <b>WEEKLY PERFORMANCE REPORT</b> 📊\n"
            f"🗓️ {start_date_str} to {end_date_str}\n\n"
            f"📈 <b>Total Trades:</b> {total_trades}\n"
            f"✅ <b>Wins:</b> {wins} | ❌ <b>Losses:</b> {losses} | 🛡️ <b>BE:</b> {bes}\n"
            f"🏆 <b>Win Rate:</b> {win_rate:.1f}%\n"
            f"💰 <b>Net Pips:</b> {net_pips:+.1f} pips\n\n"
            f"🌟 <b>Best Session:</b> {best_session_name}\n"
            f"🤖 <b>Strategy Context:</b> Institutional Signal Provider"
        )

        self._send(msg)
        logger.info("[SYSTEM] Weekly report generated and sent successfully.")

    def _send(self, text):
        try:
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            requests.post(self.base_url, json=payload)
        except Exception as e:
            logger.error(f"[SYSTEM] Telegram reporter error: {e}")
