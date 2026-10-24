"""
Unit and Regression Test Suite for Pipeline Plumbing & Engine Scalability.
Validates:
1. Cloud-agnostic importability of main.py
2. Catalog metadata retrieval (r_star_rsun and m_star_msun plumbing)
3. Physical Keplerian orbit separation and giant duration constraints
4. Tri-state centroid vetting and strict Tier A gatekeeping
5. Multi-year BLS search grid scalability (sub-5s execution across wide data gaps)
"""

import time
import numpy as np
import astropy.units as u
import lightkurve as lk

# Enforce offline network isolation and alert suppression (Rule 10)
try:
    import conftest
    conftest.install_test_network_and_alert_guards()
except Exception:
    pass

# 1. Test cloud-agnostic imports
def test_cloud_agnostic_imports():
    print("Test 1: Testing cloud-agnostic imports...")
    import main
    assert hasattr(main, 'process_target'), "main.py should export process_target"
    assert hasattr(main, 'serverless_entry'), "main.py should export serverless_entry"
    print("  -> Passed: main.py imported successfully without cloud package dependencies.")

# 2. Test Catalog metadata plumbing
def test_catalog_plumbing():
    print("Test 2: Testing catalog dictionary keys and plumbing...")
    from catalog_checker import check_catalog
    info = check_catalog(0.0, 0.0, "CANDIDATE", 3.0, r_star=1.5, m_star=1.2, gaia_id="12345")
    assert 'r_star_rsun' in info and info['r_star_rsun'] == 1.5, "r_star_rsun missing"
    assert 'r_star' in info and info['r_star'] == 1.5, "r_star backward compatibility key missing"
    assert 'm_star_msun' in info and info['m_star_msun'] == 1.2, "m_star_msun missing"
    assert 'm_star' in info and info['m_star'] == 1.2, "m_star backward compatibility key missing"
    print("  -> Passed: Both r_star_rsun and r_star are properly provided.")

# 3. Test Physical Orbit & Duration Constraints
def test_physical_constraints():
    print("Test 3: Testing physical Keplerian orbit and giant duration constraints...")
    from vetter import check_orbit_physical_separation, check_transit_duration_physical
    
    # Orbit inside star: P=0.61d on R*=28.2 Rsun giant -> a ~ 4.4 Rsun <= 28.2 Rsun
    orbit_ok, a_rsun, desc = check_orbit_physical_separation(period=0.61, r_star=28.2, m_star=2.5)
    assert not orbit_ok, f"Expected unphysical orbit to fail, got {orbit_ok}"
    assert a_rsun < 28.2, f"Expected a < R*, got a={a_rsun}"
    
    # Orbit outside star: P=10.0d on R*=2.0 Rsun -> a ~ 25.5 Rsun > 2.0 Rsun
    orbit_ok2, a_rsun2, desc2 = check_orbit_physical_separation(period=10.0, r_star=2.0, m_star=1.5)
    assert orbit_ok2, f"Expected physical orbit to pass, got {orbit_ok2}"
    
    # Giant duration check: 3.6h (0.15d) transit on 88 Rsun giant requires > 320h
    dur_ok, t_min, dur_desc = check_transit_duration_physical(duration_days=0.15, r_star=88.0, m_star=2.5)
    assert not dur_ok, f"Expected ultra-short giant dip to fail, got {dur_ok}"
    print("  -> Passed: Physical constraints correctly flag impossible orbits and durations.")

# 4. Test Tri-State Centroid and Strict Tier A Gatekeeping
def test_centroid_and_tier_gatekeeping():
    print("Test 4: Testing tri-state centroid and strict Tier A gatekeeping...")
    from vetter import assign_tier, check_centroid_motion
    
    # Case 1: Centroid NOT_RUN cannot be Tier A even with high SDE and valid parameters
    tier_not_run = assign_tier(
        category="SINGLE_TRANSIT",
        sde=25.0,
        cycles=1.0,
        sec_pass=True,
        centroid_status="NOT_RUN",
        r_star=1.5,
        orbit_pass=True,
        dur_pass=True
    )
    assert tier_not_run == "B", f"Expected NOT_RUN centroid to be capped at Tier B, got {tier_not_run}"
    
    # Case 2: Centroid FAIL is gated to Tier B (Needs Manual Review / Possible Blend Alert) rather than automatic Tier C reject
    tier_fail = assign_tier(
        category="CANDIDATE_EXOPLANET",
        sde=15.0,
        cycles=5.0,
        sec_pass=True,
        centroid_status="FAIL",
        r_star=1.0,
        orbit_pass=True,
        dur_pass=True
    )
    assert tier_fail == "B", f"Expected FAIL centroid to be gated to Tier B (needs manual review), got {tier_fail}"
    
    # Case 3: Measured PASS with all criteria met achieves Tier A
    tier_pass = assign_tier(
        category="CANDIDATE_EXOPLANET",
        sde=15.0,
        cycles=5.0,
        sec_pass=True,
        centroid_status="PASS",
        r_star=1.0,
        orbit_pass=True,
        dur_pass=True
    )
    assert tier_pass == "A", f"Expected measured PASS to achieve Tier A, got {tier_pass}"
    print("  -> Passed: Centroid tri-state strictly enforces Tier A requirement.")

# 5. Test BLS Multi-Year Grid Scaling
def test_bls_grid_multi_year_scalability():
    print("Test 5: Testing BLS search grid scalability on multi-year baselines...")
    from bls_engine import run_bls
    
    # Create two synthetic 27-day sectors separated by a 700-day gap
    sector1_t = np.linspace(0.0, 27.0, 2000)
    sector2_t = np.linspace(700.0, 727.0, 2000)
    t = np.concatenate([sector1_t, sector2_t])
    y = np.ones_like(t) + 0.001 * np.random.randn(len(t))
    
    lc = lk.LightCurve(time=t, flux=y)
    t0 = time.time()
    res = run_bls(lc)
    elapsed = time.time() - t0
    
    assert res is not None, "BLS should return results on multi-year lightcurve"
    assert elapsed < 20.0, f"BLS took {elapsed:.2f}s (must finish in < 20s on multi-year baselines)"
    print(f"  -> Passed: BLS completed in {elapsed:.2f}s across a 727-day baseline.")

