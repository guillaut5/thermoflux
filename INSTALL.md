# Installation et lancement

Ce guide couvre l'état actuel du projet (étape 1 : simulateur, Mosquitto, Postgres, migrations, ingestion). Le `docker-compose.yml` complet, qui lance tout d'une commande, arrive à l'étape 2.

Le développement se fait sur Windows avec Docker Desktop. Le même code se lance ensuite sur la Dedibox (Linux), car tout tourne dans des conteneurs.

## 1. Prérequis

| Où | Il faut |
|---|---|
| **Windows** | [Docker Desktop](https://www.docker.com/products/docker-desktop/) (moteur WSL2) et Git. Aucun compte Docker n'est nécessaire : ignore la proposition de connexion. |
| **Linux (Dedibox)** | Docker Engine avec le plugin Compose (`docker compose`), et Git. |

Vérifier que le moteur tourne (Docker Desktop doit afficher « Engine running ») :

```
docker --version
docker info
```

Si `docker info` répond « failed to connect to the docker API », Docker Desktop n'est pas lancé. Si `docker` est introuvable juste après l'installation, ouvre un nouveau terminal (ou redémarre VS Code) pour recharger le `PATH`.

Espace disque : prévoir 5 à 8 Go pour Docker et les images à ce stade.

## 2. Récupérer le projet et configurer

```
git clone <url-du-depot> thermoflux
cd thermoflux
```

Créer le fichier `.env` à partir du modèle, **puis changer le mot de passe** :

```
# PowerShell
Copy-Item .env.example .env

# Linux / macOS
cp .env.example .env
```

Éditer `.env` et remplacer **les trois mots de passe** (`change_me`, `change_me_too`) par de vrais mots de passe. Le fichier `.env` est ignoré par Git : ne le commite jamais.

| Variable | Rôle |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Compte et base PostgreSQL |
| `MQTT_SIMULATEUR_PASSWORD` | Mot de passe du compte MQTT `simulateur` (publication seule) |
| `MQTT_INGESTION_PASSWORD` | Mot de passe du compte MQTT `ingestion` (lecture seule) |
| `POSTGRES_HOST_PORT` (optionnel, défaut `5433`) | Port Postgres exposé sur la machine hôte |
| `MQTT_HOST_PORT` (optionnel, défaut `1884`) | Port Mosquitto exposé sur la machine hôte |

Les ports hôte par défaut ne sont pas 5432 et 1883 : sur le PC de développement, un Postgres et un Mosquitto locaux occupaient déjà ces ports. À l'intérieur du réseau Docker, les services gardent leurs ports normaux (5432 et 1883) et se joignent par leur nom (`postgres`, `mosquitto`).

## 3. Lancer le socle (Mosquitto + Postgres)

```
docker compose -f docker-compose.dev.yml up -d --wait
```

`--wait` rend la main quand les deux services sont sains. Les ports ne sont publiés que sur `127.0.0.1` : rien n'est exposé sur le réseau.

Mosquitto exige un identifiant et un mot de passe : l'accès anonyme est refusé. Au démarrage, [mosquitto/init.sh](mosquitto/init.sh) crée les comptes `simulateur` et `ingestion` à partir des mots de passe du `.env`. Les droits de chaque compte sont dans [mosquitto/acl](mosquitto/acl).

## 4. Construire les images maison

```
docker build -t thermoflux-migrate   ./db
docker build -t thermoflux-ingestion ./ingestion
docker build -t thermoflux-simulateur ./simulateur
```

## 5. Créer le schéma (migration)

Le conteneur `migrate` applique Alembic puis s'arrête. Remplacer `<MOT_DE_PASSE>` par la valeur de `POSTGRES_PASSWORD` :

```
docker run --rm --network thermoflux-dev -e DATABASE_URL=postgresql://thermoflux:<MOT_DE_PASSE>@postgres:5432/thermoflux thermoflux-migrate
```

La commande est idempotente : la relancer ne fait rien de plus. Vérifier :

```
docker compose -f docker-compose.dev.yml exec postgres psql -U thermoflux -c "\d mesures"
```

> La migration doit être lancée une fois Postgres sain. Si elle échoue avec « Connection refused », attendre quelques secondes après l'étape 3 et relancer.

## 6. Lancer l'ingestion

Elle se connecte à Mosquitto avec le compte `ingestion` (valeur de `MQTT_INGESTION_PASSWORD`) :

```
docker run -d --name ingestion --network thermoflux-dev -e MQTT_HOST=mosquitto -e MQTT_USERNAME=ingestion -e MQTT_PASSWORD=<MQTT_INGESTION_PASSWORD> -e DATABASE_URL=postgresql://thermoflux:<MOT_DE_PASSE>@postgres:5432/thermoflux thermoflux-ingestion
```

## 7. Lancer des simulateurs

Un conteneur par machine, avec son identité en variable d'environnement et le compte `simulateur` (valeur de `MQTT_SIMULATEUR_PASSWORD`) :

```
docker run -d --name machine_01 --network thermoflux-dev -e MACHINE_ID=machine_01 -e MQTT_HOST=mosquitto -e MQTT_USERNAME=simulateur -e MQTT_PASSWORD=<MQTT_SIMULATEUR_PASSWORD> thermoflux-simulateur
docker run -d --name machine_02 --network thermoflux-dev -e MACHINE_ID=machine_02 -e MQTT_HOST=mosquitto -e MQTT_USERNAME=simulateur -e MQTT_PASSWORD=<MQTT_SIMULATEUR_PASSWORD> thermoflux-simulateur
```

Variables du simulateur (toutes optionnelles sauf `MACHINE_ID`) :

| Variable | Défaut | Rôle |
|---|---|---|
| `MACHINE_ID` | obligatoire | Identité de la machine |
| `MQTT_HOST`, `MQTT_PORT` | `localhost`, `1883` | Broker |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | aucun | Identifiants MQTT (obligatoires face à un broker authentifié) |
| `INTERVAL_S` | `5` | Période d'émission (secondes) |
| `TEMP_BASE` | aléatoire 40-50 | Température moyenne |
| `TEMP_AMPLITUDE`, `TEMP_PERIOD_S`, `TEMP_NOISE` | `5`, `600`, `0.3` | Forme de la courbe |
| `OVERHEAT_PROB`, `OVERHEAT_DURATION_S`, `OVERHEAT_DELTA` | `0.002`, `180`, `15` | Surchauffe aléatoire |

Variables de l'ingestion : `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPIC` (défaut `usine/machines/+/temperature`) et `DATABASE_URL` (obligatoire).

## 8. Vérifier que ça marche

Voir passer les messages sur le broker (3 messages puis arrêt). Les mots de passe sont déjà dans l'environnement du conteneur Mosquitto, d'où les apostrophes simples :

```
docker compose -f docker-compose.dev.yml exec mosquitto sh -c 'mosquitto_sub -u ingestion -P "$MQTT_INGESTION_PASSWORD" -v -W 15 -C 3 -t "usine/machines/+/temperature"'
```

Vérifier que l'accès anonyme est bien refusé (doit répondre « not authorised ») :

```
docker compose -f docker-compose.dev.yml exec mosquitto mosquitto_pub -t usine/machines/x/temperature -m test
```

Voir les mesures arriver en base :

```
docker compose -f docker-compose.dev.yml exec postgres psql -U thermoflux -c "SELECT machine_id, count(*), max(ts) FROM mesures GROUP BY 1 ORDER BY 1"
```

Lire les logs d'un service :

```
docker logs machine_01
docker logs ingestion
```

Tests de robustesse :

| Test | Commande | Attendu |
|---|---|---|
| Arrêt propre | `docker stop machine_01` | arrêt en moins d'une seconde, code de sortie 0 |
| Panne Postgres | `docker compose -f docker-compose.dev.yml restart postgres` | l'ingestion logue l'erreur puis se reconnecte seule |
| Reconnexion MQTT | `docker compose -f docker-compose.dev.yml restart mosquitto` | simulateurs et ingestion se reconnectent seuls |

## 9. Arrêter et nettoyer

```
docker rm -f ingestion machine_01 machine_02
docker compose -f docker-compose.dev.yml down        # garde les données Postgres
docker compose -f docker-compose.dev.yml down -v     # supprime aussi le volume : base vide
```

## 10. Déployer sur la Dedibox

Le principe : Git fait le lien entre les deux machines.

1. Sur Windows : `git push`.
2. Sur la Dedibox : `git clone` (la première fois) ou `git pull`, puis recréer le `.env` (il n'est pas dans Git).
3. Reprendre les étapes 3 à 7 ci-dessus. Les ports hôte par défaut (5433 et 1884) sont libres à changer via `.env` si besoin.

Le déploiement en une seule commande (`docker compose up -d`) sera fourni à l'étape 2.

> Ce parcours a été testé sur Windows avec Docker Desktop. Il n'a **pas encore été exécuté sur la Dedibox**.

## Dépannage

| Symptôme | Cause | Solution |
|---|---|---|
| `docker : le terme n'est pas reconnu` | `PATH` non rechargé | ouvrir un nouveau terminal ou redémarrer VS Code |
| `failed to connect to the docker API` | Docker Desktop arrêté | le lancer et attendre « Engine running » |
| `ports are not available ... 5432` ou `1883` | port déjà pris sur la machine (Postgres ou Mosquitto local) | changer `POSTGRES_HOST_PORT` / `MQTT_HOST_PORT` dans `.env` |
| `Connection refused` pendant la migration | Postgres pas encore prêt | attendre et relancer ; avec `up --wait` ce cas ne devrait pas arriver |
| `failed to resolve host 'postgres'` | conteneur lancé hors du réseau `thermoflux-dev` | ajouter `--network thermoflux-dev` |
| `variable is not set` au `compose up` | `.env` absent ou incomplet | recréer `.env` depuis `.env.example` |
| Simulateur : « En attente du broker... » | Mosquitto pas démarré, ou mauvais `MQTT_HOST` | vérifier le broker ; dans un conteneur, utiliser `mosquitto` et non `localhost` |
| Log « Connexion refusee par le broker : Not authorized » | `MQTT_USERNAME` / `MQTT_PASSWORD` absents ou faux | utiliser `simulateur` ou `ingestion` avec le mot de passe du `.env` ; le client réessaie sans planter, et le message « En attente du broker... » qui suit est trompeur dans ce cas |
| Mesures absentes alors que tout est « connecté » | un compte utilisé pour autre chose que son rôle (ex. `ingestion` qui publie) : le broker ignore silencieusement | respecter les droits de [mosquitto/acl](mosquitto/acl) |
| Mosquitto redémarre en boucle | variable `MQTT_*_PASSWORD` manquante dans `.env` | voir `docker logs thermoflux-mosquitto-1` |
| Modification de mot de passe sans effet | le fichier `passwd` est généré au démarrage | `docker compose -f docker-compose.dev.yml up -d --force-recreate mosquitto` |
| Base vide après `down` puis `up` | `down -v` a supprimé le volume | utiliser `down` sans `-v` |
