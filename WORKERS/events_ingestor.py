import json, os, time, socket, traceback
import pika, psycopg2

BROKER_URL = os.environ["BROKER_URL"]
DB_URL     = os.environ["DB_URL"]
WORKER_ID  = os.environ.get("WORKER_ID", f"ingestor-{socket.gethostname()}")

def db():
    return psycopg2.connect(DB_URL)

def get_det_id(cur, det_name:str) -> int:
    cur.execute("INSERT INTO detection_type(name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (det_name,))
    cur.execute("SELECT id FROM detection_type WHERE name=%s", (det_name,))
    return cur.fetchone()[0]

def insert_event(cur, ev:dict):
    det_id = get_det_id(cur, ev["detection_type"])
    cur.execute("""
        INSERT INTO det_event(event_id, camera_id, detection_type_id, ts, cls, conf)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """, (
        ev.get("event_id"),
        int(ev["camera_id"]),
        det_id,
        ev["ts"],
        ev.get("cls"),
        float(ev.get("conf", 0.0)),
    ))

def main():
    params = pika.URLParameters(BROKER_URL)
    while True:
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue="det.events", durable=True)
            ch.basic_qos(prefetch_count=50)
            print(f"[{WORKER_ID}] aguardando msgs em det.events", flush=True)
            def on_msg(chx, method, props, body):
                try:
                    ev = json.loads(body.decode("utf-8"))
                    with db() as dbc, dbc.cursor() as cur:
                        insert_event(cur, ev)
                    chx.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"[{WORKER_ID}] ERRO: {e}\n{traceback.format_exc()}", flush=True)
                    chx.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            ch.basic_consume(queue="det.events", on_message_callback=on_msg, auto_ack=False)
            ch.start_consuming()
        except Exception as e:
            print(f"[{WORKER_ID}] conexão perdida: {e}; retry em 1s", flush=True)
            time.sleep(1)

if __name__ == "__main__":
    main()
