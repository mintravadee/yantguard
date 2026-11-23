r"""Print the latest rows of the request log.  Run from the repo root:
    .venv\Scripts\python.exe scripts\show_log.py
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.governance.db import db_path  # noqa: E402

db = db_path()
if not db.exists():
    sys.exit(f"No database yet at {db}. Start the server and send a request first.")

conn = sqlite3.connect(db)
rows = conn.execute(
    """SELECT id, created_at, user_name, provider, model, prompt_tokens, completion_tokens,
              total_tokens, cost_usd, status_code, latency_ms, error
       FROM requests ORDER BY id DESC LIMIT 15"""
).fetchall()
print(f"{len(rows)} latest request(s) (newest first):\n")
for r in rows:
    print(f"#{r[0]} {r[1]} | user={r[2] or '-'} | {r[3]} / {r[4]} | tokens in={r[5]} out={r[6]} total={r[7]} "
          f"| cost={'-' if r[8] is None else f'${r[8]:.6f}'} | HTTP {r[9]} | {r[10]} ms" + (f" | error: {r[11]}" if r[11] else ""))
total, spent = conn.execute("SELECT COUNT(*), COALESCE(SUM(cost_usd),0) FROM requests").fetchone()
print(f"\nTotal rows: {total} | total equivalent cost: ${spent:.6f}")
conn.close()
