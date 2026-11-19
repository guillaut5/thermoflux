#!/bin/sh
# Genere le fichier de mots de passe Mosquitto a partir de l'environnement,
# puis lance le broker. Evite tout secret dans le depot ou dans l'image.
set -eu

: "${MQTT_SIMULATEUR_PASSWORD:?variable manquante : MQTT_SIMULATEUR_PASSWORD}"
: "${MQTT_INGESTION_PASSWORD:?variable manquante : MQTT_INGESTION_PASSWORD}"

PASSWD=/mosquitto/config/passwd
mosquitto_passwd -b -c "$PASSWD" simulateur "$MQTT_SIMULATEUR_PASSWORD"
mosquitto_passwd -b "$PASSWD" ingestion "$MQTT_INGESTION_PASSWORD"
chown mosquitto:mosquitto "$PASSWD"
chmod 0600 "$PASSWD"

exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
