import sqlite3
import json

def check_logs():
    conn = sqlite3.connect('fishing_rpg.db')
    cursor = conn.cursor()
    
    print("--- Last 10 Audit Logs ---")
    cursor.execute("SELECT * FROM audit_logs ORDER BY log_id DESC LIMIT 10")
    for row in cursor.fetchall():
        print(row)
        
    print("\n--- Raid State ---")
    cursor.execute("SELECT * FROM server_state WHERE key LIKE 'RAID%'")
    for row in cursor.fetchall():
        print(row)
        
    conn.close()

if __name__ == "__main__":
    check_logs()