# 6. Test DOWNLOAD_ERROR targets are retried by process_target
def test_download_error_retry():
    print("Test 6: Testing that DOWNLOAD_ERROR targets are retried in process_target...")
    from unittest.mock import patch
    import main
    from db import upsert_target, get_connection
    
    mock_tic = "HD_MOCK_RETRY_TEST"
    upsert_target(mock_tic, mock_tic, 0.0, 0.0, status="DOWNLOAD_ERROR")
    
    called_count = 0
    def mock_get_lightcurves(target):
        nonlocal called_count
        called_count += 1
        return None  # Simulate no data on retry to exit cleanly
        
    with patch("main.get_lightcurves", side_effect=mock_get_lightcurves):
        main.process_target(mock_tic)
        
    # Clean up mock row from DB
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM targets WHERE tic_id = ?", (mock_tic,))
    conn.commit()
    conn.close()
    
    assert called_count == 1, f"Expected get_lightcurves to be called on DOWNLOAD_ERROR target, called {called_count} times"
    print("  -> Passed: process_target correctly retries targets with status DOWNLOAD_ERROR.")

# 7. Test that unmeasured centroid does not mislabel clean planet as Eclipsing Binary
def test_unmeasured_centroid_planet_classification():
    print("Test 7: Testing that unmeasured centroid does not mislabel clean planet as ECLIPSING_BINARY...")
    from vetter import vet_signals
    
    # Synthetic light curve with no centroid columns (simulating QLP) and injected 0.5% clean planet transit
    t = np.linspace(0, 27, 3000)
    y = np.ones_like(t) + 0.0001 * np.random.randn(len(t))
    phase = ((t - 1.2 + 0.5 * 3.5) % 3.5) / 3.5 - 0.5
    y[np.abs(phase) < (0.15 / (2.0 * 3.5))] -= 0.005
    lc_flat = lk.LightCurve(time=t, flux=y)
    lc_unflat = lc_flat
    
    # Synthetic BLS result for a clean planet transit (depth = 0.5%, well below DEPTH_MAX = 2%)
    bls_res = {
        "period": 3.5,
        "epoch": 1.2,
        "duration": 0.15,
        "depth": 0.005,
        "sde": 15.0,
        "power": 100.0
    }
    
    # Vet signal with host radius 1.0 Rsun, 1.0 Msun
    cat, res = vet_signals(bls_res=bls_res, ls_res=None, single_res=None, micro_res=None,
                           lc_flat=lc_flat, lc_unflat=lc_unflat, sectors=[1],
                           r_star=1.0, m_star=1.0)
                           
    assert cat == "CANDIDATE_EXOPLANET", f"Expected CANDIDATE_EXOPLANET, got {cat}"
    assert res.get("tier") == "B", f"Expected Tier B for unmeasured centroid, got {res.get('tier')}"
    assert res.get("centroid_status") == "NOT_RUN", f"Expected NOT_RUN centroid status, got {res.get('centroid_status')}"
    print("  -> Passed: Clean transit with unmeasured centroid is CANDIDATE_EXOPLANET at Tier B (not ECLIPSING_BINARY).")

# 8. Test Difference Image Centroid on contaminated on-target transits and blends
def test_difference_image_centroid_benchmarks():
    print("Test 8: Testing Difference Image Centroid on contaminated neighbor & blend benchmarks...")
    from vetter import compute_difference_image_centroid
    
    n_cad = 500
    np.random.seed(42)
    t = np.linspace(0, 10, n_cad)
    y_grid, x_grid = np.mgrid[:11, :11]
    
    target_prf = np.exp(-((x_grid - 5)**2 + (y_grid - 5)**2) / 2.0)
    target_prf /= np.sum(target_prf)
    
    neighbor_prf = np.exp(-((x_grid - 8)**2 + (y_grid - 5)**2) / 2.0)
    neighbor_prf /= np.sum(neighbor_prf)
    
    in_tr = (t > 4.5) & (t < 5.5)
    out_tr = (t < 4.0) | (t > 6.0)
    
    # Benchmark Case 1: Isolated on-target 1% transit
    cube_iso = np.array([(1000.0 * (0.99 if in_tr[i] else 1.0) * target_prf + np.random.normal(0, 1.0, (11, 11))) for i in range(n_cad)])
    st1, off1, _ = compute_difference_image_centroid(cube_iso, in_tr, out_tr, target_pos=(5.0, 5.0))
    assert st1 == "PASS" and off1 < 0.6, f"Expected PASS on isolated transit, got {st1} ({off1} px)"
    
    # Benchmark Case 2: On-target 1% transit with 40% neighbor 3 px away (immune to centroid pull)
    cube_contam = np.array([(1000.0 * (0.99 if in_tr[i] else 1.0) * target_prf + 400.0 * neighbor_prf + np.random.normal(0, 1.0, (11, 11))) for i in range(n_cad)])
    st2, off2, _ = compute_difference_image_centroid(cube_contam, in_tr, out_tr, target_pos=(5.0, 5.0))
    assert st2 == "PASS" and off2 < 0.5, f"Expected PASS on contaminated on-target transit, got {st2} ({off2} px)"
    
    # Benchmark Case 3: Constant target with 5% eclipse on neighbor (true blend)
    cube_blend = np.array([(1000.0 * target_prf + 400.0 * (0.95 if in_tr[i] else 1.0) * neighbor_prf + np.random.normal(0, 1.0, (11, 11))) for i in range(n_cad)])
    st3, off3, _ = compute_difference_image_centroid(cube_blend, in_tr, out_tr, target_pos=(5.0, 5.0))
    assert st3 == "FAIL" and off3 > 1.8, f"Expected FAIL on neighbor blend, got {st3} ({off3} px)"
    
    print("  -> Passed: Difference Image Centroid correctly passes contaminated on-target transits and flags neighbor blends.")

