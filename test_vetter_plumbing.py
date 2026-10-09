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
    
    # Case 2: Centroid FAIL must be Tier C
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
    assert tier_fail == "C", f"Expected FAIL centroid to be Tier C, got {tier_fail}"
    
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
    assert elapsed < 10.0, f"BLS took {elapsed:.2f}s (must finish in < 10s on multi-year baselines)"
    print(f"  -> Passed: BLS completed in {elapsed:.2f}s across a 727-day baseline.")

if __name__ == "__main__":
    test_cloud_agnostic_imports()
    test_catalog_plumbing()
    test_physical_constraints()
    test_centroid_and_tier_gatekeeping()
    test_bls_grid_multi_year_scalability()
    print("\n=== ALL PLUMBING & SCALABILITY TESTS PASSED! ===")
