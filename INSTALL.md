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

Éditer `.env` et remplacer **les trois mots de passe** (`change_me`, `change_me_too`) par de vrais mots de passe. Le fichier `.env` est ignoré par Git : ne le commite jamais. `WEB_PASSWORD_HASH` et `SECRET_KEY` restent vides pour l'instant : ils se génèrent à l'étape 8.

> **Fais ces modifications avant la première étape 3.** Postgres ne lit `POSTGRES_PASSWORD` qu'à l'initialisation du volume : si tu changes le mot de passe dans `.env` après, la base garde l'ancien et les services qui lisent le `.env` n'arrivent plus à s'y connecter (« password authentication failed »). Dans ce cas, soit tu remets l'ancien mot de passe, soit tu repars d'une base vide avec `docker compose -f docker-compose.dev.yml down -v`.

| Variable | Rôle |
|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Compte et base PostgreSQL |
| `MQTT_SIMULATEUR_PASSWORD` | Mot de passe du compte MQTT `simulateur` (publication seule) |
| `MQTT_INGESTION_PASSWORD` | Mot de passe du compte MQTT `ingestion` (lecture seule) |
| `WEB_USER` | Nom de l'utilisateur de l'interface web |
| `WEB_PASSWORD_HASH` | **Hash** du mot de passe web, généré à l'étape 8 (jamais le mot de passe en clair) |
| `SECRET_KEY` | Clé de signature des cookies de session (32 caractères minimum), générée à l'étape 8 |
| `POSTGRES_HOST_PORT` (optionnel, défaut `5433`) | Port Postgres exposé sur la machine hôte |
| `MQTT_HOST_PORT` (optionnel, défaut `1884`) | Port Mosquitto exposé sur la machine hôte |

Les ports hôte par défaut ne sont pas 5432 et 1883 : sur le PC de développement, un Postgres et un Mosquitto locaux occupaient déjà ces ports. À l'intérieur du réseau Docker, les services gardent leurs ports normaux (5432 et 1883) et se joignent par leur nom (`postgres`, `mosquitto`).

## 3. Lancer le socle (Mosquitto + Postgres)

```
docker compose -f docker-compose.dev.yml up -d --wait
```

`--wait` rend la main quand les deux services sont sains. Les ports ne sont publiés que sur `127.0.0.1` : rien n'est exposé sur le réseau.

**Noms des conteneurs.** Compose les nomme `<projet>-<service>-<numéro>`. Le projet est fixé à `thermoflux` dans le fichier compose, donc les noms sont `thermoflux-mosquitto-1` et `thermoflux-postgres-1`, identiques sur Windows et sur la Dedibox. `docker ps` les affiche. Les commandes de ce guide utilisent `docker exec <conteneur>` ; avec Compose, l'équivalent est `docker compose -f docker-compose.dev.yml exec <service> ...`. Les deux entrent dans le même conteneur.

Mosquitto exige un identifiant et un mot de passe : l'accès anonyme est refusé. Au démarrage, [mosquitto/init.sh](mosquitto/init.sh) crée les comptes `simulateur` et `ingestion` à partir des mots de passe du `.env`. Les droits de chaque compte sont dans [mosquitto/acl](mosquitto/acl).

## 4. Construire les images maison

```
docker build -t thermoflux-migrate   ./db
docker build -t thermoflux-ingestion ./ingestion
docker build -t thermoflux-simulateur ./simulateur
docker build -t thermoflux-web       ./web
```

## 5. Créer le schéma (migration)

Les commandes suivantes ont besoin des mots de passe du `.env`. On les charge dans le terminal une fois (à refaire dans chaque nouveau terminal) :

```
# PowerShell
Get-Content .env | ForEach-Object { if ($_ -match '^\s*([^#=\s]+)=(.*)$') { Set-Variable -Name $matches[1] -Value $matches[2] } }
$DATABASE_URL = "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"

# Linux / macOS (bash)
set -a; . ./.env; set +a
DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
```

`DATABASE_URL` se lit : `postgresql://` (protocole) `utilisateur` `:` `mot_de_passe` `@` `hôte` `:` `port` `/` `base`. L'hôte est `postgres`, le nom du service sur le réseau Docker, et le port est le port **interne** 5432 (pas 5433, qui n'existe que côté hôte). Si un mot de passe contient des caractères spéciaux (`@`, `:`, `/`, `%`), il faut les encoder dans l'URL ; les mots de passe alphanumériques n'ont pas ce problème.

Le conteneur `migrate` applique Alembic puis s'arrête :

