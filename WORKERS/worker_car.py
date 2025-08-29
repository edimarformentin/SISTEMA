import json, os, time, socket, traceback, threading
import pika, psycopg2

BROKER_URL = os.environ["BROKER_URL"]
DB_URL     = os.environ["DB_URL"]
WORKER_ID  = os.environ.get("WORKER_ID", f"car-{socket.gethostname()}")

RENEW_EVERY_SEC = int(os.getenv("RENEW_EVERY_SEC", "5"))
LEASE_EXT_SEC   = int(os.getenv("LEASE_EXT_SEC", "20"))

def db_conn():
    return psycopg2.connect(DB_URL)

def get_det_id(cur, det_name:str) -> int:
    cur.execute("INSERT INTO detection_type(name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (det_name,))
    cur.execute("SELECT id FROM detection_type WHERE name=%s", (det_name,))
    return cur.fetchone()[0]

def upsert_assignment_start(cur, camera_id:int, det_name:str, lease_ttl:int):
    det_id = get_det_id(cur, det_name)
    cur.execute("""
        INSERT INTO assignment(camera_id, detection_type_id, worker_id, lease_until, status)
        VALUES (%s, %s, %s, now() + (%s || ' sec')::interval, 'leased')
        ON CONFLICT (camera_id, detection_type_id) DO UPDATE
          SET worker_id=EXCLUDED.worker_id,
              lease_until=EXCLUDED.lease_until,
              status='leased',
              updated_at=now()
    """, (camera_id, det_id, WORKER_ID, lease_ttl))

def upsert_assignment_stop(cur, camera_id:int, det_name:str):
    det_id = get_det_id(cur, det_name)
    cur.execute("""
        INSERT INTO assignment(camera_id, detection_type_id, worker_id, lease_until, status)
        VALUES (%s, %s, NULL, NULL, 'stopped')
        ON CONFLICT (camera_id, detection_type_id) DO UPDATE
          SET worker_id=NULL,
              lease_until=NULL,
              status='stopped',
              updated_at=now()
    """, (camera_id, det_id))

def upsert_subscription_params(cur, camera_id:int, det_name:str, params:dict):
    det_id = get_det_id(cur, det_name)
    cur.execute("""
        INSERT INTO camera_subscription(camera_id, detection_type_id, params, enabled)
        VALUES (%s, %s, %s::jsonb, TRUE)
        ON CONFLICT (camera_id, detection_type_id) DO UPDATE
          SET params = camera_subscription.params || EXCLUDED.params,
              updated_at = now()
    """, (camera_id, det_id, json.dumps(params)))

def renew_loop():
    time.sleep(RENEW_EVERY_SEC)
    while True:
        try:
            with db_conn() as dbc, dbc.cursor() as cur:
                cur.execute("""
                    UPDATE assignment a
                    SET lease_until = GREATEST(a.lease_until, now()) + (%s || ' sec')::interval,
                        updated_at = now()
                    FROM detection_type dt
                    WHERE a.detection_type_id = dt.id
                      AND dt.name = %s
                      AND a.worker_id = %s
                      AND a.status = 'leased'
                """, (LEASE_EXT_SEC, "car", WORKER_ID))
        except Exception as e:
            print(f"[worker:{WORKER_ID}] erro no renew: {e}", flush=True)
        time.sleep(RENEW_EVERY_SEC)

def main():
    params = pika.URLParameters(BROKER_URL)
    while True:
        try:
            conn = pika.BlockingConnection(params)
            ch = conn.channel()
            ch.queue_declare(queue="det.start.car", durable=True)
            ch.queue_declare(queue="det.stop", durable=True)
            ch.queue_declare(queue="det.params", durable=True)
            ch.basic_qos(prefetch_count=3)
            print(f"[worker:{WORKER_ID}] aguardando det.start.car / det.stop / det.params", flush=True)

            def on_start(chx, method, props, body):
                try:
                    msg = json.loads(body.decode("utf-8"))
                    cam = int(msg["camera_id"])
                    ttl = int(msg.get("lease_ttl_sec", 60))
                    with db_conn() as dbc, dbc.cursor() as cur:
                        upsert_assignment_start(cur, cam, "car", ttl)
                    print(f"[worker:{WORKER_ID}] START car camera={cam} ttl={ttl}s -> ASSIGN ok", flush=True)
                    chx.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"[worker:{WORKER_ID}] ERRO START: {e}\n{traceback.format_exc()}", flush=True)
                    chx.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            def on_stop(chx, method, props, body):
                try:
                    msg = json.loads(body.decode("utf-8"))
                    det = msg.get("type") or msg.get("detection_type")
                    if det != "car":
                        chx.basic_ack(delivery_tag=method.delivery_tag); return
                    cam = int(msg["camera_id"])
                    with db_conn() as dbc, dbc.cursor() as cur:
                        upsert_assignment_stop(cur, cam, "car")
                    print(f"[worker:{WORKER_ID}] STOP car camera={cam} -> stopped", flush=True)
                    chx.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"[worker:{WORKER_ID}] ERRO STOP: {e}\n{traceback.format_exc()}", flush=True)
                    chx.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            def on_params(chx, method, props, body):
                try:
                    msg = json.loads(body.decode("utf-8"))
                    det = msg.get("type") or msg.get("detection_type")
                    if det != "car":
                        chx.basic_ack(delivery_tag=method.delivery_tag); return
                    cam = int(msg["camera_id"])
                    params = msg.get("params") or {k.replace('-','_'):v for k,v in msg.items() if k in ("threshold","max_fps")}
                    with db_conn() as dbc, dbc.cursor() as cur:
                        upsert_subscription_params(cur, cam, "car", params)
                    print(f"[worker:{WORKER_ID}] PARAMS car camera={cam} -> merged {params}", flush=True)
                    chx.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    print(f"[worker:{WORKER_ID}] ERRO PARAMS: {e}\n{traceback.format_exc()}", flush=True)
                    chx.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            threading.Thread(target=renew_loop, daemon=True).start()
            ch.basic_consume(queue="det.start.car", on_message_callback=on_start, auto_ack=False)
            ch.basic_consume(queue="det.stop", on_message_callback=on_stop, auto_ack=False)
            ch.basic_consume(queue="det.params", on_message_callback=on_params, auto_ack=False)
            ch.start_consuming()
        except Exception as e:
            print(f"[worker:{WORKER_ID}] conexão perdida: {e}; retry em 1s", flush=True)
            time.sleep(1)

if __name__ == "__main__":
    main()
