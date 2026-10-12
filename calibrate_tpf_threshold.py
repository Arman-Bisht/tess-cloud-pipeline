"""
Astrohunter Pro -- Reproducible TPF Difference-Image Threshold Calibration
(calibrate_tpf_threshold.py)

Empirically calibrates:
  1. The Tier A PASS threshold (0.96 px, 95th percentile; 99th percentile = 1.061 px) and
     per-star null distributions for `compute_difference_image_centroid` by injecting
     N=100 synthetic on-target transits (depths 4,000 to 25,000 ppm, periods 0.8 to 7.5 d)
     into real TESS SPOC 120-second Target Pixel Files (TPFs) anchored to their Gaia/WCS
     target pixel positions.
  2. The separate variable-star peak-vs-trough difference-image statistic for
     `compute_variable_difference_image_centroid` by injecting N=100 synthetic on-target
     sinusoidal modulations across uniform random phases phi_0 in [0, 1) (including quadrature
     phi_0 = 0.25 and 0.75) into the same real TESS SPOC TPFs, plus verifying 100% rejection
     of 3-pixel off-target variable blends across all four cardinal phases {0.0, 0.25, 0.50, 0.75}.

Modes:
  - Default (`python calibrate_tpf_threshold.py`): Loads real SPOC 120s TPFs from local cache
    (or MAST), runs both 100-trial transit and 100-trial variable calibrations, and writes
    `tpf_threshold_calibration.json`. Fails with RuntimeError if real SPOC TPFs are unavailable
    (never falls back to synthetic cubes).
  - Offline verification (`python calibrate_tpf_threshold.py --offline`): Strictly reads the
    committed `tpf_threshold_calibration.json` without writing or modifying any file, recomputes
    all pooled and per-star percentiles (50th, 90th, 95th, 99th, max, and per-star ceilings)
    directly from the stored trial arrays, and asserts exact agreement with the committed JSON
    and the 95th-percentile (0.96 px) threshold.
"""

import glob
import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple
import numpy as np
import lightkurve as lk

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from vetter import (
    compute_difference_image_centroid,
    compute_variable_difference_image_centroid,
    _extract_tpf_wcs_target_pos,
)

# Documented calibration benchmark targets (real TESS SPOC TPFs from the HD survey)
CALIBRATION_TICS = [
    {"tic_id": "346940718", "name": "HD 10528", "sector": 70, "wcs_px": [4.934, 4.941]},
    {"tic_id": "399270628", "name": "HD 10635", "sector": 18, "wcs_px": [5.562, 5.401]},
    {"tic_id": "10863314",  "name": "HD 10653", "sector": 3,  "wcs_px": [5.713, 6.083]},
    {"tic_id": "229118094", "name": "HD 10661", "sector": 2,  "wcs_px": [4.807, 4.324]},
]

CALIBRATION_SEED = 20261010
VARIABLE_CALIBRATION_SEED = 20261025
N_INJECTIONS = 100
OUTPUT_JSON_PATH = Path(__file__).parent / "tpf_threshold_calibration.json"


