# thermoflux

Mini-plateforme IoT conteneurisée : des machines simulées envoient leur température, qui est collectée, stockée puis affichée. Le métier est volontairement trivial : l'effort porte sur l'**outillage et l'architecture** (Docker, Kubernetes, migrations, observabilité, CI/CD, Terraform), avec une même base de code qui monte en gamme d'infrastructure sans être réécrite.

```
simulateurs  →  Mosquitto (MQTT)  →  ingestion  →  PostgreSQL  →  web
```

Le cadrage complet (objectifs, spécifications, étapes) est dans [IA-MD/01-PROJECT-GOALS.MD](IA-MD/01-PROJECT-GOALS.MD). Pour installer et lancer le projet : [INSTALL.md](INSTALL.md).

## État d'avancement

| Étape | Contenu | État |
|---|---|---|
| 1 | Code Python en local | **en cours** : simulateur ✅, ingestion ✅, migrations ✅, web ⏳ |
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
| `web` | `web/` | Affichage des températures courantes. | sans état (à venir) |

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

**Tout en UTC.** `TIMESTAMPTZ` en base, suffixe `Z` dans les messages. La conversion en heure locale se fera à l'affichage seulement.

**Configuration par variables d'environnement.** Aucun secret dans le code ni dans Git : `.env` est ignoré, `.env.example` documente les variables. Les logs vont sur stdout, ce qui laisse Docker ou Kubernetes les collecter.

**Mosquitto authentifié, droits par compte.** L'accès anonyme est refusé. Deux comptes, avec des droits minimaux définis dans [mosquitto/acl](mosquitto/acl) : `simulateur` peut seulement **publier** sur `usine/machines/+/temperature`, `ingestion` peut seulement **lire** ce topic. Un simulateur compromis ne peut donc pas écouter les autres, et l'ingestion ne peut pas injecter de fausses mesures. Le fichier de mots de passe n'est pas dans Git : [mosquitto/init.sh](mosquitto/init.sh) le génère au démarrage du conteneur à partir de variables d'environnement (même mécanisme qu'un `Secret` Kubernetes plus tard). Vérifié : connexion anonyme et mauvais mot de passe refusés, droits de lecture / écriture respectés, aucun mot de passe dans les logs.
Compromis : les 10 simulateurs **partagent un seul compte**, car un compte par machine n'apporte rien tant qu'on ne restreint pas chaque machine à son propre topic. Surtout, **les mots de passe circulent en clair** tant que TLS n'est pas activé : acceptable sur le réseau interne Docker, pas sur Internet. TLS reste à faire.

**Ce qui serait différent en production réelle :** Postgres managé ou géré par un opérateur avec réplicas, secrets dans un coffre, TLS partout, plusieurs nœuds physiques.

## Structure du dépôt

```
thermoflux/
├── README.md, INSTALL.md
├── .env.example               # variables attendues (le vrai .env n'est pas commité)
├── docker-compose.dev.yml     # socle de dev : Mosquitto + Postgres
├── simulateur/                # Dockerfile, requirements.txt, simulateur.py
├── ingestion/                 # Dockerfile, requirements.txt, ingestion.py
├── db/                        # Dockerfile, alembic.ini, migrations/ (job migrate)
├── mosquitto/                 # mosquitto.conf, acl, init.sh (génère les mots de passe)
└── IA-MD/                     # documents de cadrage
```

Les dossiers `web/`, `k8s/` et `terraform/` apparaîtront aux étapes correspondantes.

## Licence

Apache 2.0, voir [LICENSE](LICENSE).
