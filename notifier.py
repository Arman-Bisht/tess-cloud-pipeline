import logging
import requests
from config import ENABLE_DISCORD, DISCORD_WEBHOOK_URL, ENABLE_TELEGRAM, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

def dispatch_alert(tic_id: str, category: str, details: dict, plot_path: str):
    title = f"🪐 NEW EXOPLANET CANDIDATE: {tic_id}" if "EXOPLANET" in category else f"🌟 NEW VARIABLE/EB FOUND: {tic_id}"
    
    # Format message
    period = details.get('period', 'N/A')
    depth = details.get('depth', 'N/A')
    amp = details.get('amplitude', 'N/A')
    
    msg = f"<b>Category:</b> {category}\n"
    if period != 'N/A':
        msg += f"<b>Period:</b> {period:.4f} days\n"
    if depth != 'N/A':
        msg += f"<b>Depth:</b> {depth*100:.2f}%\n"
    if amp != 'N/A':
        msg += f"<b>Amplitude:</b> {amp:.6f}\n"
        
    # Links
    tic_num = ''.join(filter(str.isdigit, tic_id))
    msg += f"\n<a href='https://exofop.ipac.caltech.edu/tess/target.php?id={tic_num}'>ExoFOP</a>\n"
    
    # Desktop
    # send_desktop_notification(title, f"{category}\nPeriod: {period}")
    
    # Discord
    if ENABLE_DISCORD and DISCORD_WEBHOOK_URL:
        try:
            with open(plot_path, "rb") as f:
                # Discord uses markdown
                discord_msg = msg.replace('<b>', '**').replace('</b>', '**').replace("<a href='", "[ExoFOP](").replace("'>ExoFOP</a>", ")")
                payload = {"content": f"# {title}\n{discord_msg}"}
                files = {"file": (plot_path.split('/')[-1], f, "image/png")}
                requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files)
        except Exception as e:
            logger.error(f"Discord webhook failed: {e}")
            
    # Telegram
    if ENABLE_TELEGRAM and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            with open(plot_path, "rb") as f:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                payload = {"chat_id": TELEGRAM_CHAT_ID, "caption": f"<b>{title}</b>\n{msg}", "parse_mode": "HTML"}
                files = {"photo": f}
                resp = requests.post(url, data=payload, files=files)
                if resp.status_code != 200:
                    print(f"Telegram API Error: {resp.text}")
        except Exception as e:
            print(f"Telegram webhook failed: {e}")
