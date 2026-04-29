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

    def send_startup_message(self, context):
        """Sends a mandatory startup verification message"""
        msg = (
            f"🚀 <b>Bot Started Successfully!</b>\n\n"
            f"● <b>Status:</b> Online\n"
            f"● <b>Execution Mode:</b> Dual (Market/Limit)\n"
            f"● <b>Strategy Context:</b> {context.get('mode', 'Institutional Signal Provider')}\n"
            f"● <b>Structure Loop:</b> {context['frequency']}\n\n"
            f"<i>Listening for XAUUSD SMC/ICT Signals...</i>"
        )
        return self._send(msg)

    def send_signal(self, sig):
        try:
            # Dual Mode UI
            is_limit = sig.get('mode') == "LIMIT"
            mode_emoji = "⏳" if is_limit else "⚡"
            mode_label = "PENDING ORDER" if is_limit else "MARKET EXECUTION"
            
            emoji = "🟢" if "BUY" in sig['type'] else "🔴"
            news_warn = "⚠️ <b>High Volatility News</b>\n" if sig.get('news_active') else ""
            
            msg = (
                f"{emoji} <b>XAUUSD {sig['type']} SIGNAL</b>\n"
                f"{mode_emoji} <b>TYPE: {mode_label}</b>\n\n"
                f"{news_warn}"
                f"🧠 <b>AI Score:</b> {sig['score']}/10\n"
                f"📊 <b>Strategy:</b> {sig['strategy']}\n"
                f"🕒 <b>Time (BKK):</b> {sig['time']}\n\n"
                f"📥 <b>Entry Price:</b> <code>{sig['entry']:.2f}</code>\n"
                f"🛡️ <b>Stop Loss:</b> <code>{sig['sl']:.2f}</code> [-{sig['sl_pips']:.1f} pips]\n"
                f"🎯 <b>TP1 (1:1):</b> <code>{sig['tp1']:.2f}</code> [+{sig['tp1_pips']:.1f} pips]\n"
                f"🚀 <b>TP2 (1:2):</b> <code>{sig['tp2']:.2f}</code> [+{sig['tp2_pips']:.1f} pips]\n\n"
                f"⚠️ <i>Virtual signal for analysis only.</i>"
            )
            res = self._send(msg)
            message_id = res if isinstance(res, int) else None
            logger.info(f"[SYSTEM] Dual-Mode Signal sent: {sig['type']} ({sig['mode']}) | MSG_ID: {message_id}")
            return message_id
        except Exception as e:
            logger.error(f"[SYSTEM] Failed telegram notify: {e}")
            return None

    def send_status_update(self, trade, new_status_text):
        """Edits an existing Telegram message to reflect new trade status"""
        try:
            message_id = trade.get('message_id')
            if not message_id:
                return

            # Reconstruct message body based on trade data
            emoji = "🟢" if "BUY" in trade['type'] else "🔴"
            
            # Special formatting for BE or Expired status
            if "BE" in new_status_text:
                status_header = f"⚡ <b>{new_status_text}</b>"
            elif "EXPIRED" in new_status_text:
                status_header = f"🚫 <b>{new_status_text}</b>"
            else:
                status_header = f"<b>{new_status_text}</b>"
            
            tp1_str = f"<code>{trade['tp1']:.2f}</code> [+{trade.get('tp1_pips', 0.0):.1f} pips]" if trade.get('tp1') else f"<code>{trade.get('tp', 0.0):.2f}</code> [+{trade.get('tp_pips', 0.0):.1f} pips]"
            tp2_str = f"🚀 <b>TP2 (1:2):</b> <code>{trade['tp2']:.2f}</code> [+{trade.get('tp2_pips', 0.0):.1f} pips]\n" if trade.get('tp2') else ""
            
            msg = (
                f"{emoji} <b>XAUUSD {trade['type']}</b>\n"
                f"📌 <b>STATUS: {status_header}</b>\n\n"
                f"📥 <b>Entry Price:</b> <code>{trade['entry']:.2f}</code>\n"
                f"🛡️ <b>Stop Loss:</b> <code>{trade['sl']:.2f}</code> [-{trade.get('sl_pips', 0.0):.1f} pips]\n"
                f"🎯 <b>TP1 (1:1):</b> {tp1_str}\n"
                f"{tp2_str}\n"
                f"🕒 <b>Time:</b> {trade['open_time']}\n"
                f"🆔 <b>Trade ID:</b> <code>{trade['id']}</code>\n\n"
                f"⚠️ <i>Status updated in real-time.</i>"
            )
            
            self._send(msg, message_id=message_id)
        except Exception as e:
            logger.error(f"[SYSTEM] Failed status update notify: {e}")

    def send_exit_alert(self, exit_data):
        try:
            if exit_data['result'] == "WIN":
                emoji = "✅"
            elif exit_data['result'] == "LOSS":
                emoji = "❌"
            else:
                emoji = "🔄"
            msg = (
                f"{emoji} <b>VIRTUAL TRADE CLOSED: {exit_data['result']}</b>\n\n"
                f"💰 <b>Result:</b> {exit_data['result']} ({exit_data['pips']:.1f} pips)\n"
                f"📏 <b>MAE:</b> {exit_data['mae']:.1f} | <b>MFE:</b> {exit_data['mfe']:.1f}\n\n"
                f"🧠 <b>AI Analysis:</b> {exit_data['reason']}\n"
            )
            self._send(msg)
        except Exception as e:
            logger.error(f"[SYSTEM] Failed exit notify: {e}")

    def _send(self, text, message_id=None):
        try:
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            
            if message_id:
                url = f"https://api.telegram.org/bot{self.token}/editMessageText"
                payload["message_id"] = message_id
            else:
                url = f"https://api.telegram.org/bot{self.token}/sendMessage"
                
            response = requests.post(url, json=payload).json()
            if response.get("ok"):
                return response["result"]["message_id"]
            else:
                logger.error(f"[SYSTEM] Telegram API Error: {response.get('description')}")
                return None
        except Exception as e:
            logger.error(f"[SYSTEM] Telegram _send error: {e}")
            return None
