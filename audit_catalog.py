import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
from astroquery.mast import Catalogs
from astroquery.vizier import Vizier
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
from astropy.coordinates import SkyCoord
import astropy.units as u
import sys

# Configure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

print("=== STEP 1: LOAD MASTER DISCOVERIES ===")
df = pd.read_csv("master_discoveries.csv")
print(f"Total entries: {len(df)}")

print("\n=== STEP 2: LOAD NASA EXOPLANET ARCHIVE TOI CATALOG ===")
toi_table = NasaExoplanetArchive.query_criteria(table='toi', select='toi,tid,tfopwg_disp,pl_rade,pl_orbper')
toi_df = toi_table.to_pandas()
# Create mapping from integer TIC ID to TOI info
toi_map = {}
for _, row in toi_df.iterrows():
    try:
        tid = int(row['tid'])
        toi_map[tid] = {
            'toi': str(row['toi']),
            'disp': str(row['tfopwg_disp']),
            'pl_rade': row['pl_rade'],
            'pl_orbper': row['pl_orbper']
        }
    except:
        pass
print(f"Loaded {len(toi_map)} TOIs mapped by TIC ID.")

print("\n=== STEP 3: RESOLVE EXACT TIC IDs CONCURRENTLY ===")
def fetch_tic_id(name):
    try:
        res = Catalogs.query_object(name, catalog="TIC", radius=0.005)
        if len(res) > 0:
            return name, int(res[0]['ID']), float(res[0]['rad']) if res[0]['rad'] is not None and not np.isnan(float(res[0]['rad'])) else 1.0
    except Exception as e:
        pass
    return name, None, 1.0

star_tic = {}
star_radius = {}
with ThreadPoolExecutor(max_workers=12) as executor:
    futures = [executor.submit(fetch_tic_id, name) for name in df['name']]
    for f in as_completed(futures):
        name, tid, rad = f.result()
        if tid is not None:
            star_tic[name] = tid
            star_radius[name] = rad

print(f"Successfully resolved exact TIC IDs for {len(star_tic)} / {len(df)} stars.")

print("\n=== STEP 4: CROSS-MATCH BY EXACT TIC ID AGAINST TOI ===")
toi_matches = []
for name, tid in star_tic.items():
    if tid in toi_map:
        info = toi_map[tid]
        toi_matches.append((name, tid, info['toi'], info['disp'], info['pl_rade'], info['pl_orbper']))

print(f"Total TOI Matches by exact TIC ID: {len(toi_matches)}")
for m in toi_matches:
    print(f"  -> {m[0]} (TIC {m[1]}): TOI {m[2]}, Disposition: {m[3]}, Rp: {m[4]} R_earth, Period: {m[5]} d")

print("\n=== STEP 5: DEEP CROSS-MATCH OF 10 UNRECORDED OBJECTS AGAINST PRSA ET AL. 2022, GAIA DR3, ASAS-SN ===")
test_targets = [
    "HD 10673", # 96.9% eclipse
    "HD 10528", # 66.4 min pulsator
    "HD 10544", # 97.1% eclipse
    "HD 10548", # giant host eclipse
    "HD 10668", # single transit candidate
    "HD 10670", # single transit candidate
    "HD 10607", # single transit candidate
    "HD 10564", # single transit candidate
    "HD 10628", # single transit candidate
    "HD 10683", # 26.4% eclipse
]

v = Vizier(row_limit=5)
for t_name in test_targets:
    matching = df[df['name'] == t_name]
    if matching.empty:
        continue
    t_row = matching.iloc[0]
    ra = float(t_row['ra'])
    dec = float(t_row['dec'])
    coord = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg), frame='icrs')
    tid = star_tic.get(t_name, "N/A")
    print(f"\n--- Checking {t_name} (TIC {tid}, RA={ra:.4f}, Dec={dec:.4f}) ---")
    
    # 1. TESS EB Catalog (Prsa et al. 2022, J/ApJS/258/16)
    try:
        res_eb = v.query_region(coord, radius=21.0*u.arcsec, catalog="J/ApJS/258/16/catalog")
        if len(res_eb) > 0 and len(res_eb[0]) > 0:
            eb_row = res_eb[0][0]
            print(f"  [TESS EB 2022 MATCH!]: TIC {eb_row.get('TIC', 'N/A')}, Period: {eb_row.get('Period', 'N/A')} d")
        else:
            print("  [TESS EB 2022]: No match within 21 arcsec.")
    except Exception as e:
        print(f"  [TESS EB 2022 Query error]: {e}")
        
    # 2. ASAS-SN Catalog of Variable Stars (II/366)
    try:
        res_asassn = v.query_region(coord, radius=21.0*u.arcsec, catalog="II/366/catalog")
        if len(res_asassn) > 0 and len(res_asassn[0]) > 0:
            as_row = res_asassn[0][0]
            print(f"  [ASAS-SN MATCH!]: {as_row.get('ASASSN-V', 'N/A')}, Type: {as_row.get('Type', 'N/A')}, Period: {as_row.get('Per', 'N/A')} d")
        else:
            print("  [ASAS-SN]: No match within 21 arcsec.")
    except Exception as e:
        print(f"  [ASAS-SN Query error]: {e}")

    # 3. Gaia DR3 Variability (I/358/vari_classifier_result)
    try:
        res_gaia = v.query_region(coord, radius=5.0*u.arcsec, catalog="I/358/vari_classifier_result")
        if len(res_gaia) > 0 and len(res_gaia[0]) > 0:
            g_row = res_gaia[0][0]
            print(f"  [Gaia DR3 Vari MATCH!]: Class: {g_row.get('best_class_name', 'N/A')}, Score: {g_row.get('best_class_score', 'N/A')}")
        else:
            print("  [Gaia DR3 Vari]: No match within 5 arcsec.")
    except Exception as e:
        print(f"  [Gaia DR3 Vari Query error]: {e}")
