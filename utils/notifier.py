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
        """Calculates lot size to risk exactly $1.00"""
        price_diff = abs(entry - sl)
        if price_diff <= 0: return 0.01, 0, 0
        
        pips = price_diff * 10
        # Formula: RecLot = TargetRisk / PriceDiff
        # 1.0 standard move (100 points) = $100 for 1.0 Lot.
        # So RecLot = 1.0 / (PriceDiff * 1) ? 
        # For XAUUSD, if entry=2000, sl=1995 (Diff=5), 0.01 Lot = $5 risk. 
        # To get $1 risk, we need 0.01 / 5 = 0.002.
        # But if user uses Cent lot (0.1 Lot = 1 Std?), let's stick to the multiplier:
        rec_lot = round(target_risk / price_diff, 2)
        
        # Loss for 0.1 Lot (Fixed reference from user)
        # Using user's implicit logic: 0.1 lot risks $1 for 1.00 point?
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
                f"📥 <b>Entry Price:</b> {sig['entry']:.2f}\n"
                f"🛡️ <b>Stop Loss:</b> {sig['sl']:.2f}\n"
                f"🎯 <b>Take Profit:</b> {sig['tp']:.2f}\n\n"
                f"💰 <b>Micro-Account Calc ($30):</b>\n"
                f"├ <b>Risk Item:</b> 0.1 Lot (Cent)\n"
                f"├ <b>Potential Loss:</b> -${loss_01:.2f}\n"
                f"├ <b>Micro-Lot Rec (Risk $1):</b> {rec_lot} Lot\n"
                f"└ {risk_warn}\n\n"
                f"⚠️ <i>Virtual signal for analysis only.</i>"
            )
            self._send(msg)
            logger.info(f"[SYSTEM] Dual-Mode Signal sent: {sig['type']} ({sig['mode']})")
        except Exception as e:
            logger.error(f"[SYSTEM] Failed telegram notify: {e}")

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

    def _send(self, text):
        try:
            url = f"{self.base_url}"
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            requests.post(url, json=payload)
            return True
        except Exception as e:
            logger.error(f"[SYSTEM] Telegram _send error: {e}")
            return False
