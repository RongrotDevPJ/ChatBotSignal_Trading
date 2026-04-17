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

    def calculate_lot_recommendation(self, entry, sl, target_risk=1.0):
        """Calculates lot size to risk exactly $1.00"""
        price_diff = abs(entry - sl)
        if price_diff <= 0: return 0.01, 0, 0
        
        # SL in Pips (Gold 1.00 points = 10 pips usually)
        pips = price_diff * 10
        
        # Standard Cent Lot: 0.1 Lot = $0.10 per point? 
        # For $1.0 risk on a 5.0 point move ($50 move per 1 lot):
        # We need Lot = 1.0 / (PriceDiff * Multiplier)
        # Let's assume standard Cent Lot (0.1 Lot = $1 per 1.00 move?)
        # For 0.1 Lot, 1.00 move = $1.00.
        # So RecommendedLot = 1.0 / PriceDiff
        rec_lot = round(target_risk / price_diff, 2)
        
        # Loss for 0.1 lot
        loss_01 = price_diff * 0.1 * 10 # Assuming 0.1 slot = $1 per point
        # Let's use simpler: 0.1 Lot (Cent) risks $0.10 per point.
        potential_loss_01 = price_diff * 0.1
        
        return max(0.01, rec_lot), potential_loss_01, pips

    def send_signal(self, sig):
        try:
            rec_lot, loss_01, pips = self.calculate_lot_recommendation(sig['entry'], sig['sl'])
            
            emoji = "🟢" if sig['type'] == "BUY" else "🔴"
            news_warn = "⚠️ <b>High Volatility Warning (News)</b>\n" if sig.get('news_active') else ""
            risk_warn = "⚠️ <b>High Risk for Small Balance</b> (SL > 500 pips)\n" if pips > 500 else "✅ Risk: Safe"
            
            msg = (
                f"{emoji} <b>XAUUSD {sig['type']} SIGNAL</b>\n\n"
                f"{news_warn}"
                f"🧠 <b>AI Score:</b> {sig['score']}/10\n"
                f"📊 <b>Strategy:</b> {sig['strategy']}\n"
                f"🕒 <b>Time (BKK):</b> {sig['time']}\n\n"
                f"📥 <b>Entry Price:</b> {sig['entry']:.2f}\n"
                f"🛡️ <b>Stop Loss:</b> {sig['sl']:.2f}\n"
                f"🎯 <b>Take Profit:</b> {sig['tp']:.2f}\n\n"
                f"📉 <b>Potential Loss (0.1 Lot):</b> -${loss_01:.2f}\n"
                f"💰 <b>Micro-Account Rec (Risk $1):</b> {rec_lot} Lot\n"
                f"{risk_warn}\n\n"
                f"⚠️ <i>Virtual signal for analysis only.</i>"
            )

            requests.post(self.base_url, json={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"})
            logger.info(f"[SYSTEM] Signal notification sent for {sig['type']}")
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
            requests.post(self.base_url, json={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"})
        except Exception as e:
            logger.error(f"[SYSTEM] Failed exit notify: {e}")
