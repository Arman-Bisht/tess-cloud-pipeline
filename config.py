import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "astrohunter.db"
DISCOVERIES_DIR = BASE_DIR / "discoveries"
DISCOVERIES_DIR.mkdir(exist_ok=True)

# TESS Config
MAX_SECTORS = 4
LIGHTKURVE_CACHE_DIR = Path.home() / ".lightkurve" / "cache" # Default lightkurve cache dir
if "ASTROPY_CACHE_DIR" in os.environ:
    LIGHTKURVE_CACHE_DIR = Path(os.environ["ASTROPY_CACHE_DIR"])

# BLS Config
BLS_MIN_PERIOD = 0.4
BLS_MAX_PERIOD = 20.0
SDE_THRESHOLD = 7.0
DEPTH_MAX = 0.03 # 3% max for exoplanet (greater is EB)

# Lomb-Scargle Config
LS_MIN_FREQ = 0.05
LS_MAX_FREQ = 30.0
LS_FAP_THRESHOLD = 1e-5

# Webhook Config
ENABLE_DISCORD = True
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

ENABLE_TELEGRAM = True
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
