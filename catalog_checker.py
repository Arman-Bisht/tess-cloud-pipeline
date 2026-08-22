import logging
from typing import Optional, Tuple
from astropy.coordinates import SkyCoord
import astropy.units as u
from astroquery.simbad import Simbad
from astroquery.vizier import Vizier
from astroquery.ipac.nexsci.nasa_exoplanet_archive import NasaExoplanetArchive
from tenacity import retry, wait_exponential, stop_after_attempt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add OTYPE to Simbad query
custom_simbad = Simbad()
custom_simbad.add_votable_fields('otype')

@retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3))
def check_catalog(ra: float, dec: float, category: str, period: float) -> Tuple[bool, Optional[str]]:
    """
    Checks if the target is already known.
    Returns (is_known, known_classification_string).
    """
    coord = SkyCoord(ra=ra, dec=dec, unit=(u.deg, u.deg))
    radius = 15 * u.arcsec
    
    # 1. NASA Exoplanet Archive
    if category == "CANDIDATE_EXOPLANET":
        try:
            table = NasaExoplanetArchive.query_region(table="pscomppars", coordinates=coord, radius=radius)
            if len(table) > 0:
                known_periods = table['pl_orbper'].data
                for kp in known_periods:
                    if kp and abs(kp - period) / period < 0.05:
                        return True, "KNOWN_PLANET"
                return True, "KNOWN_PLANET_OTHER_PERIOD"
        except Exception as e:
            logger.warning(f"Exoplanet Archive query failed: {e}")
            
    # 2. SIMBAD
    try:
        result_table = custom_simbad.query_region(coord, radius=radius)
        if result_table is not None and len(result_table) > 0:
            colnames = result_table.colnames
            for row in result_table:
                if 'OTYPE' in colnames:
                    otype = row['OTYPE'].decode('utf-8') if isinstance(row['OTYPE'], bytes) else row['OTYPE']
                elif 'otype' in colnames:
                    otype = row['otype'].decode('utf-8') if isinstance(row['otype'], bytes) else row['otype']
                else:
                    continue
                if otype in ['EB*', 'V*', 'PulsV*', 'Planet?']:
                    return True, f"KNOWN_{otype.replace('*', '').replace('?', '').upper()}"
    except Exception as e:
        logger.warning(f"SIMBAD query failed: {e}")
        
    # 3. VSX
    try:
        vizier = Vizier(catalog="B/vsx/vsx", columns=["OID", "Name", "V", "Type", "Period"])
        result = vizier.query_region(coord, radius=radius)
        if len(result) > 0 and len(result[0]) > 0:
            return True, "KNOWN_VSX_VAR"
    except Exception as e:
        logger.warning(f"VSX query failed: {e}")
        
    return False, None

def get_final_status(category: str, is_known: bool, known_label: Optional[str]) -> str:
    if is_known:
        return known_label if known_label else f"KNOWN_{category}"
    else:
        return f"DISCOVERY_UNRECORDED_{category}"