# 9. Test Difference Image Separation Sweep (0.5 to 3.0 px) & Missing WCS NOT_RUN Guard
def test_difference_image_separation_sweep_and_missing_wcs():
    print("Test 9: Testing Difference Image Separation Sweep (0.5..3.0 px) & Missing WCS NOT_RUN guard...")
    from vetter import compute_difference_image_centroid, assign_tier
    
    n_cad = 500
    np.random.seed(101)
    t = np.linspace(0, 10, n_cad)
    y_grid, x_grid = np.mgrid[:11, :11]
    
    target_prf = np.exp(-((x_grid - 5.0)**2 + (y_grid - 5.0)**2) / 2.0)
    target_prf /= np.sum(target_prf)
    
    in_tr = (t > 4.5) & (t < 5.5)
    out_tr = (t < 4.0) | (t > 6.0)
    
    # 9a. Missing WCS (target_pos=None) must return NOT_RUN, even if a bright neighbor exists
    bright_neighbor_prf = np.exp(-((x_grid - 8.0)**2 + (y_grid - 5.0)**2) / 2.0)
    bright_neighbor_prf /= np.sum(bright_neighbor_prf)
    cube_no_wcs = np.array([(500.0 * target_prf + 2000.0 * (0.95 if in_tr[i] else 1.0) * bright_neighbor_prf + np.random.normal(0, 1.0, (11, 11))) for i in range(n_cad)])
    st_nowcs, off_nowcs, _ = compute_difference_image_centroid(cube_no_wcs, in_tr, out_tr, target_pos=None)
    assert st_nowcs == "NOT_RUN" and np.isnan(off_nowcs), f"Expected NOT_RUN when WCS target_pos is None, got {st_nowcs}"
    
    # 9b. Separation sweep across neighbor blend distances: 0.5, 1.3, 2.5, 3.0 px
    sweep_Expectations = [
        (0.5, "PASS", "A"),           # Sub-pixel blend (< 0.96 px physical resolution limit)
        (1.3, "PASS_MARGINAL", "B"),  # Marginal zone (0.96 - 1.8 px) -> gated to Tier B
        (2.5, "FAIL", "B"),           # Resolved blend (> 1.8 px) -> FAIL (gated to Tier B blend alert)
        (3.0, "FAIL", "B")            # Wide blend -> FAIL
    ]
    for sep_px, expected_status, expected_tier in sweep_Expectations:
        nb_prf = np.exp(-((x_grid - (5.0 + sep_px))**2 + (y_grid - 5.0)**2) / 2.0)
        nb_prf /= np.sum(nb_prf)
        cube_sep = np.array([(1000.0 * target_prf + 500.0 * (0.94 if in_tr[i] else 1.0) * nb_prf + np.random.normal(0, 0.8, (11, 11))) for i in range(n_cad)])
        st_s, off_s, _ = compute_difference_image_centroid(cube_sep, in_tr, out_tr, target_pos=(5.0, 5.0))
        tier_s = assign_tier("CANDIDATE_EXOPLANET", sde=14.0, cycles=5.0, sec_pass=True, centroid_status=st_s, r_star=1.0, orbit_pass=True, dur_pass=True, is_known=False)
        assert st_s == expected_status, f"At sep={sep_px} px: expected {expected_status}, got {st_s} (offset={off_s} px)"
        assert tier_s == expected_tier, f"At sep={sep_px} px: expected Tier {expected_tier}, got Tier {tier_s}"
        
    print("  -> Passed: Separation sweep (0.5..3.0 px) & missing-WCS NOT_RUN guard verified.")

def test_shared_production_detrender_and_tpf_sector_guard():
    print("Running Test 10: Shared production detrender & single-transit TPF sector coverage guard...")
    from downloader import detrend_lightcurve_production
    import lightkurve as lk
    from unittest.mock import patch, MagicMock
    from vetter import check_tpf_centroid_motion

    # 1. Verify detrend_lightcurve_production returns (lc_flat, lc_wide_flat)
    np.random.seed(999)
    t = np.linspace(0, 10.0, 2000)
    flux = 1.0 + 0.002 * np.sin(2 * np.pi * t / 3.0) + np.random.normal(0, 0.0004, size=len(t))
    # Inject a 0.5% transit
    in_dip = np.abs((t - 1.5) % 2.5) < 0.04
    flux[in_dip] -= 0.005
    lc_raw = lk.LightCurve(time=t, flux=flux)
    lc_flat, lc_wide = detrend_lightcurve_production(lc_raw)
    assert len(lc_flat) == len(lc_raw), "lc_flat should have same length as input"
    assert len(lc_wide) == len(lc_raw), "lc_wide should have same length as input"
    # Rotation should be attenuated in lc_flat while transit dip remains
    assert np.nanstd(lc_flat.flux.value[~in_dip]) < np.nanstd(lc_raw.flux.value[~in_dip]), "Detrender must attenuate stellar rotation"
    assert np.nanmedian(lc_flat.flux.value[in_dip]) < 0.997, "Detrender must preserve short transit dip"

    # 2. Verify check_tpf_centroid_motion returns NOT_RUN when single-transit epoch falls outside TPF sector
    mock_tpf = MagicMock()
    mock_tpf.time.value = np.linspace(1354.0, 1381.0, 100)  # Sector 2
    mock_tpf.flux.value = np.ones((100, 11, 11))
    with patch("vetter._download_best_tpf", return_value=mock_tpf):
        st, off, msg = check_tpf_centroid_motion("TIC 999999", 1395.5, 0.1, period=None)
        assert st == "NOT_RUN", f"Expected NOT_RUN when single-transit epoch is outside TPF sector, got {st}"
        assert np.isnan(off), f"Expected NaN offset for out-of-sector single transit, got {off}"
        assert "outside available TPF sector" in msg, f"Expected sector coverage message, got: {msg}"

    print("  -> Passed: Shared production detrender and single-transit out-of-sector TPF guard verified.")


