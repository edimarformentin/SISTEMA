import os, sys, pika
BROKER_URL=os.environ["BROKER_URL"]
conn=pika.BlockingConnection(pika.URLParameters(BROKER_URL))
ch=conn.channel()
q=sys.argv[1]; msg=sys.argv[2]
ch.queue_declare(queue=q, durable=True)
ch.basic_publish(exchange="", routing_key=q, body=msg)
print(f"OK: publicado em {q}")
conn.close()
