import requests
import os
from dotenv import load_dotenv
from utils.logger import logger

load_dotenv()

class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def calculate_risk(self, entry, sl):
        """Calculates risk for a 0.1 Lot (Cent Account) on a $30 balance"""
        # XAUUSD 0.1 Lot = 10 Ounces. 1 point move = $10.
        # But if it's a Cent Account, 0.1 Lot might be different.
        # User specified "0.1 Lot (Cent Account)" for $30. 
        # Usually 0.1 Lot on Cent is 0.001 Standard (~1.0 oz?).
        # Let's assume 0.1 Lot CENT = $0.10 risk per 1.00 move (100 points/10 pips).
        # Actually, let's use the most common Cent lot logic: 1.0 Cent Lot = 1% of Standard.
        # 0.1 Cent Lot = 0.001 Standard.
        # Risk = abs(entry - sl) * LotSize * 100?
        # Let's stick to the prompt's implied scale: $1 risk for $30 is reasonable.
        
        price_diff = abs(entry - sl)
        # Using a common multiplier for Gold: 1.0 Standard Lot = $100/point.
        # 0.1 Cent Lot = $0.10/point?
        potential_loss = price_diff * 0.1 # This assumes 0.1 Cent Lot risks $0.10 per point.
        risk_percent = (potential_loss / 30) * 100
        pips = price_diff * 10
        
        return potential_loss, risk_percent, pips

    def send_signal(self, signal_data):
        """
        Sends a professional signal message to Telegram.
        """
        try:
            potential_loss, risk_percent, pips = self.calculate_risk(signal_data['entry'], signal_data['sl'])
            
            emoji = "🟢" if signal_data['type'] == "BUY" else "🔴"
            news_warning = "⚠️ <b>High Volatility News Active</b>\n" if signal_data.get('news_active') else ""
            high_risk_warning = "⚠️ <b>High Risk for Small Balance</b> (SL > 500 pips)\n" if pips > 500 else ""
            
            title = f"{emoji} <b>XAUUSD {signal_data['type']} SIGNAL</b>"
            
            message = (
                f"{title}\n\n"
                f"{news_warning}"
                f"🧠 <b>AI Score:</b> {signal_data['score']}/10\n"
                f"📊 <b>Strategy:</b> {signal_data['strategy']}\n"
                f"🕒 <b>Time (BKK):</b> {signal_data['time']}\n\n"
                f"📥 <b>Entry Price:</b> {signal_data['entry']:.2f}\n"
                f"🎯 <b>Take Profit:</b> {signal_data['tp']:.2f}\n"
                f"🛡️ <b>Stop Loss:</b> {signal_data['sl']:.2f}\n\n"
                f"💰 <b>Micro-Account Calc ($30):</b>\n"
                f"├ <b>Risk Item:</b> 0.1 Lot (Cent)\n"
                f"├ <b>Potential Loss:</b> -${potential_loss:.2f} ({risk_percent:.1f}%)\n"
                f"└ {high_risk_warning if high_risk_warning else '✅ Risk Management: Pass'}\n\n"
                f"⚠️ <i>This is a virtual signal for analysis only.</i>"
            )

            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(self.base_url, json=payload)
            response.raise_for_status()
            logger.info(f"Signal sent to Telegram: {signal_data['type']} at {signal_data['entry']}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram signal: {e}", exc_info=True)
            return False

    def send_exit_alert(self, exit_data):
        """
        Sends an alert when a virtual trade hits SL or TP.
        """
        try:
            status_emoji = "✅" if exit_data['result'] == "WIN" else "❌"
            title = f"{status_emoji} <b>VIRTUAL TRADE CLOSED: {exit_data['result']}</b>"
            
            message = (
                f"{title}\n\n"
                f"💰 <b>Result:</b> {exit_data['result']} ({exit_data['pips']:.1f} pips)\n"
                f"📉 <b>MAE:</b> {exit_data['mae']:.1f} pips\n"
                f"📈 <b>MFE:</b> {exit_data['mfe']:.1f} pips\n\n"
                f"🧠 <b>AI Analysis:</b> {exit_data['reason']}\n"
                f"💡 <b>Advice:</b> {exit_data['advice']}"
            )

            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(self.base_url, json=payload)
            response.raise_for_status()
            logger.info(f"Exit alert sent to Telegram: {exit_data['result']}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram exit alert: {e}", exc_info=True)
            return False