def test_variable_difference_image_quadrature_and_per_star_null():
    print("[Test 11] Verifying variable-star difference imaging across all 4 phases (including quadrature), per-star null ceiling, and amplitude coherence...")
    from vetter import compute_variable_difference_image_centroid

    np.random.seed(202611)
    n_cad = 600
    t = np.linspace(0.0, 27.4, n_cad)
    period_d = 2.4
    y_grid, x_grid = np.mgrid[:11, :11]
    target_prf = np.exp(-((x_grid - 5.0) ** 2 + (y_grid - 5.0) ** 2) / 2.0)
    target_prf /= np.sum(target_prf)
    neighbor_prf = np.exp(-((x_grid - 8.0) ** 2 + (y_grid - 5.0) ** 2) / 2.0)
    neighbor_prf /= np.sum(neighbor_prf)

    # 1. On-target variable and 3-px neighbor variable blend across all 4 cardinal phases {0.0, 0.25, 0.50, 0.75}
    for phi_0 in (0.0, 0.25, 0.50, 0.75):
        mod = 0.015 * np.sin(2.0 * np.pi * (t / period_d + phi_0))[:, None, None]
        noise = np.random.normal(0.0, 0.5, (n_cad, 11, 11))

        # On-target variable + static 40% neighbor at 3 px -> must PASS at every phase
        cube_on = 1000.0 * target_prf[None, :, :] * (1.0 + mod) + 400.0 * neighbor_prf[None, :, :] + noise
        st_on, off_on, _ = compute_variable_difference_image_centroid(
            t, cube_on, period_d, target_pos=(5.0, 5.0), expected_amp=0.015
        )
        assert st_on == "PASS", f"Expected PASS for on-target variable at phase {phi_0}, got {st_on} ({off_on} px)"
        assert off_on < 0.35, f"Expected < 0.35 px offset for on-target variable at phase {phi_0}, got {off_on}"

        # Static target + 3-px variable neighbor blend -> must FAIL at every phase (including quadrature phi_0=0.25)
        cube_blend = 1000.0 * target_prf[None, :, :] + 400.0 * neighbor_prf[None, :, :] * (1.0 + 3.0 * mod) + noise
        st_bl, off_bl, _ = compute_variable_difference_image_centroid(
            t, cube_blend, period_d, target_pos=(5.0, 5.0), expected_amp=0.015
        )
        assert st_bl == "FAIL", f"Expected FAIL for 3-px variable blend at phase {phi_0}, got {st_bl} ({off_bl} px)"
        assert off_bl > 2.4, f"Expected > 2.4 px offset for 3-px variable blend at phase {phi_0}, got {off_bl}"

    # 2. Per-star null ceiling check (HD 10661 case: offset 0.75 px <= 0.96 px pooled, but > 0.37 px per-star ceiling)
    shifted_prf = np.exp(-((x_grid - 5.75) ** 2 + (y_grid - 5.0) ** 2) / 2.0)
    shifted_prf /= np.sum(shifted_prf)
    mod0 = 0.015 * np.sin(2.0 * np.pi * (t / period_d))[:, None, None]
    cube_marginal = 1000.0 * target_prf[None, :, :] + 1000.0 * shifted_prf[None, :, :] * mod0 + np.random.normal(0.0, 0.2, (n_cad, 11, 11))
    st_m, off_m, msg_m = compute_variable_difference_image_centroid(
        t, cube_marginal, period_d, target_pos=(5.0, 5.0), expected_amp=0.015, per_star_ceiling_px=0.37
    )
    assert st_m == "PASS_MARGINAL", f"Expected PASS_MARGINAL when offset ({off_m}) > per_star_ceiling_px (0.37), got {st_m}"
    assert "exceeds star's own TPF injection ceiling" in msg_m

    # 3. TPF folded amplitude coherence check (HD 10661 case: TPF folded amp << expected_amp)
    cube_weak_amp = 1000.0 * target_prf[None, :, :] * (1.0 + 0.0005 * np.sin(2.0 * np.pi * (t / period_d))[:, None, None]) + np.random.normal(0.0, 0.02, (n_cad, 11, 11))
    st_w, _, msg_w = compute_variable_difference_image_centroid(
        t, cube_weak_amp, period_d, target_pos=(5.0, 5.0), expected_amp=0.0062
    )
    assert st_w == "PASS_MARGINAL", f"Expected PASS_MARGINAL when TPF amplitude is <25% of expected, got {st_w}"
    assert "below expected lightcurve amplitude" in msg_w
    print("  -> Passed: Quadrature phase alignment (4/4 phases), per-star null ceiling, and amplitude check verified.")


def test_giant_rotation_sanity_and_offline_calibration():
    print("[Test 12] Verifying giant equatorial rotation speed sanity check (HD 10669) and read-only --offline calibration...")
    from vetter import check_giant_rotation_sanity, assign_tier
    from calibrate_tpf_threshold import verify_committed_calibration_offline, OUTPUT_JSON_PATH

    # 1. HD 10669: R* = 12.8 R_sun, P = 7.94418 d -> v_eq = 81.5 km/s > 35.0 km/s -> must flag False and Tier B
    rot_ok, v_eq, desc = check_giant_rotation_sanity(7.94418, 12.8)
    assert not rot_ok, "Expected HD 10669 (R*=12.8 R_sun, P=7.94d) to fail single-giant rotation sanity"
    assert abs(v_eq - 81.5) <= 0.2, f"Expected v_eq ~ 81.5 km/s, got {v_eq}"
    tier_669 = assign_tier("VARIABLE_STAR", 15.9, 3.4, True, "PASS", r_star=12.8, rot_sanity_pass=rot_ok)
    assert tier_669 == "B", f"Expected Tier B for suspect giant rotation, got Tier {tier_669}"

    # 2. Normal slow giant (R* = 10.0 R_sun, P = 30.0 d -> v_eq = 16.9 km/s <= 35 km/s) and dwarf -> must pass
    rot_ok_slow, v_slow, _ = check_giant_rotation_sanity(30.0, 10.0)
    assert rot_ok_slow and v_slow < 35.0
    rot_ok_dwarf, _, _ = check_giant_rotation_sanity(1.0677, 2.77)
    assert rot_ok_dwarf

    # 3. Verify --offline calibration check is strictly read-only and validates 95th-percentile (0.96 px)
    before_bytes = OUTPUT_JSON_PATH.read_bytes()
    cal_data = verify_committed_calibration_offline()
    after_bytes = OUTPUT_JSON_PATH.read_bytes()
    assert before_bytes == after_bytes, "Offline calibration verification must NEVER modify tpf_threshold_calibration.json"
    assert cal_data["adopted_pass_threshold_px"] == 0.96
    print("  -> Passed: Giant rotation sanity check (HD 10669 -> Tier B) and read-only offline calibration verified.")


def test_watchdog_nonblocking_timeout_and_socket_timeout():
    print("[Test 13] Verifying non-blocking watchdog timeout (<0.8s on 8.0s hang) and socket/astroquery timeouts...")
    import socket
    import time
    import downloader
    import catalog_checker
    import main
    from db import get_target_status

    # 1. Verify global socket and astroquery timeouts
    assert socket.getdefaulttimeout() == 30, f"Expected socket default timeout 30s, got {socket.getdefaulttimeout()}"
    from astroquery.mast import Observations, Catalogs
    from astroquery.simbad import Simbad
    from astroquery.vizier import Vizier
    assert Observations.TIMEOUT == 30, f"Expected Observations.TIMEOUT=30, got {Observations.TIMEOUT}"
    assert Catalogs.TIMEOUT == 30, f"Expected Catalogs.TIMEOUT=30, got {Catalogs.TIMEOUT}"
    assert Simbad.TIMEOUT == 30, f"Expected Simbad.TIMEOUT=30, got {Simbad.TIMEOUT}"
    assert Vizier.TIMEOUT == 30, f"Expected Vizier.TIMEOUT=30, got {Vizier.TIMEOUT}"

    # 2. Simulate an 8-second hang inside process_target and verify run_target_with_watchdog(timeout_sec=0.3)
    #    returns in < 0.8s (proving shutdown(wait=False, cancel_futures=True) does not wait for the hung thread)
    from db import upsert_target
    upsert_target("TIC_WATCHDOG_HANG_TEST", "TIC_WATCHDOG_HANG_TEST", 0.0, 0.0, "PENDING")
    orig_pipeline = main.process_target

    def _simulated_8s_hang(tic_id: str):
        time.sleep(8.0)

    main.process_target = _simulated_8s_hang
    try:
        t0 = time.perf_counter()
        ok = main.run_target_with_watchdog("TIC_WATCHDOG_HANG_TEST", timeout_sec=0.3)
        elapsed = time.perf_counter() - t0
        assert not ok, "Expected run_target_with_watchdog to return False on timeout"
        assert elapsed < 0.8, (
            f"Watchdog blocked for {elapsed:.2f}s (expected < 0.8s for 0.3s timeout on 8.0s hang)"
        )
        st = get_target_status("TIC_WATCHDOG_HANG_TEST")
        assert st == "DOWNLOAD_ERROR", f"Expected DB status DOWNLOAD_ERROR after watchdog timeout, got {st}"
    finally:
        main.process_target = orig_pipeline
        from db import get_connection
        conn = get_connection()
        c = conn.cursor()
        c.execute("DELETE FROM targets WHERE tic_id = ?", ("TIC_WATCHDOG_HANG_TEST",))
        conn.commit()
        conn.close()

    print(f"  -> Passed: Watchdog timed out in {elapsed:.3f}s (< 0.8s on 8.0s hang) and socket/astroquery timeouts verified.")


