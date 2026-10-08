import logging
from typing import Optional, Tuple, Dict, Any
from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.simbad import Simbad
from astroquery.vizier import Vizier
from astroquery.mast import Catalogs
import requests
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure SIMBAD with otype and sp_type (spectral type)
custom_simbad = Simbad()
try:
    custom_simbad.add_votable_fields('otype', 'sp_type')
except Exception:
    pass

_NASA_TOI_MAP = None

def get_nasa_toi_map():
    global _NASA_TOI_MAP
    if _NASA_TOI_MAP is not None:
        return _NASA_TOI_MAP
    _NASA_TOI_MAP = {}
    try:
        url = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query=select+toi,tid,tfopwg_disp+from+toi&format=json"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                if item.get('tid'):
                    _NASA_TOI_MAP[int(item['tid'])] = str(item.get('toi'))
    except Exception as e:
        logger.warning(f"Failed to fetch live NASA TOI catalog: {e}")
    return _NASA_TOI_MAP

def format_sexagesimal(ra_deg: float, dec_deg: float) -> str:
    try:
        coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg))
        ra_str = coord.ra.to_string(unit=u.hour, sep=('h ', 'm '), precision=2) + 's'
        dec_str = coord.dec.to_string(unit=u.deg, sep=('d ', "' "), precision=2) + '"'
        return f"{ra_str}, {dec_str}"
    except Exception:
        return f"{ra_deg:.4f}d, {dec_deg:.4f}d"

def fetch_gaia_metadata(star_name: str) -> Tuple[str, float]:
    """Retrieves Gaia DR3 Source ID and TESS magnitude from TIC."""
    gaia_id = "N/A"
    tmag = 9.0
    try:
        tic_res = Catalogs.query_object(star_name, catalog="TIC", radius=0.005)
        if len(tic_res) > 0:
            row = tic_res[0]
            if 'GAIA' in row.colnames and row['GAIA'] is not None:
                gaia_id = str(row['GAIA'])
            if 'Tmag' in row.colnames and row['Tmag'] is not None and not np.isnan(float(row['Tmag'])):
                tmag = float(row['Tmag'])
    except Exception as e:
        logger.warning(f"Failed to fetch Gaia metadata for {star_name}: {e}")
    return gaia_id, tmag

