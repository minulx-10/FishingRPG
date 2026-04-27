import sqlite3
conn = sqlite3.connect('fishing_rpg.db')
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(user_data)")
columns = [row[1] for row in cursor.fetchall()]
print(f"Columns in user_data: {columns}")
conn.close()
