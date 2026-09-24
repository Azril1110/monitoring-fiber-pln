import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
url = os.getenv('SUPABASE_URL')
key = os.getenv('SUPABASE_KEY')

print(f"Connecting to Supabase at: {url}")
client = create_client(url, key)

tables = ['rings', 'nodes', 'segments', 'issues']
results = {}

for table in tables:
    try:
        res = client.table(table).select('*').limit(1).execute()
        results[table] = "EXISTS"
        print(f"Table '{table}': EXISTS (Data count: {len(res.data)})")
    except Exception as e:
        results[table] = f"NOT_FOUND / ERROR: {e}"
        print(f"Table '{table}': ERROR ({e})")

print("\nSummary:", results)
