"""Simulateur d'une machine qui publie sa temperature en MQTT.

Configuration uniquement par variables d'environnement (12-factor).
Logs sur stdout. Arret propre sur SIGTERM / SIGINT.
"""
import json
import logging
import math
import os
import random
import signal
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

log = logging.getLogger("simulateur")


def env(name, default=None, cast=str):
    value = os.environ.get(name)
    if value is None or value == "":
        if default is None:
            sys.exit("Variable d'environnement manquante : %s" % name)
        return default
    return cast(value)


class Config:
    def __init__(self):
        self.machine_id = env("MACHINE_ID")
        self.mqtt_host = env("MQTT_HOST", "localhost")
        self.mqtt_port = env("MQTT_PORT", 1883, int)
        self.mqtt_username = os.environ.get("MQTT_USERNAME") or None
        self.mqtt_password = os.environ.get("MQTT_PASSWORD") or None
        self.interval_s = env("INTERVAL_S", 5, float)
        # Modele : base + amplitude * sin(2*pi*t/periode) + bruit gaussien
        self.temp_base = env("TEMP_BASE", round(random.uniform(40, 50), 1), float)
        self.amplitude = env("TEMP_AMPLITUDE", 5.0, float)
        self.period_s = env("TEMP_PERIOD_S", 600.0, float)
        self.noise_sigma = env("TEMP_NOISE", 0.3, float)
        # Surchauffe : probabilite par mesure, duree, surplus de temperature
        self.overheat_prob = env("OVERHEAT_PROB", 0.002, float)
        self.overheat_duration_s = env("OVERHEAT_DURATION_S", 180.0, float)
        self.overheat_delta = env("OVERHEAT_DELTA", 15.0, float)
        self.topic = "usine/machines/%s/temperature" % self.machine_id


class TemperatureModel:
    def __init__(self, cfg):
        self.cfg = cfg
        self.phase = random.uniform(0, 2 * math.pi)  # machines desynchronisees
        self.t0 = time.monotonic()
        self.overheat_until = 0.0

    def next(self):
        c = self.cfg
        now = time.monotonic()
        if now >= self.overheat_until and random.random() < c.overheat_prob:
            self.overheat_until = now + c.overheat_duration_s
            log.warning("Surchauffe simulee pendant %.0f s", c.overheat_duration_s)
        temp = (
            c.temp_base
            + c.amplitude * math.sin(2 * math.pi * (now - self.t0) / c.period_s + self.phase)
            + random.gauss(0, c.noise_sigma)
        )
        if now < self.overheat_until:
            temp += c.overheat_delta
        return round(temp, 2)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main():
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    cfg = Config()
    model = TemperatureModel(cfg)
    stop = threading.Event()
    connected = threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("Connexion refusee par le broker : %s", reason_code)
            return
        log.info("Connecte a %s:%s", cfg.mqtt_host, cfg.mqtt_port)
        connected.set()

    def on_disconnect(client, userdata, flags, reason_code, properties):
        connected.clear()
        if not stop.is_set():
            log.warning("Deconnecte du broker (%s), reconnexion automatique", reason_code)

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2, client_id="simulateur-%s" % cfg.machine_id
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    if cfg.mqtt_username:
        client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password)

    def handle_signal(signum, frame):
        log.info("Signal %s recu, arret", signal.Signals(signum).name)
        stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info(
        "Demarrage %s -> %s:%s topic=%s base=%.1f intervalle=%ss",
        cfg.machine_id, cfg.mqtt_host, cfg.mqtt_port, cfg.topic, cfg.temp_base, cfg.interval_s,
    )
    # connect_async + loop_start : la boucle reessaie tant que le broker n'est pas pret
    client.connect_async(cfg.mqtt_host, cfg.mqtt_port, keepalive=30)
    client.loop_start()

    while not stop.is_set():
        if connected.is_set():
            payload = {
                "machine_id": cfg.machine_id,
                "ts": utc_now_iso(),
                "temperature_c": model.next(),
            }
            info = client.publish(cfg.topic, json.dumps(payload), qos=1)
            log.info("publie %s", json.dumps(payload))
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                log.warning("Echec de publication (rc=%s)", info.rc)
        else:
            log.info("En attente du broker...")
        stop.wait(cfg.interval_s)

    client.disconnect()
    client.loop_stop()
    log.info("Arrete proprement")


if __name__ == "__main__":
    main()
