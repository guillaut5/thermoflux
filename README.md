# thermoflux

Mini-plateforme IoT conteneurisée : des machines simulées envoient leur température, qui est collectée, stockée puis affichée. Le métier est volontairement trivial : l'effort porte sur l'**outillage et l'architecture** (Docker, Kubernetes, migrations, observabilité, CI/CD, Terraform), avec une même base de code qui monte en gamme d'infrastructure sans être réécrite.

```
simulateurs  →  Mosquitto (MQTT)  →  ingestion  →  PostgreSQL  →  web
```

Le cadrage complet (objectifs, spécifications, étapes) est dans [IA-MD/01-PROJECT-GOALS.MD](IA-MD/01-PROJECT-GOALS.MD). Pour installer et lancer le projet : [INSTALL.md](INSTALL.md).

## État d'avancement

| Étape | Contenu | État |
|---|---|---|
| 1 | Code Python en local | simulateur ✅, ingestion ✅, migrations ✅, web ✅ (reste à valider dans un navigateur, voir ci-dessous) |
| 2 | `docker compose` complet sur la Dedibox | à faire |
| 3 | Kubernetes (k3s) | à faire |
| 4 | k3d multi-nœuds | à faire |
| 5 | Observabilité | à faire |
| 6 | CI/CD | à faire |
| 7 | Terraform (option) | à faire |

## Composants

| Composant | Dossier | Rôle | État applicatif |
|---|---|---|---|
| `simulateur` | [simulateur/](simulateur/) | Une machine qui publie sa température toutes les 5 s. Une seule image, lancée N fois avec un `MACHINE_ID` différent. | sans état |
| `mosquitto` | [mosquitto/](mosquitto/) | Broker MQTT (image officielle `eclipse-mosquitto:2`). | quasi sans état |
| `ingestion` | [ingestion/](ingestion/) | S'abonne à `usine/machines/+/temperature` et insère dans Postgres. | sans état |
| `postgres` | [db/](db/) | Historique des mesures (image officielle `postgres:16`). Schéma géré par Alembic. | **avec état** |
| `web` | [web/](web/) | FastAPI : connexion, tableau des dernières températures (rafraîchi toutes les 5 s), API JSON et `/health`. | sans état |

### Message MQTT

Topic `usine/machines/<MACHINE_ID>/temperature`, charge utile :

```json
{ "machine_id": "machine_03", "ts": "2026-11-19T13:33:24.178Z", "temperature_c": 37.24 }
```

`ts` est toujours en UTC. La température suit `base + amplitude × sin(2π·t/période) + bruit gaussien`, avec une phase aléatoire par machine et, rarement, une « surchauffe » de quelques minutes.

## Choix techniques et compromis

Chaque choix est noté avec ce qu'il coûte et à quelle échelle il devient utile ou superflu.

**MQTT plutôt que Kafka.** MQTT est léger et fait pour l'IoT, et 10 machines à 1 mesure / 5 s font 2 messages/s. Kafka ne se justifierait qu'à des volumes très supérieurs, ou pour rejouer l'historique des messages. Contrepartie : Mosquitto ne conserve pas les messages si personne n'écoute.

**Une file entre MQTT et Postgres dans l'ingestion.** Le callback MQTT valide le message et le met dans une file bornée (10 000). Un thread d'écriture l'insère et se reconnecte à Postgres tout seul. Vérifié : en redémarrant Postgres, l'ingestion se reconnecte en ~2 s et aucune mesure n'est perdue (la plus grande pause entre deux mesures reste l'intervalle normal de 2 s). Contrepartie : la file est en mémoire, donc un arrêt brutal de l'ingestion pendant une panne de Postgres perd ce qu'elle contient. Au-delà de 10 000 mesures en attente, les nouvelles sont perdues et loguées. Une vraie garantie demanderait des sessions MQTT persistantes ou un autre mécanisme de reprise.