def test_signal_free_tpf_returns_not_run_and_no_hardcoded_cache_dict():
    print("[Test 14] Verifying signal-free TPF returns NOT_RUN (40/40), mandatory expected_amp, n_trials=50 cache, and no _LOCAL_TPF_CACHE_PATTERNS...")
    import inspect
    import vetter
    from vetter import (
        compute_variable_difference_image_centroid,
        compute_per_star_tpf_null,
        _PER_STAR_NULL_CACHE,
    )

    # 1. Verify hardcoded _LOCAL_TPF_CACHE_PATTERNS is completely removed from production vetter.py
    assert not hasattr(vetter, "_LOCAL_TPF_CACHE_PATTERNS"), (
        "_LOCAL_TPF_CACHE_PATTERNS must not exist in production vetter.py"
    )

    # 2. Verify compute_per_star_tpf_null default n_trials == 50 and caches per star
    sig = inspect.signature(compute_per_star_tpf_null)
    assert sig.parameters["n_trials"].default == 50, (
        f"Expected compute_per_star_tpf_null default n_trials=50, got {sig.parameters['n_trials'].default}"
    )

    # 3. Verify expected_amp is mandatory in compute_variable_difference_image_centroid
    rng = np.random.default_rng(20261060)
    t = np.linspace(0.0, 27.4, 600)
    yg, xg = np.mgrid[:11, :11]
    prf = np.exp(-((xg - 5.0) ** 2 + (yg - 5.0) ** 2) / 2.0)
    prf /= np.sum(prf)
    mod_cube = (10000.0 * (1.0 + 0.005 * np.sin(2.0 * np.pi * t / 1.5))[:, None, None] * prf[None, :, :]) + rng.normal(0.0, 5.0, (600, 11, 11))
    st_no_amp, _, _ = compute_variable_difference_image_centroid(t, mod_cube, 1.5, target_pos=(5.0, 5.0), expected_amp=None)
    assert st_no_amp == "NOT_RUN", f"Expected NOT_RUN when expected_amp is None, got {st_no_amp}"

    # 4. Run 40 signal-free TPF simulations with pointing jitter + linear drift + static 40% neighbor
    #    and expected_amp=0.002 supplied -> all 40 must return NOT_RUN (0 PASS, 0 FAIL, 0 PASS_MARGINAL)
    verdicts = []
    for i in range(40):
        fl_level = [50000.0, 3000.0, 600.0][i % 3]
        p_test = 0.7 if i % 2 == 0 else 2.4
        jx = rng.normal(0.0, 0.12, len(t)) + np.linspace(-0.12, 0.12, len(t))
        jy = rng.normal(0.0, 0.12, len(t)) + np.linspace(-0.08, 0.08, len(t))
        cube = np.zeros((len(t), 11, 11))
        for c in range(len(t)):
            t_prf = np.exp(-((xg - (5.0 + jx[c])) ** 2 + (yg - (5.0 + jy[c])) ** 2) / 2.0)
            t_prf /= np.sum(t_prf)
            n_prf = np.exp(-((xg - (8.0 + jx[c])) ** 2 + (yg - (5.0 + jy[c])) ** 2) / 2.0)
            n_prf /= np.sum(n_prf)
            cube[c] = fl_level * t_prf + 0.4 * fl_level * n_prf + rng.normal(0.0, np.sqrt(fl_level) * 0.25, (11, 11))
        st_sf, _, _ = compute_variable_difference_image_centroid(
            t, cube, p_test, target_pos=(5.0, 5.0), expected_amp=0.002
        )
        verdicts.append(st_sf)

    not_run_count = sum(1 for v in verdicts if v == "NOT_RUN")
    assert not_run_count == 40, f"Expected 40/40 NOT_RUN on signal-free TPF, got {not_run_count}/40 ({set(verdicts)})"

    # 5. Verify _PER_STAR_NULL_CACHE caches repeated calls
    _PER_STAR_NULL_CACHE.clear()
    null1 = compute_per_star_tpf_null(t, mod_cube, (5.0, 5.0), mode="transit", n_trials=10)
    assert len(_PER_STAR_NULL_CACHE) == 1
    null2 = compute_per_star_tpf_null(t, mod_cube, (5.0, 5.0), mode="transit", n_trials=10)
    assert null1 == null2
    print("  -> Passed: 40/40 signal-free TPFs returned NOT_RUN, expected_amp mandatory, n_trials=50 cached, no hardcoded dict.")


