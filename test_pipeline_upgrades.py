import numpy as np
import lightkurve as lk
from astropy.time import Time
from pathlib import Path
from single_transit_engine import run_single_transit, trapezoid_transit_model
from microlensing_engine import run_microlensing, paczynski_model
from vetter import vet_signals
from visualizer import save_diagnostic_plot
from notifier import format_alert_message

def test_end_to_end_simulation():
    # 1. Create a synthetic Single-Transit Light Curve
    t = np.linspace(2459000, 2459027, 2000)
    baseline = 1.0
    np.random.seed(42)
    noise = np.random.normal(0, 0.001, len(t))
    flux_single = trapezoid_transit_model(t, 2459012.5, 0.015, 0.2, 0.2, baseline) + noise
    time_obj = Time(t, format='jd')
    lc_single = lk.LightCurve(time=time_obj, flux=flux_single)
    single_res = run_single_transit(lc_single)
    assert single_res is not None, 'Single transit should be detected'

    # 2. Create a synthetic Microlensing Light Curve
    flux_micro = paczynski_model(t, 2459015.0, 0.3, 4.0, baseline) + noise
    lc_micro = lk.LightCurve(time=time_obj, flux=flux_micro)
    micro_res = run_microlensing(lc_micro)
    assert micro_res is not None, 'Microlensing should be detected'

    # 3. Test Vetting & Tier assignment
    cat_single, best_single = vet_signals(None, None, single_res, None, lc_single, lc_single, [14, 15])
    assert cat_single == 'SINGLE_TRANSIT_CANDIDATE'

    cat_micro, best_micro = vet_signals(None, None, None, micro_res, lc_micro, lc_micro, [14, 15])
    assert cat_micro == 'MICROLENSING_EVENT'

    # 4. Test 5-Panel Diagnostic Plot Generator (clean up plot after check to prevent pollution)
    plot_single = save_diagnostic_plot('HD_TEST_SINGLE', cat_single, lc_single, lc_single, best_single, [14, 15])
    try:
        assert Path(plot_single).exists() and Path(plot_single).stat().st_size > 10000, '5-panel plot should be saved and non-empty'

        # 5. Verify data structures
        assert 'epoch' in best_single and 'depth' in best_single

        # 6. Test Alert Message Formatting offline
        catalog_mock = {
            'coords_str': "01h 36m 46.66s, -52d 08' 12.12\"",
            'simbad_type': 'K1/2III giant',
            'simbad_text': 'OK',
            'vsx_known': False,
            'vsx_text': 'Not found'
        }
        title, plain_msg, html_msg = format_alert_message(
            'HD 10028', 'TIC 158623300', cat_single, best_single, catalog_mock, plot_single, [14, 15, 16]
        )
        assert 'HD 10028' in title
        assert '01h 36m 46.66s' in plain_msg
    finally:
        Path(plot_single).unlink(missing_ok=True)

if __name__ == '__main__':
    test_end_to_end_simulation()
    print('Simulation test passed cleanly.')
