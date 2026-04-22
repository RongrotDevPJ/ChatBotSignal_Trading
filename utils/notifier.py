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
            f"● <b>Strategy Context:</b> {context['balance_msg']}\n"
            f"● <b>Structure Loop:</b> {context['frequency']}\n\n"
            f"<i>Listening for XAUUSD SMC/ICT Signals...</i>"
        )
        return self._send(msg)

    def calculate_lot_recommendation(self, entry, sl, target_risk=1.0):
        """Calculates lot size for Cent Account (1.0 Lot = $1.00 risk per 1.00 move)"""
        price_diff = abs(entry - sl)
        if price_diff <= 0: return 0.01, 0, 0
        
        # Standardized Pips: 1.00$ move = 100 points/pips
        pips = price_diff * 100
        
        # Lot calculation based on Target Risk ($1.00)
        # For Cent Accounts, 1.0 lot risks $1.00 per $1.00 price move.
        rec_lot = round(target_risk / price_diff, 2)
        
        # Potential Loss for 0.1 Lot (Cent mode)
        # 0.1 Lot risks $0.10 for 1.00 price move.
        potential_loss_01 = price_diff * 0.1 
        
        return max(0.01, rec_lot), potential_loss_01, pips

    def send_signal(self, sig):
        try:
            rec_lot, loss_01, pips = self.calculate_lot_recommendation(sig['entry'], sig['sl'])
            
            # Dual Mode UI
            is_limit = sig.get('mode') == "LIMIT"
            mode_emoji = "⏳" if is_limit else "⚡"
            mode_label = "PENDING ORDER" if is_limit else "MARKET EXECUTION"
            
            emoji = "🟢" if "BUY" in sig['type'] else "🔴"
            news_warn = "⚠️ <b>High Volatiltiy News</b>\n" if sig.get('news_active') else ""
            risk_warn = "⚠️ <b>High Risk for Small Balance</b>\n" if pips > 500 else "✅ Risk: Safe"
            
            msg = (
                f"{emoji} <b>XAUUSD {sig['type']} SIGNAL</b>\n"
                f"{mode_emoji} <b>TYPE: {mode_label}</b>\n\n"
                f"{news_warn}"
                f"🧠 <b>AI Score:</b> {sig['score']}/10\n"
                f"📊 <b>Strategy:</b> {sig['strategy']}\n"
                f"🕒 <b>Time (BKK):</b> {sig['time']}\n\n"
                f"📥 <b>Entry Price:</b> <code>{sig['entry']:.2f}</code>\n"
                f"🛡️ <b>Stop Loss:</b> <code>{sig['sl']:.2f}</code> [-{sig['sl_pips']:.1f} pips]\n"
                f"🎯 <b>Take Profit:</b> <code>{sig['tp']:.2f}</code> [+{sig['tp_pips']:.1f} pips]\n\n"
                f"💰 <b>Micro-Account Calc ($30):</b>\n"
                f"├ <b>Risk Item:</b> 0.1 Lot\n"
                f"├ <b>Potential Loss:</b> -${loss_01:.2f}\n"
                f"├ <b>Micro-Lot Rec (Risk $1):</b> {rec_lot} Lot\n"
                f"└ {risk_warn}\n\n"
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
            
            msg = (
                f"{emoji} <b>XAUUSD {trade['type']}</b>\n"
                f"📌 <b>STATUS: {status_header}</b>\n\n"
                f"📥 <b>Entry Price:</b> <code>{trade['entry']:.2f}</code>\n"
                f"🛡️ <b>Stop Loss:</b> <code>{trade['sl']:.2f}</code> [-{trade.get('sl_pips', 0.0):.1f} pips]\n"
                f"🎯 <b>Take Profit:</b> <code>{trade['tp']:.2f}</code> [+{trade.get('tp_pips', 0.0):.1f} pips]\n\n"
                f"🕒 <b>Time:</b> {trade['open_time']}\n"
                f"🆔 <b>Trade ID:</b> <code>{trade['id']}</code>\n\n"
                f"⚠️ <i>Status updated in real-time.</i>"
            )
            
            self._send(msg, message_id=message_id)
        except Exception as e:
            logger.error(f"[SYSTEM] Failed status update notify: {e}")

    def send_exit_alert(self, exit_data):
        try:
            emoji = "✅" if exit_data['result'] == "WIN" else "❌"
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
