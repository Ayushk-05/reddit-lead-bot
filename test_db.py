import psycopg
from config import DATABASE_URL

print("URL:", DATABASE_URL)
print("Connecting...")

conn = psycopg.connect(
    DATABASE_URL,
    connect_timeout=10,
)

print("✅ Connected!")

with conn.cursor() as cur:
    cur.execute("SELECT NOW();")
    print(cur.fetchone())

conn.close()
print("Done!")