"""
Offline unit test for alert message formatting and alert suppression (WP0.1 B / Rule 10).
Guarantees alerts are disabled by default and zero external network calls occur.
"""

import tempfile
from pathlib import Path
from config import ALERTS_ENABLED
from notifier import format_alert_message, dispatch_alert
from conftest import ALERT_RECORDER

def test_alert_formatting_and_offline_suppression():
    # 1. ALERTS_ENABLED must default to False
    assert ALERTS_ENABLED is False, "ALERTS_ENABLED must default to False outside user-initiated runs"

    # 2. Format alert message offline
    details = {
        "period": 3.1415,
        "depth": 0.015,
        "amplitude": 0.002,
        "duration": 0.12,
        "sde": 14.2,
        "epoch": 2459000.1234,
        "sec_pass": True,
        "sec_ratio": 0.0,
        "odd_even_ratio": 1.02,
        "centroid_desc": "PASS: Photocenter on target"
    }

    catalog_mock = {
        "coords_str": "01h 36m 46.66s, -52d 08' 12.12\"",
        "vsx_text": "Not found",
        "simbad_text": "K1/2III giant"
    }

    with tempfile.NamedTemporaryFile("w", suffix=".png", delete=False) as tf:
        dummy_plot = tf.name

    try:
        header, plain_msg, html_msg = format_alert_message(
            "HD 99999", "TIC 999999999", "CANDIDATE_EXOPLANET", details, catalog_mock, dummy_plot, [14, 15]
        )
        assert "HD 99999" in header
        assert "3.1415" in plain_msg
        assert "<b>" in html_msg

        # 3. Test that dispatch_alert safely routes through test recorder with zero network calls
        ALERT_RECORDER.clear()
        dispatch_alert(
            "HD 99999", "TIC 999999999", "CANDIDATE_EXOPLANET", details, catalog_mock, dummy_plot, [14, 15]
        )
        assert len(ALERT_RECORDER.recorded_calls) == 1
        assert ALERT_RECORDER.recorded_calls[0]["type"] == "dispatch_alert"
        assert ALERT_RECORDER.recorded_calls[0]["args"][0] == "HD 99999"
    finally:
        Path(dummy_plot).unlink(missing_ok=True)