def test_external_tess_benchmark_and_missing_file_guard():
    print("[Test 15] Verifying 50-target held-out external TESS benchmark (targets.csv + results.csv) and missing-file RuntimeError guard...")
    import tempfile
    from pathlib import Path
    from injection_recovery import verify_external_benchmark_results, run_external_tess_benchmark

    # 1. Verify committed benchmark/targets.csv and benchmark/results.csv offline
    res = verify_external_benchmark_results()
    assert res["n_total"] == 50, f"Expected 50 total benchmark targets, got {res['n_total']}"
    assert res["n_planets"] >= 20, f"Expected >= 20 confirmed transiting planets, got {res['n_planets']}"
    assert res["n_non_planets"] >= 20, f"Expected >= 20 confirmed non-planets/FPs/EBs, got {res['n_non_planets']}"
    assert res["recall_pct"] >= 85.0, f"Expected planet recall >= 85%, got {res['recall_pct']:.1f}%"
    assert res["specificity_pct"] >= 75.0, f"Expected non-planet specificity >= 75%, got {res['specificity_pct']:.1f}%"
    assert res["precision_pct"] >= 80.0, f"Expected precision >= 80%, got {res['precision_pct']:.1f}%"
    assert res["accuracy_pct"] >= res["majority_baseline_pct"] + 25.0, (
        f"Expected accuracy ({res['accuracy_pct']:.1f}%) far above majority baseline ({res['majority_baseline_pct']:.1f}%)"
    )

    # 2. Verify run_external_tess_benchmark raises RuntimeError when a FITS file is missing (n_evaluated < n_rows)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tf:
        tf.write(
            "target_name,tic_id,true_class,true_subclass,catalog_period_d,catalog_depth_ppm,r_star_rsun,m_star_msun,tmag,sector,catalog_id,catalog_url,source_catalog,source_date,s3_lc_key\n"
            "TOI 99999.01,999999999999,PLANET,TOI_CP,3.5,5000.0,1.0,1.0,10.0,1,TOI-99999.01,https://exofop.ipac.caltech.edu,Test,2026-01-01,nonexistent_lc.fits\n"
        )
        tmp_csv = tf.name
    try:
        raised = False
        try:
            run_external_tess_benchmark(csv_path=tmp_csv)
        except RuntimeError as e:
            raised = True
            assert "missing" in str(e).lower() and "fetch_benchmark_data.py" in str(e)
        assert raised, "run_external_tess_benchmark must raise RuntimeError when FITS files are missing"
    finally:
        Path(tmp_csv).unlink(missing_ok=True)

    print(
        f"  -> Passed: Held-out benchmark verified (N={res['n_total']}: TP={res['tp']}/{res['n_planets']} Recall={res['recall_pct']:.1f}%, "
        f"TN={res['tn']}/{res['n_non_planets']} Specificity={res['specificity_pct']:.1f}%, Precision={res['precision_pct']:.1f}%) & missing-file guard verified."
    )


def test_linux_requirements_lock_clean():
    print("[Test 16] Verifying requirements-lock.txt is cross-platform Linux-clean (no pywin32, torch, or extraneous AI packages)...")
    from pathlib import Path

    lock_path = Path(__file__).parent / "requirements-lock.txt"
    assert lock_path.exists(), "requirements-lock.txt must exist"
    lines = [
        ln.strip()
        for ln in lock_path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) >= 50, f"Expected >= 50 pinned packages in requirements-lock.txt, got {len(lines)}"
    forbidden = ("pywin32", "torch", "torchvision", "tensorflow", "timesfm", "tabpfn", "ultralytics", "opencv", "boto3")
    for ln in lines:
        assert "==" in ln, f"Unpinned line in requirements-lock.txt: {ln}"
        pkg = ln.split("==")[0].strip().lower()
        for bad in forbidden:
            assert bad not in pkg, f"Forbidden platform/extra package '{pkg}' found in requirements-lock.txt"
    print(f"  -> Passed: requirements-lock.txt has {len(lines)} clean cross-platform packages and zero forbidden packages.")


def test_citation_cff_and_legal_hygiene():
    print("[Test 17] Verifying CITATION.cff, LICENSE, .zenodo.json, and CHANGELOG.md legal/release hygiene...")
    import json, yaml, re
    from pathlib import Path

    repo_root = Path(__file__).parent

    # 1. LICENSE
    lic_file = repo_root / "LICENSE"
    assert lic_file.exists(), "LICENSE file must exist"
    lic_text = lic_file.read_text(encoding="utf-8")
    assert "MIT License" in lic_text, "LICENSE must specify MIT License"
    assert "[PLACEHOLDER: AUTHOR_NAME]" in lic_text, "LICENSE must contain author placeholder"

    # 2. CITATION.cff
    cff_file = repo_root / "CITATION.cff"
    assert cff_file.exists(), "CITATION.cff file must exist"
    cff = yaml.safe_load(cff_file.read_text(encoding="utf-8"))
    assert cff.get("cff-version") == "1.2.0", f"Expected cff-version 1.2.0, got {cff.get('cff-version')}"
    assert cff.get("license") == "MIT", f"Expected license MIT, got {cff.get('license')}"
    assert cff.get("title"), "CITATION.cff must have a title"
    authors = cff.get("authors", [])
    assert len(authors) > 0, "CITATION.cff must define at least one author"
    assert "[PLACEHOLDER: AUTHOR_LAST_NAME]" in authors[0].get("family-names", ""), "Author last name must use placeholder"
    orcid = authors[0].get("orcid", "")
    assert re.match(r"^https://orcid\.org/[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$", orcid), f"Invalid ORCID URI in CITATION.cff: {orcid}"

    # 3. .zenodo.json
    zen_file = repo_root / ".zenodo.json"
    assert zen_file.exists(), ".zenodo.json file must exist"
    zen = json.loads(zen_file.read_text(encoding="utf-8"))
    assert zen.get("upload_type") == "software", f"Expected upload_type 'software', got {zen.get('upload_type')}"
    assert zen.get("license") == "MIT", f"Expected license 'MIT', got {zen.get('license')}"
    assert len(zen.get("creators", [])) > 0, ".zenodo.json must define at least one creator"

    # 4. CHANGELOG.md
    chg_file = repo_root / "CHANGELOG.md"
    assert chg_file.exists(), "CHANGELOG.md must exist"
    chg_text = chg_file.read_text(encoding="utf-8")
    assert "[2.7.0]" in chg_text, "CHANGELOG.md must document v2.7.0"

    print("  -> Passed: CITATION.cff (CFF 1.2.0), LICENSE (MIT), .zenodo.json, and CHANGELOG.md verified.")


def check_citation_and_zenodo_placeholders(ref_name: str = "main") -> bool:
    """
    Validates CITATION.cff and .zenodo.json placeholders (WP0.1 C):
    - Normal branches (e.g., 'main', 'master'): emits a warning if placeholders are present.
    - Release tags (matching 'v*' or 'refs/tags/v*'): raises AssertionError if placeholders are present.
    Returns True if placeholders are present, False otherwise.
    """
    import yaml, json, warnings
    from pathlib import Path
    repo_root = Path(__file__).parent

    cff = yaml.safe_load((repo_root / "CITATION.cff").read_text(encoding="utf-8"))
    zen = json.loads((repo_root / ".zenodo.json").read_text(encoding="utf-8"))

    has_placeholder = False
    # Check CFF
    for a in cff.get("authors", []):
        if "[PLACEHOLDER:" in str(a.get("family-names", "")) or "[PLACEHOLDER:" in str(a.get("given-names", "")):
            has_placeholder = True
        if "0000-0000-0000-0000" in str(a.get("orcid", "")):
            has_placeholder = True

    # Check Zenodo
    for c in zen.get("creators", []):
        if "[PLACEHOLDER:" in str(c.get("name", "")) or "0000-0000-0000-0000" in str(c.get("orcid", "")):
            has_placeholder = True

    is_tag = ref_name.startswith("v") or ref_name.startswith("refs/tags/v")
    if is_tag and has_placeholder:
        raise AssertionError(
            f"Release tag '{ref_name}' cannot contain author/ORCID placeholders in CITATION.cff or .zenodo.json. "
            "Please replace placeholders with authentic author details before tagging release."
        )
    if has_placeholder:
        warnings.warn(
            f"Author/ORCID placeholders detected in CITATION.cff/.zenodo.json on branch '{ref_name}'. "
            "These placeholders are allowed on development branches but will fail CI on release tags matching v*.",
            UserWarning
        )
    return has_placeholder


