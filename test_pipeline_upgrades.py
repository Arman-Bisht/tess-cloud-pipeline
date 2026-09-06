import numpy as np
import lightkurve as lk
from astropy.time import Time
from single_transit_engine import run_single_transit, trapezoid_transit_model
from microlensing_engine import run_microlensing, paczynski_model
from variable_engine import run_lomb_scargle
from bls_engine import run_bls
from vetter import vet_signals
from visualizer import save_diagnostic_plot
from db import save_discovery, get_connection
from notifier import format_alert_message
import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

print('--- Starting End-to-End Simulation Tests ---')

# 1. Create a synthetic Single-Transit Light Curve
t = np.linspace(2459000, 2459027, 2000)
baseline = 1.0
np.random.seed(42)
noise = np.random.normal(0, 0.001, len(t))
# Solitary transit at t0 = 2459012.5, depth=0.015, duration=0.2 days (4.8 hours)
flux_single = trapezoid_transit_model(t, 2459012.5, 0.015, 0.2, 0.2, baseline) + noise
time_obj = Time(t, format='jd')
lc_single = lk.LightCurve(time=time_obj, flux=flux_single)
single_res = run_single_transit(lc_single)
assert single_res is not None, 'Single transit should be detected'
print('Single transit detected:', round(single_res['epoch'], 2), 'SNR:', round(single_res['snr'], 1))

# 2. Create a synthetic Microlensing Light Curve
flux_micro = paczynski_model(t, 2459015.0, 0.3, 4.0, baseline) + noise
lc_micro = lk.LightCurve(time=time_obj, flux=flux_micro)
micro_res = run_microlensing(lc_micro)
assert micro_res is not None, 'Microlensing should be detected'
print('Microlensing detected:', round(micro_res['epoch'], 2), 'tE:', round(micro_res['tE'], 1), 'days')

# 3. Test Vetting & Tier assignment
cat_single, best_single = vet_signals(None, None, single_res, None, lc_single, lc_single, [14, 15])
print('Vetted category:', cat_single, 'Tier:', best_single['tier'])
assert cat_single == 'SINGLE_TRANSIT_CANDIDATE'

cat_micro, best_micro = vet_signals(None, None, None, micro_res, lc_micro, lc_micro, [14, 15])
print('Vetted category:', cat_micro, 'Tier:', best_micro['tier'])
assert cat_micro == 'MICROLENSING_EVENT'

# 4. Test 5-Panel Diagnostic Plot Generator
plot_single = save_diagnostic_plot('HD_TEST_SINGLE', cat_single, lc_single, lc_single, best_single, [14, 15])
assert os.path.exists(plot_single) and os.path.getsize(plot_single) > 10000, '5-panel plot should be saved and non-empty'
print('5-Panel plot generated:', os.path.basename(plot_single), f'({os.path.getsize(plot_single)} bytes)')

# 5. Test DB & Master CSV
catalog_mock = {
    'coords_str': "01h 36m 46.66s, -52d 08' 12.12\"",
    'simbad_type': 'K1/2III giant',
    'simbad_text': 'OK',
    'vsx_known': False,
    'vsx_text': 'Not found'
}
save_discovery('HD_TEST_SINGLE', 'HD_TEST_SINGLE', 24.19, -52.14, cat_single, best_single, catalog_mock, plot_single, [14, 15])
print('Saved to SQLite and Master CSV successfully!')

# 6. Test Alert Message Formatting
title, plain_msg, html_msg = format_alert_message('HD 10028', 'TIC 158623300', cat_single, best_single, catalog_mock, plot_single, [14, 15, 16])
print('Formatted Alert Sample:')
print(plain_msg[:250] + '...')

print('--- ALL PIPELINE TESTS PASSED SUCCESSFULLY! ---')