def check_catalog(ra: float, dec: float, category: str, period: Optional[float], tic_id: Optional[str] = None, star_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Performs strict astronomical cross-matching:
    1. Exact TIC ID matching against NASA Exoplanet Archive TOIs.
    2. Exact star identifier query in SIMBAD (falling back to tight <=2.5" cone).
    3. Tight <=3.0" cone query in AAVSO VSX to eliminate faint background neighbors.
    
    Returns structured catalog matching info including Gaia ID and match separation in arcsec.
    """
    coord = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))
    
    gaia_id = "N/A"
    tmag = 9.0
    if star_name:
        gaia_id, tmag = fetch_gaia_metadata(star_name)

    info = {
        "is_known": False,
        "known_label": None,
        "gaia_dr3_id": gaia_id,
        "match_sep_arcsec": 0.0,
        "vsx_known": False,
        "vsx_name": "None",
        "vsx_type": "None",
        "vsx_text": "❌ Not found",
        "simbad_type": "None",
        "simbad_main_id": star_name if star_name else "Unknown",
        "simbad_text": "❌ Not cataloged",
        "archive_known": False,
        "archive_text": "❌ Not found",
        "coords_str": format_sexagesimal(ra, dec)
    }
    
    # 1. Exact NASA TOI Check by TIC ID
    toi_map = get_nasa_toi_map()
    clean_tid = None
    if tic_id:
        try:
            clean_tid = int(str(tic_id).replace("TIC", "").strip())
        except Exception:
            pass
            
    if clean_tid and clean_tid in toi_map:
        info["is_known"] = True
        info["archive_known"] = True
        info["known_label"] = "KNOWN_TOI_CANDIDATE"
        info["archive_text"] = f"✅ TOI {toi_map[clean_tid]}"
        return info

    # 2. SIMBAD: Query by exact target identifier first
    try:
        simbad_match = None
        if star_name:
            simbad_match = custom_simbad.query_object(star_name)
            
        if simbad_match is None or len(simbad_match) == 0:
            # Fall back to tight 2.5 arcsec cone to avoid background quasars or faint stars
            simbad_match = custom_simbad.query_region(coord, radius=2.5 * u.arcsec)

        if simbad_match is not None and len(simbad_match) > 0:
            row = simbad_match[0]
            col_map = {c.lower(): c for c in simbad_match.colnames}
            
            otype = ""
            sptype = ""
            main_id = ""
            if 'main_id' in col_map:
                val = row[col_map['main_id']]
                main_id = str(val.decode('utf-8') if isinstance(val, bytes) else val).strip()
            if 'otype' in col_map:
                val = row[col_map['otype']]
                otype = str(val.decode('utf-8') if isinstance(val, bytes) else val).strip()
            if 'sp_type' in col_map:
                val = row[col_map['sp_type']]
                sptype = str(val.decode('utf-8') if isinstance(val, bytes) else val).strip()
            elif 'sp' in col_map:
                val = row[col_map['sp']]
                sptype = str(val.decode('utf-8') if isinstance(val, bytes) else val).strip()
                    
            desc = f"{otype} {sptype}".strip()
            info["simbad_main_id"] = main_id
            info["simbad_type"] = desc if desc else otype
            info["simbad_text"] = f"✅ {desc}" if desc else "✅ Star listed"
            
            clean_otype = otype.upper().replace(' ', '')
            # Classify spectroscopic binaries distinctly from photometric detections
            if 'SB' in clean_otype:
                info["is_known"] = True
                info["is_known_binary"] = True
                info["known_label"] = "KNOWN_SIMBAD_SB_UNCHECKED_PHOTOMETRY"
                info["simbad_text"] = f"✅ Spectroscopic Binary ({desc})"
            elif any(k in clean_otype for k in ['EB*', 'EL*', 'BY*', 'RS*', 'ROTV*', 'DOUBLE', 'BINARY']):
                info["is_known"] = True
                info["is_known_binary"] = True
                info["known_label"] = "KNOWN_BINARY_PHOTOMETRIC_VAR"
                info["simbad_text"] = f"✅ Known Binary ({desc})"
            elif any(k in clean_otype for k in ['V*', 'PULS', 'PLANET', 'ECL', 'ROT']):
                info["is_known"] = True
                info["known_label"] = f"KNOWN_SIMBAD_{otype.replace('*','').replace('?','')}"
    except Exception as e:
        logger.warning(f"SIMBAD query failed: {e}")
        
    # 3. AAVSO VSX: Tight 3.0-arcsecond cone to prevent neighbor matching
    try:
        vizier = Vizier(catalog="B/vsx/vsx", columns=["OID", "Name", "Type", "Period", "RAJ2000", "DEJ2000"])
        result = vizier.query_region(coord, radius=3.0 * u.arcsec)
        if len(result) > 0 and len(result[0]) > 0:
            vsx_row = result[0][0]
            vsx_name = str(vsx_row['Name'])
            vsx_type = str(vsx_row['Type']) if 'Type' in vsx_row.colnames else "Var"
            match_c = SkyCoord(ra=vsx_row['RAJ2000'], dec=vsx_row['DEJ2000'], unit=(u.deg, u.deg))
            sep = float(coord.separation(match_c).arcsec)
            
            info["vsx_known"] = True
            info["vsx_name"] = vsx_name
            info["vsx_type"] = vsx_type
            info["match_sep_arcsec"] = sep
            info["vsx_text"] = f"✅ Known ({vsx_name} - {vsx_type})"
            info["is_known"] = True
            info["known_label"] = f"KNOWN_VSX_{vsx_type}"
    except Exception as e:
        logger.warning(f"VSX query failed: {e}")
        
    return info

def get_final_status(category: str, is_known: bool, known_label: Optional[str]) -> str:
    if is_known:
        return known_label if known_label else f"KNOWN_{category}"
    else:
        return f"UNLISTED_NEEDS_VETTING_{category}"
