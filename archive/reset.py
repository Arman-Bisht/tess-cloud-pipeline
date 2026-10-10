import sqlite3
conn = sqlite3.connect('astrohunter.db')
conn.execute("UPDATE targets SET status='PENDING'")
conn.commit()
conn.close()
