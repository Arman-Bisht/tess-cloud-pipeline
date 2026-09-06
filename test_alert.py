import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from notifier import dispatch_alert
from config import DISCOVERIES_DIR

# Create a dummy image for testing
dummy_plot = DISCOVERIES_DIR / "test_alert.png"
plt.figure(figsize=(8, 4))
plt.plot(np.sin(np.linspace(0, 10, 100)), label="Test Signal", color='r')
plt.title("AstroHunter Pro - Local Test Alert")
plt.legend()
plt.tight_layout()
plt.savefig(dummy_plot)
plt.close()

details = {
    "period": 3.1415,
    "depth": 0.015,
    "amplitude": 0.002,
    "duration": 0.12,
    "sde": 14.2,
    "epoch": 2459000.1234,
    "sec_pass": True,
    "sec_ratio": 0.0,
    "odd_even_ratio": 1.02
}

catalog_mock = {
    "coords_str": "01h 36m 46.66s, -52d 08' 12.12\"",
    "vsx_text": "❌ Not found",
    "simbad_text": "✅ K1/2III giant"
}

print("Dispatching test alert to Telegram from local machine...")
dispatch_alert("HD 99999", "TIC 999999999", "DISCOVERY_UNRECORDED_CANDIDATE_EXOPLANET", details, catalog_mock, str(dummy_plot), [14, 15, 16])
print("Test complete! Check your Telegram!")
