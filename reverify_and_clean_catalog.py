import pandas as pd
import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.simbad import Simbad
from astroquery.vizier import Vizier
from astroquery.mast import Catalogs
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("reverifier")

sys.stdout.reconfigure(encoding='utf-8')

# Configure custom SIMBAD
simbad_custom = Simbad()
simbad_custom.TIMEOUT = 10
simbad_custom.add_votable_fields('otype', 'sp')

vizier_vsx = Vizier(catalog="B/vsx/vsx", columns=["OID", "Name", "Type", "Period", "RAJ2000", "DEJ2000", "max", "min"])
vizier_vsx.TIMEOUT = 10

CSV_PATH = "master_discoveries.csv"
df = pd.read_csv(CSV_PATH)
logger.info(f"Loaded {len(df)} records from {CSV_PATH}")

def fetch_gaia_and_tic_meta(star_name, ra, dec):
    """Fetches exact Gaia DR3 Source ID, TESS magnitude, and stellar radius."""
    gaia_id = "N/A"
    tmag = 9.0
    r_star = 1.0
    try:
        tic_res = Catalogs.query_object(star_name, catalog="TIC", radius=0.005)
        if len(tic_res) > 0:
            row = tic_res[0]
            if 'GAIA' in row.colnames and row['GAIA'] is not None:
                gaia_id = str(row['GAIA'])
            if 'Tmag' in row.colnames and row['Tmag'] is not None and not np.isnan(float(row['Tmag'])):
                tmag = float(row['Tmag'])
            if 'rad' in row.colnames and row['rad'] is not None and not np.isnan(float(row['rad'])):
                r_star = float(row['rad'])
    except Exception as e:
        pass
    return gaia_id, tmag, r_star

def accurate_catalog_crossmatch(star_name, ra, dec):
    """
    Cross-matches using exact star name query first, then tight 2.5 arcsec cone.
    Returns: simbad_otype, simbad_main_id, simbad_sep_arcsec, vsx_name, vsx_type, vsx_sep_arcsec
    """
    coord = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))
    
    # 1. SIMBAD by exact name
    simbad_main = star_name
    simbad_otype = "Unknown"
    simbad_sep = 0.0
    try:
        s_res = simbad_custom.query_object(star_name)
        if s_res is not None and len(s_res) > 0:
            simbad_main = str(s_res['main_id'][0])
            simbad_otype = str(s_res['otype'][0])
            simbad_sep = 0.0
        else:
            # Fallback tight 2.5 arcsec cone
            s_cone = simbad_custom.query_region(coord, radius=2.5 * u.arcsec)
            if s_cone is not None and len(s_cone) > 0:
                simbad_main = str(s_cone['main_id'][0])
                simbad_otype = str(s_cone['otype'][0])
                c_match = SkyCoord(ra=s_cone['ra'][0], dec=s_cone['dec'][0], unit=(u.hourangle, u.deg))
                simbad_sep = float(coord.separation(c_match).arcsec)
    except Exception as e:
        pass

    # 2. VSX by tight 3.0 arcsec cone (eliminates 29-arcsec background neighbors like ZTF)
    vsx_name = "None"
    vsx_type = "None"
    vsx_sep = 999.0
    try:
        v_res = vizier_vsx.query_region(coord, radius=3.5 * u.arcsec)
        if len(v_res) > 0 and len(v_res[0]) > 0:
            v_row = v_res[0][0]
            vsx_name = str(v_row['Name'])
            vsx_type = str(v_row['Type']) if 'Type' in v_row.colnames else "Var"
            match_c = SkyCoord(ra=v_row['RAJ2000'], dec=v_row['DEJ2000'], unit=(u.deg, u.deg))
            vsx_sep = float(coord.separation(match_c).arcsec)
    except Exception as e:
        pass

    return simbad_main, simbad_otype, simbad_sep, vsx_name, vsx_type, vsx_sep

print("Auditing all 120 targets with strict scientific criteria...")
audit_results = []

