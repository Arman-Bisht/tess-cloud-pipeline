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
plt.title("AstroHunter Pro - Test Alert Image")
plt.legend()
plt.tight_layout()
plt.savefig(dummy_plot)
plt.close()

details = {
    "period": 3.1415,
    "depth": 0.015,
    "amplitude": 1.2
}

print("Dispatching test alert to Telegram...")
dispatch_alert("TEST-001", "CANDIDATE_EXOPLANET", details, str(dummy_plot))
print("Test complete. Check your Telegram!")