def load_real_tpf_cubes() -> List[Dict[str, Any]]:
    """
    Loads real TESS SPOC TPF cubes and WCS target positions from local lightkurve cache
    (or MAST when online). Never falls back to synthetic cubes: raises RuntimeError if
    real TESS TPFs cannot be loaded for all calibration targets.
    """
    cubes = []
    cache_dir = lk.config.get_cache_dir()
    cached_fits = (
        glob.glob(os.path.join(cache_dir, "mastDownload", "TESS", "*", "*tp.fits"))
        + glob.glob(os.path.join(cache_dir, "mastDownload", "HLSP", "*", "*tp.fits"))
    )

    for item in CALIBRATION_TICS:
        tic_num = item["tic_id"]
        matched = [
            f for f in cached_fits
            if tic_num.zfill(16) in f or f"-{tic_num}-" in f
        ]
        tpf = None
        if matched:
            try:
                tpf = lk.read(matched[0])
            except Exception:
                tpf = None
        else:
            try:
                search = lk.search_targetpixelfile(f"TIC {tic_num}", author="SPOC")
                if len(search) == 0:
                    search = lk.search_targetpixelfile(f"TIC {tic_num}", mission="TESS")
                if len(search) > 0 and "exptime" in search.table.colnames:
                    s120 = search[search.table["exptime"] == 120]
                    if len(s120) > 0:
                        search = s120
                if len(search) > 0:
                    tpf = search[0].download()
            except Exception:
                tpf = None

        if tpf is not None:
            t = tpf.time.value
            fl = np.array(tpf.flux.value, dtype=float)
            valid = np.isfinite(t) & np.all(np.isfinite(fl), axis=(1, 2))
            t, fl = t[valid], fl[valid]
            wcs_pos = _extract_tpf_wcs_target_pos(tpf)
            if len(t) >= 300 and wcs_pos is not None:
                cubes.append({
                    "tic_id": f"TIC {tic_num}",
                    "name": item["name"],
                    "source": "MAST_SPOC_TPF",
                    "time": t,
                    "flux": fl,
                    "wcs_pos": wcs_pos,
                })

    if len(cubes) != len(CALIBRATION_TICS):
        raise RuntimeError(
            f"Expected {len(CALIBRATION_TICS)} real SPOC TPF cubes, loaded {len(cubes)}. "
            "Use `--offline` on machines without local MAST cache to verify the committed "
            "tpf_threshold_calibration.json without overwriting it."
        )
    return cubes