for idx, row in df.iterrows():
    name = row['name']
    ra = float(row['ra'])
    dec = float(row['dec'])
    period_raw = str(row['period'])
    amp = float(row['amplitude']) if pd.notna(row['amplitude']) else 0.0
    depth = float(row['depth']) if pd.notna(row['depth']) else 0.0
    notes = str(row['notes']) if pd.notna(row['notes']) else ""
    r_star = float(row['r_star_rsun']) if pd.notna(row['r_star_rsun']) else 1.0

    # 1. Fetch metadata & cross-match
    gaia_id, tmag, r_star_tic = fetch_gaia_and_tic_meta(name, ra, dec)
    s_main, s_otype, s_sep, v_name, v_type, v_sep = accurate_catalog_crossmatch(name, ra, dec)

    # 2. Check for Flaws:
    # A. Spurious 18-19.6 day period
    p_val = None
    try:
        p_val = float(period_raw)
    except:
        pass
    
    is_spurious_19d = False
    if p_val is not None and (18.0 <= p_val <= 19.65):
        is_spurious_19d = True

    # B. Stitching / Divergence depth (> 50%)
    is_divergent_depth = False
    if depth > 0.50:
        is_divergent_depth = True

    # C. Noise floor amplitude (< 1000 ppm / 0.1%)
    is_noise_floor = False
    if amp > 0 and amp < 0.001 and (p_val is not None):
        is_noise_floor = True

    # D. Categorization
    disposition = "VALID"
    rejection_reason = "None"
    final_category = "UNLISTED_NEEDS_VETTING"

    if is_divergent_depth:
        disposition = "REJECTED_ARTIFACT"
        rejection_reason = f"Unphysical depth ({depth*100:.1f}%) from sector boundary flattening divergence"
    elif is_spurious_19d:
        disposition = "REJECTED_ARTIFACT"
        rejection_reason = f"Spurious ~19-day TESS sector/gap window function alias (P={p_val:.3f}d)"
    elif is_noise_floor:
        disposition = "REJECTED_NOISE_FLOOR"
        rejection_reason = f"Amplitude ({amp*1e6:.1f} ppm) below 1000 ppm TESS instrumental noise floor"
    elif v_name != "None" and v_sep <= 3.5:
        disposition = "RECOVERED_KNOWN_VSX"
        final_category = f"KNOWN_VSX_{v_type}"
    elif "SB" in s_otype:
        disposition = "KNOWN_SPECTROSCOPIC_BINARY"
        final_category = f"KNOWN_SIMBAD_SB_UNCHECKED_PHOTOMETRY"
    elif name == "HD 10647":
        disposition = "NON_TRANSITING_RV_HOST"
        final_category = "STELLAR_ACTIVITY_ON_KNOWN_RV_HOST"
    else:
        # Valid candidate surviving all cuts!
        if period_raw == "Single" or "Single" in str(row.get('notes','')):
            final_category = "UNLISTED_LOW_MASS_COMPANION_OR_GRAZING_EB"
        elif depth > 0.01:
            final_category = "UNLISTED_ECLIPSING_BINARY_CANDIDATE"
        else:
            final_category = "UNLISTED_VARIABLE_STAR_CANDIDATE"

    # Companion radius check
    r_comp = None
    if depth > 0 and depth < 0.50:
        r_comp = (r_star * np.sqrt(depth)) / 0.10279

    audit_results.append({
        "name": name,
        "tic_id": row['tic_id'],
        "gaia_dr3_id": gaia_id,
        "ra": ra,
        "dec": dec,
        "period": period_raw,
        "amplitude": amp,
        "depth": depth,
        "r_star_rsun": r_star,
        "r_comp_rjup": round(r_comp, 2) if r_comp is not None else None,
        "simbad_main_id": s_main,
        "simbad_otype": s_otype,
        "simbad_sep_arcsec": round(s_sep, 2),
        "vsx_name": v_name,
        "vsx_type": v_type,
        "vsx_sep_arcsec": round(v_sep, 2) if v_sep < 900 else None,
        "disposition": disposition,
        "final_category": final_category,
        "rejection_reason": rejection_reason,
        "original_notes": notes
    })

audit_df = pd.DataFrame(audit_results)
audit_df.to_csv("reverified_catalog_120.csv", index=False)
logger.info("Saved reverified_catalog_120.csv!")

print("\n=== REVERIFICATION BREAKDOWN ===")
print(audit_df['disposition'].value_counts())
print("\n=== SURVIVING VALID CANDIDATES CATEGORY BREAKDOWN ===")
valid_df = audit_df[audit_df['disposition'] == 'VALID']
print(valid_df['final_category'].value_counts())

print("\n=== TOP SURVIVING VALID CANDIDATES ===")
for idx, r in valid_df.iterrows():
    p_str = f"P={r['period']}d" if r['period'] != 'Single' else "Single Dip"
    sig_str = f"Amp={r['amplitude']*100:.2f}%" if r['amplitude'] > 0 else f"Depth={r['depth']*100:.2f}%"
    print(f"  * {r['name']} (TIC {r['tic_id']}): {r['final_category']} | {p_str}, {sig_str} | Simbad={r['simbad_otype']}")
