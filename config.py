import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "astrohunter.db"
DISCOVERIES_DIR = BASE_DIR / "discoveries"
DISCOVERIES_DIR.mkdir(exist_ok=True)
MASTER_CSV_PATH = BASE_DIR / "master_discoveries.csv"

# TESS Config
MAX_SECTORS = 4
LIGHTKURVE_CACHE_DIR = Path.home() / ".lightkurve" / "cache"
if "ASTROPY_CACHE_DIR" in os.environ:
    LIGHTKURVE_CACHE_DIR = Path(os.environ["ASTROPY_CACHE_DIR"])

# BLS Config
BLS_MIN_PERIOD = 0.4
BLS_MAX_PERIOD = 20.0
SDE_THRESHOLD = 8.0
DEPTH_MAX = 0.03  # 3% threshold distinction between rocky/gas giants and stellar eclipses

# Lomb-Scargle Config
LS_MIN_FREQ = 0.05
LS_MAX_FREQ = 30.0
LS_FAP_THRESHOLD = 1e-5  # Final cataloging threshold
LS_FAP_SWEEP = 1e-3      # Initial discovery sweep threshold

# Load local .env file if present (for local execution)
env_file = BASE_DIR / ".env"
if env_file.exists():
    try:
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass

# Webhook & Alerts Config (Defaults to False outside user-initiated live runs)
ALERTS_ENABLED = os.getenv("ALERTS_ENABLED", "false").lower() in ("true", "1", "yes")

ENABLE_DISCORD = ALERTS_ENABLED and bool(os.getenv("DISCORD_WEBHOOK_URL", ""))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

ENABLE_TELEGRAM = ALERTS_ENABLED and bool(os.getenv("TELEGRAM_BOT_TOKEN", "")) and bool(os.getenv("TELEGRAM_CHAT_ID", ""))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