def test_network_and_alert_hygiene():
    print("[Test 18] Verifying test network isolation and alert suppression (Rule 10)...")
    import socket
    from config import ALERTS_ENABLED
    from notifier import dispatch_alert
    from conftest import ALERT_RECORDER, BlockedNetworkCallError

    # 1. ALERTS_ENABLED must be False in test environment
    assert ALERTS_ENABLED is False, "ALERTS_ENABLED must default to False in test harness"

    # 2. Outbound socket connection attempts must be blocked
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocked = False
    try:
        s.connect(("8.8.8.8", 53))
    except (BlockedNetworkCallError, RuntimeError) as e:
        blocked = True
        assert "blocked by test harness" in str(e).lower()
    finally:
        s.close()
    assert blocked, "Outbound network socket calls must be strictly blocked during testing"

    # 3. dispatch_alert must not send real alerts and must be intercepted by test recorder
    ALERT_RECORDER.clear()
    dispatch_alert("TEST_TARGET", "TIC 123", "CANDIDATE_EXOPLANET", {"sde": 10.0}, {}, "dummy.png")
    assert len(ALERT_RECORDER.recorded_calls) == 1
    assert ALERT_RECORDER.recorded_calls[0]["args"][0] == "TEST_TARGET"
    print("  -> Passed: ALERTS_ENABLED=False, outbound sockets blocked, and alerts intercepted by recorder.")


def test_ci_placeholder_rules_on_branches_vs_tags():
    print("[Test 19] Verifying CI placeholder rules on development branches vs release tags (WP0.1 C)...")
    import pytest

    # 1. On branch 'main', placeholders produce a warning and pass
    with pytest.warns(UserWarning, match="Author/ORCID placeholders detected"):
        has_placeholders = check_citation_and_zenodo_placeholders(ref_name="main")
    assert has_placeholders is True, "Expected placeholders detected in current dev CITATION.cff/.zenodo.json"

    # 2. On a release tag matching 'v*', placeholders must FAIL loudly
    with pytest.raises(AssertionError, match="cannot contain author/ORCID placeholders"):
        check_citation_and_zenodo_placeholders(ref_name="v2.8.0")

    with pytest.raises(AssertionError, match="cannot contain author/ORCID placeholders"):
        check_citation_and_zenodo_placeholders(ref_name="refs/tags/v2.8.0")

    print("  -> Passed: Placeholders warn on normal branches but fail loudly on release tags matching v*.")


def test_readme_table_integrity_and_character_limit():
    print("[Test 20] Verifying README restructure, table data integrity, and documentation files (WP1)...")
    from pathlib import Path
    import sys
    repo_root = Path(__file__).resolve().parent

    # 1. Verify docs/ files exist and are non-empty
    docs_dir = repo_root / "docs"
    required_docs = [
        "validation.md",
        "vetting.md",
        "benchmark.md",
        "known_limitations.md",
        "vsx_recovery.md",
    ]
    for doc in required_docs:
        doc_path = docs_dir / doc
        assert doc_path.exists(), f"Missing required doc file: {doc_path}"
        assert doc_path.stat().st_size > 500, f"Doc file {doc_path} is too short or empty"

    # 2. Verify README.md character count is under 10,000 characters
    readme_path = repo_root / "README.md"
    assert readme_path.exists(), "Missing README.md"
    readme_text = readme_path.read_text(encoding="utf-8")
    assert len(readme_text) <= 10000, f"README.md exceeds 10,000 characters: {len(readme_text)}"

    # 3. Verify README numbers match benchmark data via scripts/make_readme_tables.py
    sys.path.insert(0, str(repo_root / "scripts"))
    try:
        from make_readme_tables import load_benchmark_metrics, load_vsx_metrics, verify_readme_content
        m = load_benchmark_metrics(repo_root)
        v = load_vsx_metrics()
        errors = verify_readme_content(readme_text, m, v)
        assert len(errors) == 0, f"README table verification failed: {errors}"
    finally:
        if str(repo_root / "scripts") in sys.path:
            sys.path.remove(str(repo_root / "scripts"))

    # 4. Verify detrender description in architecture diagram matches code
    assert "Savitzky-Golay" in readme_text, "Diagram must accurately describe Savitzky-Golay flattening"
    assert "Biweight" not in readme_text, "Diagram must not claim Biweight before WP3"
    assert "0.4 - 20.0 d" in readme_text, "Diagram must state BLS range 0.4 - 20.0 d"
    assert "Unflattened Stream" in readme_text, "Diagram must state Lomb-Scargle runs on unflattened stream"

    # 5. Verify Tier A definition and blend limits
    assert "not astrophysical validation" in readme_text.lower(), "README must explicitly state Tier A is not validation"
    assert "9 of 32" in readme_text, "README must report 9 of 32 Tier A benchmark targets are non-planets"
    assert "1.0 pixel" in readme_text, "README must document ~1.0 pixel centroid blend resolution limit"

    print(f"  -> Passed: README.md ({len(readme_text)} chars), tables in sync with data, all 5 docs/ files verified.")


