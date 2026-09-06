import logging
from typing import Optional, Tuple, Dict, Any
from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.simbad import Simbad
from astroquery.vizier import Vizier
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
from tenacity import retry, wait_exponential, stop_after_attempt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure SIMBAD with otype and sp_type (spectral type)
custom_simbad = Simbad()
try:
    custom_simbad.add_votable_fields('otype', 'sp_type')
except Exception:
    pass

def format_sexagesimal(ra_deg: float, dec_deg: float) -> str:
    """
    Converts decimal RA/Dec to standard sexagesimal string (e.g. 01h 36m 46.66s, -52° 08' 12.13").
    """
    try:
        coord = SkyCoord(ra=ra_deg, dec=dec_deg, unit=(u.deg, u.deg))
        ra_str = coord.ra.to_string(unit=u.hour, sep=('h ', 'm '), precision=2) + 's'
        dec_str = coord.dec.to_string(unit=u.deg, sep=('d ', "' "), precision=2) + '"'
        return f"{ra_str}, {dec_str}"
    except Exception:
        return f"{ra_deg:.4f}d, {dec_deg:.4f}d"

@retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
def check_catalog(ra: float, dec: float, category: str, period: Optional[float]) -> Dict[str, Any]:
    """
    Performs 15-arcsecond coordinate cone search against:
    1. NASA Exoplanet Archive (pscomppars, toi)
    2. SIMBAD
    3. AAVSO VSX
    
    Returns structured catalog matching info.
    """
    coord = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))
    radius = 15 * u.arcsec
    
    info = {
        "is_known": False,
        "known_label": None,
        "vsx_known": False,
        "vsx_text": "❌ Not found",
        "simbad_type": "None",
        "simbad_text": "❌ Not cataloged",
        "archive_known": False,
        "archive_text": "❌ Not found",
        "coords_str": format_sexagesimal(ra, dec)
    }
    
    # 1. NASA Exoplanet Archive (pscomppars + toi)
    if "EXOPLANET" in category or "SINGLE_TRANSIT" in category:
        try:
            # Check confirmed planets (pscomppars)
            table_conf = NasaExoplanetArchive.query_region(table="pscomppars", coordinates=coord, radius=radius)
            if table_conf is not None and len(table_conf) > 0:
                info["is_known"] = True
                info["archive_known"] = True
                info["known_label"] = "KNOWN_CONFIRMED_PLANET"
                info["archive_text"] = "✅ Confirmed Planet"
                return info
                
            # Check TOI (TESS Objects of Interest)
            table_toi = NasaExoplanetArchive.query_region(table="toi", coordinates=coord, radius=radius)
            if table_toi is not None and len(table_toi) > 0:
                info["is_known"] = True
                info["archive_known"] = True
                info["known_label"] = "KNOWN_TOI_CANDIDATE"
                info["archive_text"] = f"✅ TOI {table_toi['toi'][0]}"
                return info
        except Exception as e:
            logger.warning(f"NASA Exoplanet Archive query failed: {e}")

    # 2. SIMBAD Cone Search
    try:
        result_table = custom_simbad.query_region(coord, radius=radius)
        if result_table is not None and len(result_table) > 0:
            colnames = [c.upper() for c in result_table.colnames]
            row = result_table[0]
            otype = ""
            sptype = ""
            for name in result_table.colnames:
                if name.upper() == 'OTYPE':
                    otype = str(row[name].decode('utf-8') if isinstance(row[name], bytes) else row[name]).strip()
                elif name.upper() in ['SP_TYPE', 'SP']:
                    sptype = str(row[name].decode('utf-8') if isinstance(row[name], bytes) else row[name]).strip()
                    
            desc = f"{otype} {sptype}".strip()
            if desc:
                info["simbad_type"] = desc
                info["simbad_text"] = f"✅ {desc}"
            else:
                info["simbad_text"] = "✅ Star listed"
                
            # Check if SIMBAD already classifies it as variable, binary, or planet
            if any(k in otype.upper() for k in ['EB', 'V*', 'PULS', 'PLANET', 'ECL']):
                info["is_known"] = True
                info["known_label"] = f"KNOWN_SIMBAD_{otype.replace('*','').replace('?','')}"
    except Exception as e:
        logger.warning(f"SIMBAD query failed: {e}")
        
    # 3. AAVSO VSX (Vizier B/vsx/vsx)
    try:
        vizier = Vizier(catalog="B/vsx/vsx", columns=["OID", "Name", "Type", "Period"])
        result = vizier.query_region(coord, radius=radius)
        if len(result) > 0 and len(result[0]) > 0:
            vsx_row = result[0][0]
            vsx_name = str(vsx_row['Name'])
            vsx_type = str(vsx_row['Type']) if 'Type' in vsx_row.colnames else "Var"
            info["vsx_known"] = True
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
        return f"DISCOVERY_UNRECORDED_{category}"
