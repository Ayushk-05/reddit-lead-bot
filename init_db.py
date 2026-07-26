from db import get_conn

def main():
    with get_conn() as conn:
        with conn.cursor() as cur:
            with open("schema.sql", "r", encoding="utf-8") as f:
                cur.execute(f.read())
        conn.commit()

    print("✅ Database initialized successfully!")

if __name__ == "__main__":
    main()