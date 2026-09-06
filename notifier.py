import logging
import os
import platform
import requests
from typing import Dict, Any, Optional, List, Tuple
from config import ENABLE_DISCORD, DISCORD_WEBHOOK_URL, ENABLE_TELEGRAM, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

def send_desktop_notification(title: str, message: str):
    """
    Sends desktop notification on Windows without crashing in headless Linux.
    """
    if platform.system() == "Windows":
        try:
            from plyer import notification
            notification.notify(
                title=title[:64],
                message=message[:128],
                app_name="Astrohunter",
                timeout=5
            )
        except Exception as e:
            logger.debug(f"Desktop notification bypassed: {e}")

def format_alert_message(target_name: str, 
                         tic_id: str, 
                         category: str, 
                         details: Dict[str, Any], 
                         catalog_info: Dict[str, Any], 
                         plot_path: str,
                         sectors: Optional[List[int]] = None) -> Tuple[str, str, str]:
    """
    Formats the alert following Section 5.1 specification.
    Returns (title, plain_text, html_text).
    """
    # Header emoji & title
    if "EXOPLANET" in category:
        header = f"🪐 NEW EXOPLANET CANDIDATE: {target_name}"
    elif "SINGLE_TRANSIT" in category:
        header = f"🌌 SINGLE TRANSIT CANDIDATE: {target_name}"
    elif "MICROLENSING" in category:
        header = f"🔭 NEW MICROLENSING EVENT: {target_name}"
    else:
        header = f"🌟 NEW VARIABLE/EB FOUND: {target_name}"

    tic_num = ''.join(filter(str.isdigit, tic_id))
    coords_str = catalog_info.get("coords_str", "N/A")
    sectors_str = ", ".join(map(str, sectors)) if sectors else "TESS"
    
    # Detection fields
    det_type = category.replace("DISCOVERY_UNRECORDED_", "").replace("_", " ").title()
    period = details.get('period')
    period_str = f"{period:.4f} ± 0.0005 d" if period is not None else "Single Event (> 27 d)"
    
    epoch = details.get('epoch')
    epoch_str = f"{epoch:.4f} (BJD)" if epoch is not None else "N/A"
    
    depth = details.get('depth')
    depth_str = f"{depth*100:.2f}%" if depth is not None else "N/A"
    
    duration = details.get('duration')
    duration_str = f"{duration*24.0:.1f} h" if duration is not None else "N/A"
    
    sde = details.get('sde', 0.0)
    sde_str = f"{sde:.1f}"
    
    # Vetting fields
    sec_pass = details.get('sec_pass', True)
    sec_ratio = details.get('sec_ratio', 0.0)
    sec_str = "None detected" if sec_pass else f"Detected (drop {sec_ratio*100:.1f}%)"
    
    oe_ratio = details.get('odd_even_ratio')
    oe_str = f"{oe_ratio:.2f}" if oe_ratio is not None and "EXOPLANET" in category else "N/A"
    
    vsx_match = catalog_info.get("vsx_text", "❌ Not found")
    simbad_match = catalog_info.get("simbad_text", "❌ Not cataloged")
    
    exofop_url = f"https://exofop.ipac.caltech.edu/tess/target.php?id={tic_num}"
    
    # Section 5.1 Plain Text
    plain_text = f"""{header}
━━━━━━━━━━━━━━━━━━━━━━━
📌 TIC ID: {tic_num}
📍 Coords: {coords_str}
🔭 Sectors: {sectors_str} (2-min cadence)

📊 DETECTION
   Type: {det_type}
   Period: {period_str}
   Epoch: {epoch_str}
   Depth: {depth_str}
   Duration: {duration_str}
   SDE: {sde_str}

🛡️ VETTING
   Secondary Eclipse: {sec_str}
   Odd/Even Ratio: {oe_str}
   VSX Match: {vsx_match}
   SIMBAD Match: {simbad_match}

🔗 ExoFOP: {exofop_url}
💾 Files: {plot_path}"""

    # HTML for Telegram
    html_text = f"""<b>{header}</b>
━━━━━━━━━━━━━━━━━━━━━━━
📌 <b>TIC ID:</b> {tic_num}
📍 <b>Coords:</b> {coords_str}
🔭 <b>Sectors:</b> {sectors_str}

📊 <b>DETECTION</b>
   <b>Type:</b> {det_type}
   <b>Period:</b> {period_str}
   <b>Epoch:</b> {epoch_str}
   <b>Depth:</b> {depth_str}
   <b>Duration:</b> {duration_str}
   <b>SDE:</b> {sde_str}

🛡️ <b>VETTING</b>
   <b>Secondary Eclipse:</b> {sec_str}
   <b>Odd/Even Ratio:</b> {oe_str}
   <b>VSX Match:</b> {vsx_match}
   <b>SIMBAD Match:</b> {simbad_match}

🔗 <a href='{exofop_url}'>ExoFOP Target Page</a>
💾 <code>{os.path.basename(plot_path)}</code>"""

    return header, plain_text, html_text

def dispatch_alert(target_name: str, 
                   tic_id: str, 
                   category: str, 
                   details: Dict[str, Any], 
                   catalog_info: Dict[str, Any], 
                   plot_path: str,
                   sectors: Optional[List[int]] = None):
    """
    Dispatches alerts to Telegram, Discord, and Desktop.
    """
    title, plain_msg, html_msg = format_alert_message(target_name, tic_id, category, details, catalog_info, plot_path, sectors)
    
    # 1. Desktop Notification
    send_desktop_notification(title, f"{category}\nSDE: {details.get('sde', 0):.1f}")
    
    # 2. Discord Webhook
    if ENABLE_DISCORD and DISCORD_WEBHOOK_URL:
        try:
            with open(plot_path, "rb") as f:
                payload = {"content": f"```\n{plain_msg}\n```"}
                files = {"file": (os.path.basename(plot_path), f, "image/png")}
                requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files, timeout=15)
        except Exception as e:
            logger.error(f"Discord webhook failed: {e}")
            
    # 3. Telegram Bot
    if ENABLE_TELEGRAM and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            with open(plot_path, "rb") as f:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                payload = {
                    "chat_id": TELEGRAM_CHAT_ID, 
                    "caption": html_msg, 
                    "parse_mode": "HTML"
                }
                files = {"photo": f}
                resp = requests.post(url, data=payload, files=files, timeout=30)
                if resp.status_code != 200:
                    logger.warning(f"Telegram API response ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")
