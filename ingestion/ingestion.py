"""Ingestion : s'abonne aux temperatures MQTT et les ecrit dans PostgreSQL.

Architecture : le callback MQTT valide le message et le met dans une file ;
un thread d'ecriture le sort de la file et l'insere. Si Postgres est
indisponible, les messages s'accumulent dans la file (bornee) et l'ecriture
reprend a la reconnexion.

Configuration par variables d'environnement. Logs sur stdout.
"""
import json
import logging
import os
import queue
import signal
import sys
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import psycopg

log = logging.getLogger("ingestion")

QUEUE_MAX = 10000
INSERT_SQL = "INSERT INTO mesures (machine_id, ts, temperature_c) VALUES (%s, %s, %s)"


def env(name, default=None, cast=str):
    value = os.environ.get(name)
    if value is None or value == "":
        if default is None:
            sys.exit("Variable d'environnement manquante : %s" % name)
        return default
    return cast(value)


def parse_message(raw):
    """Retourne (machine_id, ts, temperature_c) ou leve ValueError."""
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("JSON invalide : %s" % exc)
    if not isinstance(data, dict):
        raise ValueError("le message n'est pas un objet JSON")

    machine_id = data.get("machine_id")
    if not isinstance(machine_id, str) or not machine_id:
        raise ValueError("machine_id absent ou invalide")

    ts_raw = data.get("ts")
    if not isinstance(ts_raw, str):
        raise ValueError("ts absent ou invalide")
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("ts non parsable : %r" % ts_raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)  # tout en UTC

    temp = data.get("temperature_c")
    if isinstance(temp, bool) or not isinstance(temp, (int, float)):
        raise ValueError("temperature_c absent ou non numerique")
    if temp != temp or temp in (float("inf"), float("-inf")):
        raise ValueError("temperature_c non finie")

    return machine_id, ts, float(temp)


def writer(database_url, q, stop, stats):
    """Sort les mesures de la file et les insere, en se reconnectant si besoin."""
    conn = None
    pending = None
    while True:
        if pending is None:
            try:
                pending = q.get(timeout=1)
            except queue.Empty:
                if stop.is_set():
                    return
                continue
        try:
            if conn is None or conn.closed:
                conn = psycopg.connect(database_url, connect_timeout=5)
                log.info("Connecte a PostgreSQL")
            with conn.cursor() as cur:
                cur.execute(INSERT_SQL, pending)
            conn.commit()
            stats["inserted"] += 1
            pending = None
        except psycopg.Error as exc:
            log.warning("Erreur PostgreSQL (%s), nouvel essai", str(exc).strip())
            if conn is not None:
                try:
                    conn.close()
                except psycopg.Error:
                    pass
                conn = None
            if stop.wait(2):
                log.error("Arret demande : mesure non inseree, %d en file perdues", q.qsize() + 1)
                return


def main():
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    mqtt_host = env("MQTT_HOST", "localhost")
    mqtt_port = env("MQTT_PORT", 1883, int)
    topic = env("MQTT_TOPIC", "usine/machines/+/temperature")
    database_url = env("DATABASE_URL")

    q = queue.Queue(maxsize=QUEUE_MAX)
    stop = threading.Event()
    stats = {"inserted": 0}

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Connexion refusee par le broker : %s", reason_code)
            return
        log.info("Connecte a %s:%s, abonnement a %s", mqtt_host, mqtt_port, topic)
        client.subscribe(topic, qos=1)  # reabonne a chaque (re)connexion

    def on_disconnect(client, userdata, flags, reason_code, properties):
        if not stop.is_set():
            log.warning("Deconnecte du broker (%s), reconnexion automatique", reason_code)

    def on_message(client, userdata, msg):
        try:
            row = parse_message(msg.payload)
        except ValueError as exc:
            log.warning("Message ignore sur %s : %s", msg.topic, exc)
            return
        try:
            q.put_nowait(row)
        except queue.Full:
            log.error("File pleine, mesure perdue (%s)", row[0])

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ingestion-%d" % os.getpid())
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    mqtt_username = os.environ.get("MQTT_USERNAME") or None
    if mqtt_username:
        client.username_pw_set(mqtt_username, os.environ.get("MQTT_PASSWORD") or None)

    def handle_signal(signum, frame):
        log.info("Signal %s recu, arret", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    thread = threading.Thread(target=writer, args=(database_url, q, stop, stats), name="writer")
    thread.start()

    client.connect_async(mqtt_host, mqtt_port, keepalive=30)
    client.loop_start()

    stop.wait()
    client.disconnect()
    client.loop_stop()
    thread.join(timeout=10)  # laisse le thread vider la file
    log.info("Arrete proprement (%d mesures inserees)", stats["inserted"])


if __name__ == "__main__":
    main()