**Un `INSERT` par message.** Simple et lisible, suffisant à ce volume (172 800 lignes/jour). L'insertion par lots est prévue comme exercice, avec mesure du gain.

**Message invalide : logué et ignoré.** Un JSON cassé, un champ manquant, un `ts` illisible ou une température non numérique ne font pas planter le service.

**Migrations Alembic, en SQL explicite.** La migration `0001` écrit le `CREATE TABLE` et l'index tels qu'ils sont spécifiés, sans ORM. Elle tourne dans un conteneur dédié `migrate`, **avant** les applications. Contrepartie : Alembic et SQLAlchemy sont de lourdes dépendances pour une seule table, mais c'est l'outil standard et il servira à l'exercice expand / contract.

**Web : authentification par session et mot de passe haché.** Un seul utilisateur (`WEB_USER`), dont le mot de passe n'existe qu'en **hash scrypt** dans l'environnement (`WEB_PASSWORD_HASH`). La session est un cookie signé (`HttpOnly`, `SameSite=Lax`, 8 h). Le mot de passe est toujours vérifié, même si le nom d'utilisateur est faux, pour que le temps de réponse ne révèle pas si l'utilisateur existe. `/docs` et `/openapi.json` sont désactivés : ils décriraient l'API sans authentification. L'affichage construit les cellules avec `textContent`, jamais `innerHTML`, car `machine_id` vient du réseau.
Compromis : scrypt (bibliothèque standard, paramètres OWASP) plutôt que bcrypt ou argon2 évite une dépendance, et son format sans `$` survit à un `.env` ou à `docker run -e` sans guillemets. Argon2id reste le premier choix de l'OWASP et serait préférable dans un projet réel. Il n'y a **pas de limitation du nombre d'essais** de connexion : acceptable pour un usage local, à ajouter (ou à déléguer à un proxy) avant toute exposition. Le cookie n'est marqué `Secure` que si `COOKIE_SECURE=true`, donc il faut du HTTPS devant le web avant de l'exposer.

**Le web utilise le compte `thermoflux` de la base**, qui est propriétaire du schéma. C'est volontairement simple pour l'étape 1 : la séparation `iot_web` (lecture seule) / `iot_ingestion` / `iot_admin` est l'un des exercices bonus.

**Une connexion Postgres par requête dans le web.** Simple, et elle se rétablit seule après une panne de la base. Un pool de connexions deviendrait utile avec beaucoup de requêtes simultanées, ce qui n'est pas le cas ici. Seules les machines qui ont déjà envoyé au moins une mesure apparaissent dans le tableau : il n'y a pas de registre des machines attendues.

**Tout en UTC.** `TIMESTAMPTZ` en base, suffixe `Z` dans les messages. La conversion en heure locale se fera à l'affichage seulement.

**Configuration par variables d'environnement.** Aucun secret dans le code ni dans Git : `.env` est ignoré, `.env.example` documente les variables. Les logs vont sur stdout, ce qui laisse Docker ou Kubernetes les collecter.

