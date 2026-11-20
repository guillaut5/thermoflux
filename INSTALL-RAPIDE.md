# Installation : la séquence en bref

Version condensée de [INSTALL.md](INSTALL.md) (explications, variables, dépannage). Commandes en PowerShell, à lancer depuis le dossier du projet. Docker Desktop doit être démarré.

## Vue d'ensemble

```
Postgres (sain) ──┐
                  ├──► migrate (s'arrête) ──┬──► ingestion ──► écrit dans Postgres
Mosquitto (sain) ─┘                         └──► web  ──► http://127.0.0.1:8000
Mosquitto (sain) ──► 10 simulateurs ──► publient dans Mosquitto
```

Deux voies, **une seule à la fois** : **A** = tout à la main (`docker run`), **B** = `docker compose`. Mêmes images, même réseau, même volume : on peut basculer sans perdre l'historique.

## 1. Configuration (une fois)

```
Copy-Item .env.example .env
```
Éditer `.env` : remplacer les 3 mots de passe `change_me*`. **À faire avant le premier démarrage** : Postgres ne lit son mot de passe qu'à la création du volume.

## 2. Image web, puis ses secrets (une fois)

```
docker build -t thermoflux-web ./web
docker run --rm -it thermoflux-web python hash_password.py                              # → WEB_PASSWORD_HASH= dans .env
docker run --rm thermoflux-web python -c "import secrets; print(secrets.token_hex(32))" # → SECRET_KEY= dans .env
```

## 3A. Voie manuelle

```
docker compose up -d --wait postgres mosquitto          # socle : les 2 images officielles

docker build -t thermoflux-migrate    ./db
docker build -t thermoflux-ingestion  ./ingestion
docker build -t thermoflux-simulateur ./simulateur

Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=\s]+)=(.*)$') { Set-Variable -Name $matches[1] -Value $matches[2] } }
$DATABASE_URL = "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"

docker run --rm --network thermoflux-dev -e DATABASE_URL=$DATABASE_URL thermoflux-migrate
docker run -d --name ingestion --network thermoflux-dev -e MQTT_HOST=mosquitto -e MQTT_USERNAME=ingestion -e MQTT_PASSWORD=$MQTT_INGESTION_PASSWORD -e DATABASE_URL=$DATABASE_URL thermoflux-ingestion
docker run -d --name web --network thermoflux-dev -p 127.0.0.1:8000:8000 -e DATABASE_URL=$DATABASE_URL -e WEB_USER=$WEB_USER -e WEB_PASSWORD_HASH=$WEB_PASSWORD_HASH -e SECRET_KEY=$SECRET_KEY thermoflux-web
docker run -d --name machine_01 --network thermoflux-dev -e MACHINE_ID=machine_01 -e MQTT_HOST=mosquitto -e MQTT_USERNAME=simulateur -e MQTT_PASSWORD=$MQTT_SIMULATEUR_PASSWORD thermoflux-simulateur
# autant de machines que voulu : changer machine_01 (nom du conteneur et MACHINE_ID)
```

## 3B. Voie Compose

```
docker compose up -d --build --wait
```
Lance tout, les 10 machines comprises, dans l'ordre du schéma.

## 4. Vérifier

```
docker ps                                                  # voie A : ingestion, web, machine_xx ; voie B : thermoflux-*-1
curl.exe -s http://127.0.0.1:8000/health                   # {"status":"ok"}
docker exec thermoflux-postgres-1 psql -U thermoflux -c "SELECT machine_id, count(*), max(ts) FROM mesures GROUP BY 1 ORDER BY 1"
```
Navigateur : <http://127.0.0.1:8000>, utilisateur `WEB_USER`, mot de passe choisi à l'étape 2.

| Test | Voie A | Voie B |
|---|---|---|
| Une machine hors ligne (grise après 30 s) | `docker stop machine_01` | `docker compose stop simulateur_04` |
| Logs d'un service | `docker logs ingestion` | `docker compose logs -f ingestion` |
| Panne de la base (l'ingestion se reconnecte seule) | `docker restart thermoflux-postgres-1` | idem |

## 5. Arrêter

```
docker rm -f web ingestion machine_01    # voie A : d'abord les conteneurs manuels
docker compose down                      # garde la base ; `down -v` l'efface
```

## Changer de voie

| De | Vers | Faire |
|---|---|---|
| A | B | `docker rm -f web ingestion machine_01 ...` puis `docker compose up -d --build --wait` |
| B | A | `docker compose down`, puis tout le bloc 3A |

## Pièges fréquents

| Symptôme | Cause | Solution |
|---|---|---|
| `password authentication failed` | `.env` modifié après la création du volume | remettre l'ancien mot de passe, ou `docker compose down -v` |
| `name ... is already in use` | conteneur du même nom déjà là | `docker rm -f nom` |
| `port is already allocated` | port pris, ou l'autre voie tourne encore | arrêter l'autre voie, ou changer `WEB_HOST_PORT` / `POSTGRES_HOST_PORT` / `MQTT_HOST_PORT` |
| `failed to resolve host 'postgres'` | `docker run` sans `--network thermoflux-dev` | ajouter l'option |
| `Network ... Resource is still in use` | conteneurs manuels encore sur le réseau | `docker rm -f` dessus, puis `compose down` |
| Mesures en double | les deux voies tournent : deux ingestions | n'en garder qu'une |
| `web` redémarre en boucle (voie B) | `WEB_PASSWORD_HASH` ou `SECRET_KEY` vides | étape 2, puis `docker compose up -d web` |
| `.env` modifié, aucun effet (voie A) | variables chargées dans le terminal une seule fois | relancer le bloc `Get-Content .env ...` |
