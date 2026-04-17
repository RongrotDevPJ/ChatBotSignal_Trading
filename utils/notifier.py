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

    def send_signal(self, signal_data):
        """
        Sends a professional signal message to Telegram.
        signal_data: dict containing type, price, sl, tp, score, etc.
        """
        try:
            emoji = "🟢" if signal_data['type'] == "BUY" else "🔴"
            title = f"{emoji} <b>XAUUSD {signal_data['type']} SIGNAL</b>"
            
            message = (
                f"{title}\n\n"
                f"🧠 <b>AI Score:</b> {signal_data['score']}/10\n"
                f"📊 <b>Strategy:</b> {signal_data['strategy']}\n"
                f"🕒 <b>Time (BKK):</b> {signal_data['time']}\n\n"
                f"📥 <b>Entry Price:</b> {signal_data['entry']:.2f}\n"
                f"🎯 <b>Take Profit:</b> {signal_data['tp']:.2f}\n"
                f"🛡️ <b>Stop Loss:</b> {signal_data['sl']:.2f}\n\n"
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
