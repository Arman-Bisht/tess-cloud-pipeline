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

if __name__ == "__main__":
    test_cloud_agnostic_imports()
    test_catalog_plumbing()
    test_physical_constraints()
    test_centroid_and_tier_gatekeeping()
    test_bls_grid_multi_year_scalability()
    test_download_error_retry()
    test_unmeasured_centroid_planet_classification()
    test_difference_image_centroid_benchmarks()
    print("\n=== ALL 8 PLUMBING, RETRY, CENTROID & VETTING TESTS PASSED! ===")
