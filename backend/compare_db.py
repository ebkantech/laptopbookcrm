import psycopg
from getpass import getpass

dbs = [
    ("LOCAL", {
        "host": "localhost", "port": 5432,
        "user": "postgres", "dbname": "crmbook"
    }),
    ("SUPABASE", {
        "host": "aws-0-ap-south-1.pooler.supabase.com",
        "port": 5432, "user": "postgres.iazzkyvadvcmvwoyqirg",
        "dbname": "postgres"
    }),
]

counts = {}
for label, cfg in dbs:
    cfg["password"] = getpass(f"{label} database password: ")
    with psycopg.connect(**cfg) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' ORDER BY tablename
            """)
            tables = [r[0] for r in cur.fetchall()]
            counts[label] = {}
            for table in tables:
                cur.execute(
                    'SELECT COUNT(*) FROM public.' +
                    '"' + table.replace('"', '""') + '"'
                )
                counts[label][table] = cur.fetchone()[0]

print("\nTABLE COUNT COMPARISON")
print(f"{'TABLE':42} {'LOCAL':>8} {'SUPABASE':>10} {'STATUS'}")
print("-" * 76)
for table in sorted(set(counts["LOCAL"]) | set(counts["SUPABASE"])):
    local = counts["LOCAL"].get(table)
    remote = counts["SUPABASE"].get(table)
    status = "MATCH" if local == remote else "DIFFERENT"
    print(f"{table:42} {str(local):>8} {str(remote):>10} {status}")
print("\nTables local:", len(counts["LOCAL"]))
print("Tables Supabase:", len(counts["SUPABASE"]))
