import sqlite3
from typing import Optional, Dict, Any
from config import DB_PATH

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
        type TEXT,
        period REAL,
        depth REAL,
        amplitude REAL,
        sde REAL,
        fap REAL,
        epoch REAL,
        duration REAL,
        FOREIGN KEY (tic_id) REFERENCES targets(tic_id)
    )
    ''')
    
    conn.commit()
    conn.close()

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

def save_signal(tic_id: str, signal_type: str, metrics: Dict[str, Any]):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO signals (tic_id, type, period, depth, amplitude, sde, fap, epoch, duration)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        tic_id, 
        signal_type, 
        metrics.get('period'), 
        metrics.get('depth'), 
        metrics.get('amplitude'), 
        metrics.get('sde'), 
        metrics.get('fap'),
        metrics.get('epoch'),
        metrics.get('duration')
    ))
    conn.commit()
    conn.close()

init_db()
