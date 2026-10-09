import sqlite3
import csv
from pathlib import Path
from typing import Optional, Dict, Any, List
import numpy as np
from config import DB_PATH, MASTER_CSV_PATH

def get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS targets (
        tic_id TEXT PRIMARY KEY,
        name TEXT,
        ra REAL,
        dec REAL,
        status TEXT,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tic_id TEXT,
        name TEXT,
        ra REAL,
        dec REAL,
        category TEXT,
        type TEXT,
        period REAL,
        epoch REAL,
        depth REAL,
        amplitude REAL,
        duration REAL,
        sde REAL,
        fap REAL,
        tier TEXT,
        confidence TEXT,
        simbad_type TEXT,
        vsx_known BOOLEAN,
        sectors TEXT,
        plot_path TEXT,
        detection_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        vsx_submitted BOOLEAN DEFAULT 0,
        FOREIGN KEY (tic_id) REFERENCES targets(tic_id)
    )
    ''')
    
    # Migrate existing signals table if columns are missing
    cursor.execute("PRAGMA table_info(signals)")
    existing_cols = [row[1] for row in cursor.fetchall()]
    new_cols = [
        ("name", "TEXT"),
        ("ra", "REAL"),
        ("dec", "REAL"),
        ("category", "TEXT"),
        ("tier", "TEXT"),
        ("confidence", "TEXT"),
        ("simbad_type", "TEXT"),
        ("vsx_known", "BOOLEAN"),
        ("vsx_period", "REAL"),
        ("period_ratio", "REAL"),
        ("period_err", "REAL"),
        ("n_cycles", "REAL"),
        ("centroid_status", "TEXT"),
        ("centroid_shift_sigma", "REAL"),
        ("centroid_desc", "TEXT"),
        ("pipeline_version", "TEXT"),
        ("sectors", "TEXT"),
        ("plot_path", "TEXT"),
        ("detection_timestamp", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("vsx_submitted", "BOOLEAN DEFAULT 0")
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing_cols:
            try:
                cursor.execute(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    conn.commit()
    conn.close()
    
    # Initialize Master CSV if it doesn't exist
    if not MASTER_CSV_PATH.exists():
        with open(MASTER_CSV_PATH, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "name", "tic_id", "gaia_dr3_id", "ra", "dec", "period", "period_err", "vsx_period", "period_ratio", 
                "n_cycles", "centroid_status", "centroid_sigma", "amplitude", "depth", "category", "r_star_rsun", 
                "r_comp_rjup", "simbad_type", "vsx_known", "gaia_ok", "radius_ok", "orbit_phys_ok", 
                "duration_phys_ok", "confidence", "pipeline_version", "notes"
            ])

def upsert_target(tic_id: str, name: str, ra: float, dec: float, status: str = "PENDING"):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO targets (tic_id, name, ra, dec, status)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(tic_id) DO UPDATE SET
        name=excluded.name,
        ra=excluded.ra,
        dec=excluded.dec,
        status=excluded.status,
        last_updated=CURRENT_TIMESTAMP
    ''', (tic_id, name, ra, dec, status))
    conn.commit()
    conn.close()