```
docker run --rm --network thermoflux-dev -e DATABASE_URL=$DATABASE_URL thermoflux-migrate
```

La commande est idempotente : la relancer ne fait rien de plus. Vérifier :

```
docker exec thermoflux-postgres-1 psql -U thermoflux -c "\d mesures"
```

> La migration doit être lancée une fois Postgres sain. Si elle échoue avec « Connection refused », attendre quelques secondes après l'étape 3 et relancer.

## 6. Lancer l'ingestion

Elle se connecte à Mosquitto avec le compte `ingestion` (mot de passe `MQTT_INGESTION_PASSWORD`, déjà chargé à l'étape 5) :

```
docker run -d --name ingestion --network thermoflux-dev -e MQTT_HOST=mosquitto -e MQTT_USERNAME=ingestion -e MQTT_PASSWORD=$MQTT_INGESTION_PASSWORD -e DATABASE_URL=$DATABASE_URL thermoflux-ingestion
```

## 7. Lancer des simulateurs

Un conteneur par machine, avec son identité en variable d'environnement et le compte `simulateur` (mot de passe `MQTT_SIMULATEUR_PASSWORD`) :

```
docker run -d --name machine_01 --network thermoflux-dev -e MACHINE_ID=machine_01 -e MQTT_HOST=mosquitto -e MQTT_USERNAME=simulateur -e MQTT_PASSWORD=$MQTT_SIMULATEUR_PASSWORD thermoflux-simulateur
docker run -d --name machine_02 --network thermoflux-dev -e MACHINE_ID=machine_02 -e MQTT_HOST=mosquitto -e MQTT_USERNAME=simulateur -e MQTT_PASSWORD=$MQTT_SIMULATEUR_PASSWORD thermoflux-simulateur
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

## 8. Lancer le web

### Générer le mot de passe haché et la clé de session

Le `.env` ne contient jamais le mot de passe web en clair, seulement son **hash**. L'image web embarque l'outil pour le calculer. Le mot de passe est saisi au clavier (8 caractères minimum), sans apparaître :

```
docker run --rm -it thermoflux-web python hash_password.py
```

Copier la ligne affichée (`scrypt:65536:8:2:...`) dans `.env`, après `WEB_PASSWORD_HASH=`. Elle ne contient ni `$` ni espace, donc aucun guillemet n'est nécessaire.

Générer la clé de signature des cookies et la copier dans `.env`, après `SECRET_KEY=` :

```import
docker run --rm thermoflux-web python -c " secrets; print(secrets.token_hex(32))"
```

Recharger le `.env` dans le terminal (le bloc de l'étape 5), puis lancer le web :

```
docker run -d --name web --network thermoflux-dev -p 127.0.0.1:8000:8000 -e DATABASE_URL=$DATABASE_URL -e WEB_USER=$WEB_USER -e WEB_PASSWORD_HASH=$WEB_PASSWORD_HASH -e SECRET_KEY=$SECRET_KEY thermoflux-web
```

`-p 127.0.0.1:8000:8000` publie le port du conteneur sur ton PC, à gauche le port côté PC, à droite celui du conteneur. Ouvrir <http://127.0.0.1:8000> dans le navigateur et se connecter avec `WEB_USER` et le mot de passe choisi. Si le port 8000 est pris, change le premier nombre (par exemple `8001:8000`).

Variables du web : `DATABASE_URL`, `WEB_USER`, `WEB_PASSWORD_HASH` et `SECRET_KEY` (obligatoires) ; `OFFLINE_AFTER_S` (défaut `30`, délai sans mesure avant « hors ligne »), `TEMP_WARN_C` (défaut `55`, orange), `TEMP_ALERT_C` (défaut `60`, rouge) et `COOKIE_SECURE` (défaut `false`, à mettre à `true` derrière HTTPS) en option.

Routes : `/login`, `/` (page), `/api/dernieres` (JSON), `/health` (sans authentification, 200 si l'appli joint la base, 503 sinon).

## 9. Vérifier que ça marche

Voir passer les messages sur le broker (3 messages puis arrêt). Les mots de passe sont déjà dans l'environnement du conteneur Mosquitto, d'où les apostrophes simples :

```
docker exec thermoflux-mosquitto-1 sh -c 'mosquitto_sub -u ingestion -P "$MQTT_INGESTION_PASSWORD" -v -W 15 -C 3 -t "usine/machines/+/temperature"'
```

Vérifier que l'accès anonyme est bien refusé (doit répondre « not authorised ») :

```
docker exec thermoflux-mosquitto-1 mosquitto_pub -t usine/machines/x/temperature -m test
```

Voir les mesures arriver en base :

```
docker exec thermoflux-postgres-1 psql -U thermoflux -c "SELECT machine_id, count(*), max(ts) FROM mesures GROUP BY 1 ORDER BY 1"
```

Lire les logs d'un service :

```
docker logs machine_01
docker logs ingestion
docker logs web
```

Vérifier le web sans navigateur (`curl.exe` sous Windows) :

```
curl.exe -s http://127.0.0.1:8000/health          # {"status":"ok"}
curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8000/api/dernieres   # 401 : il faut être connecté
```

Le conteneur web a aussi une sonde de santé Docker : `docker inspect web --format "{{.State.Health.Status}}"` doit répondre `healthy`.

Tests de robustesse :

| Test | Commande | Attendu |
|---|---|---|
| Arrêt propre | `docker stop machine_01` | arrêt en moins d'une seconde, code de sortie 0 |
| Machine hors ligne | `docker stop machine_02`, puis attendre 30 s | la ligne passe en gris « Hors ligne » dans le navigateur |
| Panne de base vue du web | `docker restart thermoflux-postgres-1` | le bandeau « Données indisponibles » apparaît brièvement puis disparaît ; `/health` répond 503 pendant la coupure |
| Panne Postgres | `docker restart thermoflux-postgres-1` | l'ingestion logue l'erreur puis se reconnecte seule |
| Reconnexion MQTT | `docker restart thermoflux-mosquitto-1` | simulateurs et ingestion se reconnectent seuls |

## 10. Arrêter et nettoyer

```
docker rm -f web ingestion machine_01 machine_02
docker compose -f docker-compose.dev.yml down        # garde les données Postgres
docker compose -f docker-compose.dev.yml down -v     # supprime aussi le volume : base vide
```

## 11. Déployer sur la Dedibox

Le principe : Git fait le lien entre les deux machines.

1. Sur Windows : `git push`.
2. Sur la Dedibox : `git clone` (la première fois) ou `git pull`, puis recréer le `.env` (il n'est pas dans Git).
3. Reprendre les étapes 3 à 8 ci-dessus. Pour accéder au web depuis ton PC sans l'exposer sur Internet, utilise un tunnel SSH (`ssh -L 8000:127.0.0.1:8000 <utilisateur>@<dedibox>`) plutôt que d'ouvrir le port. Les ports hôte par défaut (5433 et 1884) sont libres à changer via `.env` si besoin.

Le déploiement en une seule commande (`docker compose up -d`) sera fourni à l'étape 2.

**Deux copies du dépôt sur une même machine Docker (par exemple un dossier de développement et un clone de test) :**
- Chaque copie a **son propre `.env`**, qui n'est pas dans Git. Les mots de passe peuvent donc différer, c'est normal.
- Le fichier compose fixe `name: thermoflux` : les deux copies partagent les mêmes conteneurs (`thermoflux-mosquitto-1`...), le même réseau et le même volume. Lancer `docker compose up` depuis la mauvaise copie recrée Mosquitto avec les mots de passe de **cette** copie, et les clients de l'autre sont alors refusés. Lance toujours Compose depuis la copie qui fait tourner la chaîne.
- Seul ce qui est commité et récupéré par `git pull` arrive dans le clone.

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
| `password authentication failed for user "thermoflux"` | le mot de passe du `.env` a changé après la création du volume : Postgres garde celui de l'initialisation | remettre l'ancien mot de passe dans `.env`, ou repartir d'une base vide (`down -v`) |
| Web : `Variable d'environnement manquante` ou `SECRET_KEY trop courte` | `WEB_USER`, `WEB_PASSWORD_HASH` ou `SECRET_KEY` absents de `.env`, ou `.env` non rechargé dans ce terminal | les renseigner (étape 8), recharger le `.env`, relancer ; voir `docker logs web` |
| Connexion web refusée avec le bon mot de passe | hash mal copié, ou hash calculé pour un autre mot de passe | recalculer avec `hash_password.py` et recopier la ligne entière dans `.env` |
| `/health` répond 503 | le web ne joint pas la base : mauvais mot de passe, ou Postgres arrêté | `docker logs web` donne la cause exacte |
| Page web affichée mais tableau vide | aucune mesure en base : ingestion ou simulateurs arrêtés | `docker ps`, puis `docker logs ingestion` |
| `port is already allocated` sur 8000 | un autre programme utilise ce port | changer le premier nombre de `-p`, par exemple `8001:8000` |