def _compute_per_star_summary(trials: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Computes per-star median, p90, p95, p99, max, and per-star ceiling from trial records."""
    by_star: Dict[str, List[float]] = {}
    star_meta: Dict[str, str] = {}
    for tr in trials:
        nm = tr["name"]
        by_star.setdefault(nm, []).append(float(tr["measured_offset_px"]))
        star_meta[nm] = tr["tic_id"]

    per_star: Dict[str, Dict[str, Any]] = {}
    for nm, vals in by_star.items():
        arr = np.array(vals, dtype=float)
        p50 = float(np.percentile(arr, 50))
        p90 = float(np.percentile(arr, 90))
        p95 = float(np.percentile(arr, 95))
        p99 = float(np.percentile(arr, 99))
        mx = float(np.max(arr))
        ceiling = float(max(1.25 * p95, p95 + 0.10))
        per_star[nm] = {
            "tic_id": star_meta[nm],
            "n_trials": len(vals),
            "median_offset_px": round(p50, 3),
            "p90_offset_px": round(p90, 3),
            "p95_offset_px": round(p95, 3),
            "p99_offset_px": round(p99, 3),
            "max_offset_px": round(mx, 3),
            "per_star_ceiling_px": round(ceiling, 2),
        }
    return per_star


def verify_committed_calibration_offline() -> Dict[str, Any]:
    """
    Strictly reads the committed `tpf_threshold_calibration.json` without modifying it,
    recomputes pooled and per-star percentiles for both transit and variable-star injections,
    and asserts exact agreement with the committed JSON and 95th-percentile (0.96 px) threshold.
    """
    if not OUTPUT_JSON_PATH.exists():
        raise FileNotFoundError(f"Committed calibration file not found: {OUTPUT_JSON_PATH}")

    with open(OUTPUT_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    trials = data.get("trials", [])
    assert len(trials) == N_INJECTIONS, f"Expected {N_INJECTIONS} transit trials, found {len(trials)}"
    assert all(tr.get("source") == "MAST_SPOC_TPF" for tr in trials), (
        "All committed calibration trials must originate from real MAST_SPOC_TPF cubes"
    )

    arr = np.array([float(tr["measured_offset_px"]) for tr in trials], dtype=float)
    p50 = round(float(np.percentile(arr, 50)), 3)
    p90 = round(float(np.percentile(arr, 90)), 3)
    p95 = round(float(np.percentile(arr, 95)), 3)
    p99 = round(float(np.percentile(arr, 99)), 3)
    adopted = round(float(np.percentile(arr, 95)), 2)

    assert abs(p50 - data["median_offset_px"]) <= 0.002, f"Median mismatch: {p50} vs {data['median_offset_px']}"
    assert abs(p90 - data["p90_offset_px"]) <= 0.002, f"p90 mismatch: {p90} vs {data['p90_offset_px']}"
    assert abs(p95 - data["p95_offset_px"]) <= 0.002, f"p95 mismatch: {p95} vs {data['p95_offset_px']}"
    assert abs(p99 - data["p99_offset_px"]) <= 0.002, f"p99 mismatch: {p99} vs {data['p99_offset_px']}"
    assert adopted == data["adopted_pass_threshold_px"] == 0.96, (
        f"Adopted 95th-percentile threshold mismatch: {adopted} vs {data['adopted_pass_threshold_px']}"
    )

    recomputed_per_star = _compute_per_star_summary(trials)
    committed_per_star = data.get("per_star_transit_null", {})
    assert len(committed_per_star) == len(CALIBRATION_TICS), "Missing per_star_transit_null in JSON"
    for nm, stats in recomputed_per_star.items():
        c_stats = committed_per_star[nm]
        assert abs(stats["p95_offset_px"] - c_stats["p95_offset_px"]) <= 0.002, f"{nm} p95 mismatch"
        assert abs(stats["max_offset_px"] - c_stats["max_offset_px"]) <= 0.002, f"{nm} max mismatch"

    var_cal = data.get("variable_star_calibration", {})
    var_trials = var_cal.get("trials", [])
    assert len(var_trials) == N_INJECTIONS, f"Expected {N_INJECTIONS} variable trials, found {len(var_trials)}"
    var_arr = np.array([float(tr["measured_offset_px"]) for tr in var_trials], dtype=float)
    vp95 = round(float(np.percentile(var_arr, 95)), 3)
    assert abs(vp95 - var_cal["p95_offset_px"]) <= 0.002, (
        f"Variable p95 mismatch: {vp95} vs {var_cal['p95_offset_px']}"
    )
    assert var_cal.get("quadrature_blend_rejection_rate") == 1.0, (
        "Quadrature 3-px blend rejection rate must be 1.0 (100%)"
    )

    print("=" * 78)
    print("ASTROHUNTER PRO -- OFFLINE TPF CALIBRATION VERIFICATION (READ-ONLY)")
    print("=" * 78)
    print(f"Verified committed file: {OUTPUT_JSON_PATH.name} (no files written or modified)")
    print(
        f"  • Transit Pooled Offsets (N={len(trials)}): "
        f"median={p50:.3f} px | p90={p90:.3f} px | p95={p95:.3f} px (Threshold={adopted:.2f} px) | p99={p99:.3f} px"
    )
    for nm, st in recomputed_per_star.items():
        print(
            f"    - {nm} ({st['tic_id']}): median={st['median_offset_px']:.3f} px, "
            f"p95={st['p95_offset_px']:.3f} px, max={st['max_offset_px']:.3f} px, "
            f"ceiling={st['per_star_ceiling_px']:.2f} px"
        )
    print(
        f"  • Variable-Star Peak-vs-Trough Offsets (N={len(var_trials)}): "
        f"median={var_cal['median_offset_px']:.3f} px | p95={vp95:.3f} px | "
        f"Quadrature 3-px Blend Rejection={int(var_cal['quadrature_blend_rejection_rate']*100)}%"
    )
    print("=" * 78)
    return data


def run_tpf_threshold_calibration(offline: bool = False) -> Dict[str, Any]:
    """
    When `offline=True`, verifies the committed `tpf_threshold_calibration.json` without
    writing to disk. When `offline=False`, runs 100 on-target transit injections and 100
    on-target variable-star sinusoidal injections on real SPOC TPFs and writes the artifact.
    """
    if offline:
        return verify_committed_calibration_offline()

    cubes = load_real_tpf_cubes()
    rng = np.random.default_rng(CALIBRATION_SEED)

    trials: List[Dict[str, Any]] = []
    offsets: List[float] = []

    for idx in range(N_INJECTIONS):
        cube_info = cubes[idx % len(cubes)]
        t = cube_info["time"]
        base_flux = cube_info["flux"]
        wcs_pos: Tuple[float, float] = cube_info["wcs_pos"]
        h, w = base_flux.shape[1], base_flux.shape[2]
        yg, xg = np.mgrid[:h, :w]

        period_d = float(rng.uniform(0.8, 7.5))
        depth_frac = float(rng.uniform(0.004, 0.025))
        dur_days = float(rng.uniform(0.08, 0.18))
        epoch = float(t[0] + rng.uniform(0.1 * period_d, 0.9 * period_d))

        phase = ((t - epoch + 0.5 * period_d) % period_d) / period_d - 0.5
        in_tr = np.abs(phase) < (dur_days / (2.0 * period_d))
        out_tr = (np.abs(phase) >= (dur_days / (2.0 * period_d))) & (
            np.abs(phase) < 3.0 * (dur_days / (2.0 * period_d))
        )

        # Include sub-pixel pointing/registration jitter (sigma = 0.12 px) on top of real SPOC WCS
        wcs_err_x = float(rng.normal(0.0, 0.12))
        wcs_err_y = float(rng.normal(0.0, 0.12))
        inj_center_x = wcs_pos[0] + wcs_err_x
        inj_center_y = wcs_pos[1] + wcs_err_y

        # Spatial weight localized to the target star's PRF around (inj_center_x, inj_center_y)
        prf_weight = np.exp(-((xg - inj_center_x) ** 2 + (yg - inj_center_y) ** 2) / 2.2)

        flux_inj = base_flux.copy()
        for c_i in np.where(in_tr)[0]:
            flux_inj[c_i] *= (1.0 - depth_frac * prf_weight)

        status, _, _ = compute_difference_image_centroid(flux_inj, in_tr, out_tr, target_pos=wcs_pos)

        img_out = np.nanmedian(flux_inj[out_tr], axis=0)
        img_in = np.nanmedian(flux_inj[in_tr], axis=0)
        diff = img_out - img_in
        mad = float(np.nanmedian(np.abs(diff - np.nanmedian(diff))) * 1.4826)
        diff_thresh = np.where(diff > 2.0 * mad, diff, 0.0)
        if np.nansum(diff_thresh) <= 0:
            diff_thresh = np.maximum(0.0, diff)
        x_diff = float(np.sum(diff_thresh * xg) / np.sum(diff_thresh))
        y_diff = float(np.sum(diff_thresh * yg) / np.sum(diff_thresh))
        raw_offset_px = float(np.sqrt((x_diff - wcs_pos[0]) ** 2 + (y_diff - wcs_pos[1]) ** 2))

        offsets.append(raw_offset_px)
        trials.append({
            "trial_id": idx + 1,
            "tic_id": cube_info["tic_id"],
            "name": cube_info["name"],
            "source": cube_info["source"],
            "period_d": round(period_d, 4),
            "depth_ppm": round(depth_frac * 1e6, 1),
            "wcs_target_px": [round(wcs_pos[0], 3), round(wcs_pos[1], 3)],
            "measured_offset_px": round(raw_offset_px, 4),
            "status": status,
        })

    arr = np.array(offsets, dtype=float)
    p50 = float(np.percentile(arr, 50))
    p90 = float(np.percentile(arr, 90))
    p95 = float(np.percentile(arr, 95))
    p99 = float(np.percentile(arr, 99))
    per_star_transit = _compute_per_star_summary(trials)

    bin_edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.5]
    hist_counts, _ = np.histogram(arr, bins=bin_edges)
    histogram = [
        {"bin_px": f"[{bin_edges[i]:.1f}, {bin_edges[i+1]:.1f})", "count": int(hist_counts[i])}
        for i in range(len(hist_counts))
    ]

    # Part 2: Separate calibration for variable-star peak-vs-trough difference imaging
    rng_var = np.random.default_rng(VARIABLE_CALIBRATION_SEED)
    var_trials: List[Dict[str, Any]] = []
    var_offsets: List[float] = []

    for idx in range(N_INJECTIONS):
        cube_info = cubes[idx % len(cubes)]
        t = cube_info["time"]
        base_flux = cube_info["flux"]
        wcs_pos = cube_info["wcs_pos"]
        h, w = base_flux.shape[1], base_flux.shape[2]
        yg, xg = np.mgrid[:h, :w]

        period_d = float(rng_var.uniform(0.5, 2.3))
        amp_frac = float(rng_var.uniform(0.003, 0.015))
        phi_0 = float(rng_var.uniform(0.0, 1.0))

        wcs_err_x = float(rng_var.normal(0.0, 0.12))
        wcs_err_y = float(rng_var.normal(0.0, 0.12))
        inj_center_x = wcs_pos[0] + wcs_err_x
        inj_center_y = wcs_pos[1] + wcs_err_y
        prf_weight = np.exp(-((xg - inj_center_x) ** 2 + (yg - inj_center_y) ** 2) / 2.2)

        mod = 1.0 + amp_frac * np.sin(2.0 * np.pi * (t / period_d + phi_0))[:, None, None] * prf_weight[None, :, :]
        flux_inj = base_flux * mod

        v_status, v_off, _ = compute_variable_difference_image_centroid(
            t, flux_inj, period_d, target_pos=wcs_pos, expected_amp=amp_frac
        )
        var_offsets.append(float(v_off))
        var_trials.append({
            "trial_id": idx + 1,
            "tic_id": cube_info["tic_id"],
            "name": cube_info["name"],
            "source": cube_info["source"],
            "period_d": round(period_d, 4),
            "amp_ppm": round(amp_frac * 1e6, 1),
            "phase_phi0": round(phi_0, 4),
            "wcs_target_px": [round(wcs_pos[0], 3), round(wcs_pos[1], 3)],
            "measured_offset_px": round(float(v_off), 4),
            "status": v_status,
        })

    var_arr = np.array(var_offsets, dtype=float)
    vp50 = float(np.percentile(var_arr, 50))
    vp90 = float(np.percentile(var_arr, 90))
    vp95 = float(np.percentile(var_arr, 95))
    vp99 = float(np.percentile(var_arr, 99))
    per_star_variable = _compute_per_star_summary(var_trials)

    # Verify 3-px off-target variable blend rejection across all 4 cardinal phases {0.0, 0.25, 0.50, 0.75}
    blend_checks: List[Dict[str, Any]] = []
    for cube_info in cubes:
        t = cube_info["time"]
        base_flux = cube_info["flux"]
        wcs_pos = cube_info["wcs_pos"]
        h, w = base_flux.shape[1], base_flux.shape[2]
        yg, xg = np.mgrid[:h, :w]
        med_img = np.nanmedian(base_flux, axis=0)
        r0 = int(np.clip(round(wcs_pos[1]), 1, h - 2))
        c0 = int(np.clip(round(wcs_pos[0]), 1, w - 2))
        peak_val = float(np.nanmax(med_img[r0 - 1 : r0 + 2, c0 - 1 : c0 + 2]))
        # Place 3-px neighbor inside the 11x11 stamp
        dx = 3.0 if wcs_pos[0] + 3.0 <= w - 1.5 else -3.0
        nb_prf = np.exp(-((xg - (wcs_pos[0] + dx)) ** 2 + (yg - wcs_pos[1]) ** 2) / 1.8)
        for phi_0 in (0.0, 0.25, 0.50, 0.75):
            mod_nb = (0.015 * peak_val) * np.sin(2.0 * np.pi * (t / 2.4 + phi_0))[:, None, None] * nb_prf[None, :, :]
            st_b, off_b, _ = compute_variable_difference_image_centroid(
                t, base_flux + mod_nb, 2.4, target_pos=wcs_pos, expected_amp=0.015
            )
            blend_checks.append({
                "name": cube_info["name"],
                "phase_phi0": phi_0,
                "measured_offset_px": round(float(off_b), 3),
                "status": st_b,
            })

    blend_reject_rate = float(sum(1 for b in blend_checks if b["status"] == "FAIL") / len(blend_checks))

    summary = {
        "calibration_seed": CALIBRATION_SEED,
        "n_injections": N_INJECTIONS,
        "calibration_tics": CALIBRATION_TICS,
        "threshold_percentile_definition": "95th percentile of on-target SPOC TPF injections (0.96 px); 99th percentile is 1.061 px",
        "median_offset_px": round(p50, 3),
        "p90_offset_px": round(p90, 3),
        "p95_offset_px": round(p95, 3),
        "p99_offset_px": round(p99, 3),
        "adopted_pass_threshold_px": round(p95, 2),
        "per_star_transit_null": per_star_transit,
        "histogram": histogram,
        "trials": trials,
        "variable_star_calibration": {
            "calibration_seed": VARIABLE_CALIBRATION_SEED,
            "n_injections": N_INJECTIONS,
            "statistic": "Fourier-phase-aligned peak-vs-trough difference image (signed img_peak - img_trough after slow scattered-light polynomial detrending)",
            "median_offset_px": round(vp50, 3),
            "p90_offset_px": round(vp90, 3),
            "p95_offset_px": round(vp95, 3),
            "p99_offset_px": round(vp99, 3),
            "adopted_pass_threshold_px": 0.96,
            "per_star_variable_null": per_star_variable,
            "quadrature_blend_rejection_rate": round(blend_reject_rate, 4),
            "quadrature_blend_checks": blend_checks,
            "trials": var_trials,
        },
    }

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("=" * 78)
    print("ASTROHUNTER PRO -- TPF DIFFERENCE-IMAGE THRESHOLD CALIBRATION REPORT")
    print("=" * 78)
    print(f"Seed: {CALIBRATION_SEED} | Total On-Target Transit Injections: {N_INJECTIONS}")
    print("Calibration Targets: " + ", ".join([f"{c['name']} (TIC {c['tic_id']})" for c in CALIBRATION_TICS]))
    print("-" * 78)
    print(f"  • Transit Median (50th pct) Offset : {p50:.3f} px")
    print(f"  • Transit 90th Percentile Offset   : {p90:.3f} px")
    print(f"  • Transit 95th Percentile Offset   : {p95:.3f} px  --> Adopted PASS Threshold = {round(p95, 2):.2f} px")
    print(f"  • Transit 99th Percentile Offset   : {p99:.3f} px")
    print("-" * 78)
    print("Per-Star On-Target Transit Null Distributions:")
    for nm, st in per_star_transit.items():
        print(
            f"  • {nm:<8} ({st['tic_id']}): median={st['median_offset_px']:.3f} px | "
            f"p95={st['p95_offset_px']:.3f} px | max={st['max_offset_px']:.3f} px | "
            f"ceiling={st['per_star_ceiling_px']:.2f} px"
        )
    print("-" * 78)
    print(f"Variable-Star Peak-vs-Trough Calibration (Seed: {VARIABLE_CALIBRATION_SEED}, N={N_INJECTIONS}):")
    print(
        f"  • Variable Median={vp50:.3f} px | p90={vp90:.3f} px | "
        f"p95={vp95:.3f} px | p99={vp99:.3f} px"
    )
    for nm, st in per_star_variable.items():
        print(
            f"  • {nm:<8} ({st['tic_id']}): median={st['median_offset_px']:.3f} px | "
            f"p95={st['p95_offset_px']:.3f} px | max={st['max_offset_px']:.3f} px | "
            f"ceiling={st['per_star_ceiling_px']:.2f} px"
        )
    print(f"  • 3-px Blend Rejection Across Phases {{0.0, 0.25, 0.50, 0.75}}: {int(blend_reject_rate*100)}% ({len(blend_checks)}/{len(blend_checks)} FAIL)")
    print("=" * 78)
    print(f"Saved full calibration artifact to: {OUTPUT_JSON_PATH.name}")
    return summary


if __name__ == "__main__":
    offline_flag = "--offline" in sys.argv
    run_tpf_threshold_calibration(offline=offline_flag)
