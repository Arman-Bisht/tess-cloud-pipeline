import sqlite3
import csv
from pathlib import Path
from typing import Optional, Dict, Any, List
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
                "name", "ra", "dec", "tic_id", "period", "amplitude", 
                "depth", "category", "simbad_type", "vsx_known", "confidence", "notes"
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
    
    cursor.execute('''
    INSERT INTO signals (
        tic_id, name, ra, dec, category, type, period, epoch, depth, 
        amplitude, duration, sde, fap, tier, confidence, simbad_type, 
        vsx_known, sectors, plot_path
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        tic_id, name, ra, dec, category, category, period, epoch, depth,
        amplitude, duration, sde, fap, tier, confidence, simbad_type,
        vsx_known, sectors_str, plot_path
    ))
    conn.commit()
    conn.close()
    
    # Maintain Master CSV (Spec 3.4)
    # columns: name, ra, dec, tic_id, period, amplitude, depth, category, simbad_type, vsx_known, confidence, notes
    notes = f"SDE={sde:.1f}, Sectors={sectors_str}" if sde else f"Sectors={sectors_str}"
    with open(MASTER_CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            name, 
            round(ra, 6) if ra else "", 
            round(dec, 6) if dec else "", 
            tic_id, 
            round(period, 5) if period else "Single", 
            round(amplitude, 6) if amplitude else "", 
            round(depth, 5) if depth else "", 
            category, 
            simbad_type, 
            "YES" if vsx_known else "NO", 
            confidence, 
            notes
        ])

init_db()