**Mosquitto authentifié, droits par compte.** L'accès anonyme est refusé. Deux comptes, avec des droits minimaux définis dans [mosquitto/acl](mosquitto/acl) : `simulateur` peut seulement **publier** sur `usine/machines/+/temperature`, `ingestion` peut seulement **lire** ce topic. Un simulateur compromis ne peut donc pas écouter les autres, et l'ingestion ne peut pas injecter de fausses mesures. Le fichier de mots de passe n'est pas dans Git : [mosquitto/init.sh](mosquitto/init.sh) le génère au démarrage du conteneur à partir de variables d'environnement (même mécanisme qu'un `Secret` Kubernetes plus tard). Vérifié : connexion anonyme et mauvais mot de passe refusés, droits de lecture / écriture respectés, aucun mot de passe dans les logs.
Compromis : les 10 simulateurs **partagent un seul compte**, car un compte par machine n'apporte rien tant qu'on ne restreint pas chaque machine à son propre topic. Surtout, **les mots de passe circulent en clair** tant que TLS n'est pas activé : acceptable sur le réseau interne Docker, pas sur Internet. TLS reste à faire.

**Ce qui serait différent en production réelle :** Postgres managé ou géré par un opérateur avec réplicas, secrets dans un coffre, TLS partout, plusieurs nœuds physiques.

## Comprendre les images officielles

Une image officielle (`postgres`, `eclipse-mosquitto`) n'est pas une boîte noire : elle encode une manière d'installer et d'exploiter le logiciel, la même d'une image à l'autre. Une fois ces conventions repérées, une image inconnue se lit vite.

| Ce que j'aurais fait à la main | Ce que l'image fait à ma place | Où le voir dans le dépôt |
|---|---|---|
| Installer le paquet, créer le rôle et la base avec `createuser` / `createdb` | Les crée au **premier démarrage** à partir de `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | [docker-compose.dev.yml](docker-compose.dev.yml) |
| Choisir un dossier de données, gérer ses droits | Fixe le dossier de données (`/var/lib/postgresql/data`) pour qu'on y monte **un volume** | volume nommé `pgdata` |
| Éditer `/etc/postgresql/.../postgresql.conf` | Garde la config **dans le dossier de données** ; on la surcharge par paramètres de commande ou fichier monté | `SHOW config_file;` dans `psql` |
| Configurer un service systemd et un fichier de log | Lance **un seul processus au premier plan** et laisse les logs sur stdout | `docker logs` |
| Écrire le fichier de config à la main sur le serveur | **Monte** un fichier du dépôt en lecture seule (`:ro`) | `mosquitto.conf`, `acl` |
| Préparer l'environnement avant chaque démarrage | Passe par un **script d'entrée** qui prépare, puis lance le service | [mosquitto/init.sh](mosquitto/init.sh) reprend ce schéma |

Surprises rencontrées en chemin, typiques de ces images :
- Il n'y a **pas de rôle `postgres`** : `POSTGRES_USER` renomme le super-utilisateur (ici `thermoflux`).
- `postgresql.conf` n'est **pas dans `/etc`** mais dans le dossier de données.
- Le conteneur est **jetable**, le volume non : `down` garde les données, `down -v` les détruit.

Pour aborder une image inconnue : lire la section « Environment Variables » et « Where to store data » de sa page Docker Hub, puis `docker image inspect <image>` (variables, volumes, ports), puis entrer dedans (`docker compose exec <service> sh`) et lire son script d'entrée.

**Compromis.** L'image officielle donne des défauts pratiques, pas des défauts de production. Exemples vus ici : Postgres accepte la connexion locale sans mot de passe dans le conteneur, et Mosquitto 2 refuse l'anonyme par défaut mais n'active ni authentification ni TLS tant qu'on ne les configure pas. Elle économise l'installation, pas le durcissement. En contrepartie de cette commodité, on dépend de ses conventions : changer de version majeure de Postgres demande une migration des données, pas seulement un changement de tag.

## Structure du dépôt

```
thermoflux/
├── README.md, INSTALL.md
├── .env.example               # variables attendues (le vrai .env n'est pas commité)
├── docker-compose.dev.yml     # socle de dev : Mosquitto + Postgres
├── simulateur/                # Dockerfile, requirements.txt, simulateur.py
├── ingestion/                 # Dockerfile, requirements.txt, ingestion.py
├── web/                       # Dockerfile, app.py, auth.py, hash_password.py, templates/
├── db/                        # Dockerfile, alembic.ini, migrations/ (job migrate)
├── mosquitto/                 # mosquitto.conf, acl, init.sh (génère les mots de passe)
└── IA-MD/                     # documents de cadrage
```

Les dossiers `k8s/` et `terraform/` apparaîtront aux étapes correspondantes.

## Licence

Apache 2.0, voir [LICENSE](LICENSE).
