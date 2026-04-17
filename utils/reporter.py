import json
import os
import requests
from datetime import datetime
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

        # กรองเฉพาะออเดอร์ที่ปิดแล้ว
        closed_trades = [t for t in data if t.get('status') == 'CLOSED']
        total_trades = len(closed_trades)

        if total_trades == 0:
            logger.info("[REPORTER] No closed trades this week.")
            return

        # คำนวณสถิติ
        wins = sum(1 for t in closed_trades if t.get('result') == 'WIN')
        losses = sum(1 for t in closed_trades if t.get('result') == 'LOSS')
        win_rate = (wins / total_trades) * 100

        net_pips = 0.0
        total_mae = 0.0
        total_mfe = 0.0

        for t in closed_trades:
            # หาผลต่างราคา (Pips)
            # Price diff calculation assuming Gold mapping
            diff = t['exit_price'] - t['entry']
            pips = (diff * 10) if t['type'].startswith('BUY') else (-diff * 10)
            net_pips += pips
            
            total_mae += t.get('mae', 0.0)
            total_mfe += t.get('mfe', 0.0)

        avg_mae = total_mae / total_trades
        avg_mfe = total_mfe / total_trades

        # 💡 AI Insight Generation
        insight = "ระบบทำงานได้ตามมาตรฐานปกติ"
        if win_rate >= 60 and net_pips > 0:
            insight = "🎯 ยอดเยี่ยม! ความแม่นยำสูงมาก โครงสร้าง SMC ของคุณคมกริบ"
        elif win_rate < 40:
            insight = "⚠️ ความแม่นยำต่ำในสัปดาห์นี้ อาจเจอภาวะตลาด Choppy แนะนำให้รอกดเฉพาะ Signal Score 8+ เท่านั้น"
        elif avg_mae > 15 and win_rate > 50:
            insight = "💡 Win Rate ดี แต่โดนลาก (MAE) ค่อนข้างลึก พิจารณาเผื่อระยะ SL ให้กว้างขึ้นอีกนิด หรือเน้นเข้า Limit Order เป็นหลัก"
        elif avg_mfe > 20 and net_pips < 0:
            insight = "💡 ราคาพุ่งไปทำกำไร (MFE) ได้ไกล แต่กลับมาชน SL (Net Pips ติดลบ) คุณควรพิจารณาเลื่อน SL บังหน้าทุน (Break-Even) เมื่อกำไรถึง 1R"

        now = datetime.now().strftime("%d %b %Y")
        msg = (
            f"📊 <b>XAUUSD Weekly Performance Report</b>\n"
            f"📅 <b>Date:</b> {now}\n"
            f"------------------------------\n"
            f"🎯 <b>Total Signals:</b> {total_trades} Trades\n"
            f"✅ <b>Wins:</b> {wins} | ❌ <b>Losses:</b> {losses}\n"
            f"🏆 <b>Win Rate:</b> {win_rate:.1f}%\n"
            f"📈 <b>Net Profit:</b> {net_pips:+.1f} Pips\n\n"
            f"📏 <b>Avg MAE:</b> {avg_mae:.1f} Pips (โดนลากเฉลี่ย)\n"
            f"📏 <b>Avg MFE:</b> {avg_mfe:.1f} Pips (วิ่งกำไรเฉลี่ย)\n\n"
            f"💡 <b>AI Insight:</b> <i>{insight}</i>"
        )

        self._send(msg)
        logger.info("[SYSTEM] Weekly report generated and sent successfully.")

    def _send(self, text):
        try:
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            requests.post(self.base_url, json=payload)
        except Exception as e:
            logger.error(f"[SYSTEM] Telegram reporter error: {e}")
