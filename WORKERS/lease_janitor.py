import os, time, socket, traceback
import psycopg2

DB_URL = os.environ["DB_URL"]
WORKER_ID = os.environ.get("WORKER_ID", f"janitor-{socket.gethostname()}")
INTERVAL = int(os.getenv("JANITOR_INTERVAL", "5"))

def run():
    while True:
        try:
            with psycopg2.connect(DB_URL) as dbc, dbc.cursor() as cur:
                cur.execute("""
                    UPDATE assignment a
                       SET status='expired', worker_id=NULL, lease_until=NULL, updated_at=now()
                     WHERE a.status='leased' AND a.lease_until < now();
                """)
                print(f"[{WORKER_ID}] expired rows={cur.rowcount}", flush=True)
        except Exception as e:
            print(f"[{WORKER_ID}] ERRO JANITOR: {e}\n{traceback.format_exc()}", flush=True)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    run()