def update_status(tic_id: str, status: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE targets SET status = ?, last_updated = CURRENT_TIMESTAMP WHERE tic_id = ?', (status, tic_id))
    conn.commit()
    conn.close()

def get_target_status(tic_id: str) -> Optional[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM targets WHERE tic_id = ?', (tic_id,))
    row = cursor.fetchone()
    conn.close()
    return row['status'] if row else None

def get_max_hd_number() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tic_id FROM targets WHERE tic_id LIKE 'HD %'")
    rows = cursor.fetchall()
    conn.close()
    max_num = 10000
    for r in rows:
        try:
            num = int(r['tic_id'].replace('HD ', ''))
            if num > max_num:
                max_num = num
        except Exception:
            pass
    return max_num

def save_discovery(tic_id: str, 
                   name: str, 
                   ra: float, 
                   dec: float, 
                   category: str, 
                   metrics: Dict[str, Any], 
                   catalog_info: Dict[str, Any], 
                   plot_path: str,
                   sectors: Optional[List[int]] = None):
    """
    Saves full discovery record to SQLite and appends to master_discoveries.csv.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    period = metrics.get('period')
    epoch = metrics.get('epoch')
    depth = metrics.get('depth')
    amplitude = metrics.get('amplitude')
    duration = metrics.get('duration')
    sde = metrics.get('sde')
    fap = metrics.get('fap')
    tier = metrics.get('tier', 'B')
    confidence = f"Tier {tier}"
    simbad_type = catalog_info.get('simbad_type', 'None')
    vsx_known = catalog_info.get('vsx_known', False)
    sectors_str = ",".join(map(str, sectors)) if sectors else ""
    
    vsx_period = catalog_info.get('vsx_period')
    period_ratio = catalog_info.get('period_ratio')
    period_err = metrics.get('period_err')
    n_cycles = metrics.get('n_cycles', round(metrics.get('cycles', 1.0), 1))
    centroid_status = metrics.get('centroid_status', 'NOT_RUN')
    centroid_sigma = metrics.get('centroid_shift_sigma', 0.0)
    centroid_desc = metrics.get('centroid_desc', 'Passed')
    pipeline_version = "v2.2.0"
    
    cursor.execute('''
    INSERT INTO signals (
        tic_id, name, ra, dec, category, type, period, period_err, vsx_period, period_ratio,
        n_cycles, centroid_status, centroid_shift_sigma, centroid_desc, pipeline_version,
        epoch, depth, amplitude, duration, sde, fap, tier, confidence, simbad_type, 
        vsx_known, sectors, plot_path
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        tic_id, name, ra, dec, category, category, period, period_err, vsx_period, period_ratio,
        n_cycles, centroid_status, centroid_sigma, centroid_desc, pipeline_version,
        epoch, depth, amplitude, duration, sde, fap, tier, confidence, simbad_type,
        vsx_known, sectors_str, plot_path
    ))
    conn.commit()
    conn.close()
    
    # Maintain Master CSV with clean physical parameters matching master_discoveries.csv
    gaia_dr3_id = catalog_info.get('gaia_dr3_id', 'N/A')
    r_star = catalog_info.get('r_star_rsun')
    if r_star is not None:
        try:
            if np.isnan(float(r_star)) or float(r_star) <= 0:
                r_star = None
            else:
                r_star = float(r_star)
        except Exception:
            r_star = None

    r_comp = None
    if "VARIABLE" not in category.upper() and r_star is not None and r_star > 0:
        if depth and depth > 0 and depth < 0.50:
            r_comp = round((r_star * np.sqrt(depth)) / 0.10279, 2)

    gaia_ok = "YES" if gaia_dr3_id and gaia_dr3_id not in ["N/A", "--", "None"] else "NO"
    radius_ok = "YES" if r_star is not None else "NO"
    
    # Orbital physical separation check
    orbit_phys_ok = "N/A"
    if period and period != "Single":
        try:
            p_val = float(period)
            a_rsun = 215.032 * (2.5 * (p_val / 365.25)**2)**(1/3)
            if r_star is not None and r_star > 0:
                orbit_phys_ok = "YES" if a_rsun > r_star else "NO (Inside Star)"
            else:
                orbit_phys_ok = "YES (R* unknown)"
        except Exception:
            pass
            
    # Transit duration physical check
    duration_phys_ok = "YES"
    if duration and duration > 0 and r_star is not None and r_star >= 5.0:
        t_dur_min = 0.0261 * (r_star**1.5 / np.sqrt(2.5))
        if duration < 0.20 * t_dur_min:
            duration_phys_ok = "NO (Too Fast for Giant)"

    # Derive tier confidence respecting vetter metrics and audit flags
    tier = metrics.get('tier', 'B')
    if tier == "A" and gaia_ok == "YES" and radius_ok == "YES" and orbit_phys_ok in ["YES", "N/A"] and duration_phys_ok == "YES":
        clean_tier = "Tier A (Vetted Clean)"
    elif tier in ["A", "B"] and (radius_ok == "NO" or gaia_ok == "NO"):
        clean_tier = "Tier B (Unconstrained Parameters)"
    elif tier == "B":
        clean_tier = "Tier B (Probable)"
    else:
        clean_tier = "Tier C (Audit Flagged)"

    notes = f"SDE={sde:.1f}, Sectors={sectors_str}" if sde else f"Sectors={sectors_str}"
    with open(MASTER_CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            name, 
            tic_id,
            gaia_dr3_id,
            round(ra, 6) if ra else "", 
            round(dec, 6) if dec else "", 
            round(period, 5) if period else "Single", 
            round(period_err, 6) if (period_err is not None and not np.isnan(period_err)) else "",
            round(vsx_period, 5) if vsx_period else "",
            round(period_ratio, 4) if period_ratio else "",
            round(n_cycles, 1) if n_cycles else "1.0",
            centroid_status,
            round(centroid_sigma, 2) if (centroid_sigma is not None and not np.isnan(centroid_sigma)) else "NaN",
            round(amplitude, 6) if amplitude else "", 
            round(depth, 5) if depth else "", 
            category, 
            round(r_star, 2) if r_star is not None else "",
            r_comp if r_comp is not None else "",
            simbad_type, 
            "YES" if vsx_known else "NO", 
            gaia_ok,
            radius_ok,
            orbit_phys_ok,
            duration_phys_ok,
            clean_tier, 
            pipeline_version,
            notes
        ])

init_db()