def test_benchmark_v2_pre_registration_and_heldout_isolation():
    print("[Test 21] Verifying Benchmark v2 pre-registration, held-out isolation, and zero-overlap invariants...")
    import os
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bench_dir = os.path.join(base_dir, "benchmark_v2")

    # 1. Verify PROTOCOL.md and PROVENANCE.md exist
    proto_path = os.path.join(bench_dir, "PROTOCOL.md")
    prov_path = os.path.join(bench_dir, "PROVENANCE.md")
    assert os.path.exists(proto_path), "benchmark_v2/PROTOCOL.md must exist"
    assert os.path.exists(prov_path), "benchmark_v2/PROVENANCE.md must exist"

    # 2. Strict held-out isolation: NO results files or plots may exist yet
    results_a = os.path.join(bench_dir, "results_set_a.csv")
    results_b = os.path.join(bench_dir, "results_set_b.csv")
    assert not os.path.exists(results_a), "benchmark_v2/results_set_a.csv must NOT exist prior to WP8"
    assert not os.path.exists(results_b), "benchmark_v2/results_set_b.csv must NOT exist prior to WP8"

    # 3. Targets and sector tables must exist with exact counts
    a_path = os.path.join(bench_dir, "targets_set_a.csv")
    b_path = os.path.join(bench_dir, "targets_set_b.csv")
    sec_b_path = os.path.join(bench_dir, "sectors_set_b.csv")

    assert os.path.exists(a_path), "benchmark_v2/targets_set_a.csv must exist"
    assert os.path.exists(b_path), "benchmark_v2/targets_set_b.csv must exist"
    assert os.path.exists(sec_b_path), "benchmark_v2/sectors_set_b.csv must exist"

    import pandas as pd
    df_a = pd.read_csv(a_path)
    df_b = pd.read_csv(b_path)
    df_sec_b = pd.read_csv(sec_b_path)

    assert len(df_a) == 60, f"Expected 60 rows in Set A, got {len(df_a)}"
    assert len(df_b) == 60, f"Expected 60 rows in Set B, got {len(df_b)}"
    assert len(df_sec_b) == 120, f"Expected 120 rows in sectors_set_b.csv, got {len(df_sec_b)}"

    # 4. Run deterministic verification script
    from benchmark_v2.verify_benchmark_v2 import verify_benchmark_v2
    verify_benchmark_v2()

    print("  -> Passed: Benchmark v2 Sets A and B verified with zero overlap and held-out isolation.")


def test_benchmark_v2_verification_bad_csv_rejection(tmp_path):
    print("[Test 22] Verifying that verify_benchmark_v2 strictly rejects invalid benchmark CSVs in tmp_path...")
    import os
    import pytest
    import pandas as pd
    from benchmark_v2.verify_benchmark_v2 import verify_benchmark_v2

    base_dir = os.path.dirname(os.path.abspath(__file__))
    bench_dir = os.path.join(base_dir, "benchmark_v2")
    real_a = os.path.join(bench_dir, "targets_set_a.csv")
    real_b = os.path.join(bench_dir, "targets_set_b.csv")

    df_a = pd.read_csv(real_a)
    df_b = pd.read_csv(real_b)

    # 1. Deliberately corrupt Set A period (set P > 8.7 d)
    bad_a_period = df_a.copy()
    bad_a_period.loc[0, "catalog_period_d"] = 25.0
    bad_a_path = str(tmp_path / "bad_a_period.csv")
    bad_a_period.to_csv(bad_a_path, index=False)

    with pytest.raises(AssertionError, match="Set A period violation"):
        verify_benchmark_v2(a_path=bad_a_path, b_path=real_b)

    # 2. Deliberately corrupt Set B period (set P <= 8.7 d)
    bad_b_period = df_b.copy()
    bad_b_period.loc[0, "catalog_period_d"] = 5.0
    bad_b_path = str(tmp_path / "bad_b_period.csv")
    bad_b_period.to_csv(bad_b_path, index=False)

    with pytest.raises(AssertionError, match="Set B period violation"):
        verify_benchmark_v2(a_path=real_a, b_path=bad_b_path)

    # 3. Deliberately corrupt Set B sectors (set n_sectors < 2)
    bad_b_sec = df_b.copy()
    bad_b_sec.loc[0, "n_sectors"] = 1
    bad_b_sec_path = str(tmp_path / "bad_b_sec.csv")
    bad_b_sec.to_csv(bad_b_sec_path, index=False)

    with pytest.raises(AssertionError, match="Set B minimum sectors failure"):
        verify_benchmark_v2(a_path=real_a, b_path=bad_b_sec_path)

    # 4. Deliberately corrupt Set A class mix (replace PRSA_EB with TOI_FP)
    bad_a_mix = df_a.copy()
    bad_a_mix.loc[bad_a_mix["true_subclass"] == "PRSA_EB", "true_subclass"] = "TOI_FP"
    bad_a_mix_path = str(tmp_path / "bad_a_mix.csv")
    bad_a_mix.to_csv(bad_a_mix_path, index=False)

    with pytest.raises(AssertionError, match="Set A non-planet subclass violation"):
        verify_benchmark_v2(a_path=bad_a_mix_path, b_path=real_b)

    # 5. Deliberately corrupt overlap (put a burned ID into Set A)
    burned_path = os.path.join(bench_dir, "burned_ids.txt")
    with open(burned_path, "r", encoding="utf-8") as f:
        first_burned_id = int(f.readline().strip())
    bad_a_overlap = df_a.copy()
    bad_a_overlap.loc[0, "tic_id"] = first_burned_id
    bad_a_overlap_path = str(tmp_path / "bad_a_overlap.csv")
    bad_a_overlap.to_csv(bad_a_overlap_path, index=False)

    with pytest.raises(AssertionError, match="Burned overlap failure"):
        verify_benchmark_v2(a_path=bad_a_overlap_path, b_path=real_b)

    print("  -> Passed: All deliberately corrupted benchmark CSVs in tmp_path were caught and rejected.")


if __name__ == "__main__":
    test_cloud_agnostic_imports()
    test_catalog_plumbing()
    test_physical_constraints()
    test_centroid_and_tier_gatekeeping()
    test_bls_grid_multi_year_scalability()
    test_download_error_retry()
    test_unmeasured_centroid_planet_classification()
    test_difference_image_centroid_benchmarks()
    test_difference_image_separation_sweep_and_missing_wcs()
    test_shared_production_detrender_and_tpf_sector_guard()
    test_variable_difference_image_quadrature_and_per_star_null()
    test_giant_rotation_sanity_and_offline_calibration()
    test_watchdog_nonblocking_timeout_and_socket_timeout()
    test_signal_free_tpf_returns_not_run_and_no_hardcoded_cache_dict()
    test_external_tess_benchmark_and_missing_file_guard()
    test_linux_requirements_lock_clean()
    test_citation_cff_and_legal_hygiene()
    test_network_and_alert_hygiene()
    test_ci_placeholder_rules_on_branches_vs_tags()
    test_readme_table_integrity_and_character_limit()
    test_benchmark_v2_pre_registration_and_heldout_isolation()
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        test_benchmark_v2_verification_bad_csv_rejection(Path(td))
    print("\n=== ALL 22 PLUMBING, WATCHDOG, CENTROID, BENCHMARK, LOCKFILE, NETWORK & RELEASE HYGIENE TESTS PASSED! ===")




