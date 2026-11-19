# thermoflux — Mini-plateforme IoT conteneurisée

> Document de cadrage : idée générale, objectifs, architecture, spécifications des composants et étapes de progression.
> Destiné à être relu au fil du projet et à servir de README de départ.

---

## 1. L'idée générale

Construire en miniature une **plateforme de collecte de données IoT**, avec les outils et les pratiques des grosses structures (conteneurs, orchestration, infrastructure as code, observabilité), puis la faire monter en gamme d'infrastructure **sans réécrire le code**.

Le métier est volontairement simple et connu (des machines qui envoient une température) pour que l'effort porte entièrement sur **l'outillage et l'architecture**.

Le schéma est celui de quasiment toute plateforme de données moderne :

```
producteurs  →  bus de messages  →  consommateur  →  base de données  →  interface
```

---

## 2. Objectifs

### Objectif immédiat
Faire tourner **une fois** l'ensemble de la chaîne de bout en bout sur la Dedibox, avec `docker compose`.

### Objectifs d'apprentissage
- Manipuler concrètement Docker, puis Kubernetes (k3s / k3d), puis Terraform.
- Comprendre la différence entre services **sans état** (qu'on multiplie librement) et services **avec état** (la base).
- Gérer proprement la configuration et les secrets (jamais en dur dans le code ni dans Git).
- Pratiquer les migrations de schéma (préparation à l'exercice expand / contract).
- Observer le système (métriques, logs).

### Objectif professionnel
Disposer d'un **dépôt Git montrable en entretien**, avec un README qui explique les choix techniques **et leurs compromis** (« voilà comment je l'aurais fait à la main, voilà comment on le fait aujourd'hui, voilà où je trouve ça surdimensionné »).

---

## 3. Architecture

```
 ┌──────────────┐
 │ simulateur   │  machine_01 ─┐
 │ simulateur   │  machine_02 ─┤
 │    ...       │     ...     ─┤   MQTT publish (toutes les 5 s)
 │ simulateur   │  machine_10 ─┘
 └──────────────┘         │
                          ▼
                 ┌─────────────────┐
                 │   Mosquitto     │  broker MQTT
                 │  (port 1883)    │
                 └─────────────────┘
                          │  MQTT subscribe  usine/machines/+/temperature
                          ▼
                 ┌─────────────────┐
                 │   ingestion     │  app Python
                 └─────────────────┘
                          │  INSERT
                          ▼
                 ┌─────────────────┐
                 │   PostgreSQL    │  seul composant AVEC ÉTAT (volume persistant)
                 └─────────────────┘
                          │  SELECT
                          ▼
                 ┌─────────────────┐
                 │   web           │  app Python (FastAPI ou Flask) + login
                 │  (port 8000)    │
                 └─────────────────┘
                          │
                       navigateur
```

### Les 5 services

| Service | Image | État | Nombre d'instances |
|---|---|---|---|
| `simulateur` | **image maison** | sans état | 10 (une par machine) |
| `mosquitto` | `eclipse-mosquitto` (officielle) | quasi sans état | 1 |
| `ingestion` | **image maison** | sans état | 1 (puis 2 pour tester) |
| `postgres` | `postgres:16` (officielle) | **avec état** | 1 |
| `web` | **image maison** | sans état | 1 (puis 2-3 pour tester) |

Soit **3 images maison** à construire, et **2 images officielles** réutilisées telles quelles.

### Principe clé : une image, plusieurs conteneurs

Pour les machines émettrices : **une seule image `simulateur`**, lancée **10 fois**. Chaque conteneur reçoit son identité par variable d'environnement (`MACHINE_ID=machine_03`).

- On ne construit pas 10 images différentes : l'image est le *programme*, le conteneur est *une exécution* de ce programme avec sa configuration.
- Passer de 10 à 50 machines = changer un chiffre, pas le code. C'est la démonstration concrète du **scaling horizontal** des services sans état.

---

## 4. Spécifications des composants

### 4.1 Simulateur (une machine)

**Rôle** : simuler une machine qui publie sa température toutes les 5 secondes.

**Configuration (variables d'environnement)** :

| Variable | Exemple | Rôle |
|---|---|---|
| `MACHINE_ID` | `machine_03` | identité de la machine |
| `MQTT_HOST` | `mosquitto` | adresse du broker (nom du service) |
| `MQTT_PORT` | `1883` | |
| `INTERVAL_S` | `5` | période d'émission |
| `TEMP_BASE` | `45` | température moyenne (optionnel, sinon aléatoire au démarrage) |

**Modèle de température** (pour avoir des courbes réalistes, pas du bruit pur) :
```
temp = base + amplitude × sin(2π × t / période) + bruit gaussien
```
Exemple : base 45 °C, amplitude 5 °C, période 10 min, bruit σ = 0,3 °C.
Bonus : de temps en temps (probabilité faible), une « surchauffe » de quelques minutes, pour avoir des anomalies à visualiser plus tard.

**Topic MQTT** : `usine/machines/<MACHINE_ID>/temperature`

**Message (JSON)** :
```json
{
  "machine_id": "machine_03",
  "ts": "2026-11-18T08:30:05.123Z",
  "temperature_c": 46.82
}
```

**Comportements attendus** :
- Reconnexion automatique si le broker n'est pas encore prêt ou redémarre.
- Logs sur la sortie standard (stdout), pas dans un fichier : c'est Docker / Kubernetes qui collecte les logs.
- Arrêt propre sur signal `SIGTERM` (envoyé par Docker / Kubernetes à l'arrêt).

**Bibliothèque** : `paho-mqtt`.

---

### 4.2 Broker MQTT — Mosquitto

**Rôle** : recevoir les messages des simulateurs et les redistribuer aux abonnés.

- Image officielle `eclipse-mosquitto:2`.
- Fichier `mosquitto.conf` minimal : écoute sur 1883.
- Étape 1-2 : accès anonyme autorisé (simplicité).
- Étape ultérieure : utilisateur / mot de passe, puis éventuellement TLS.

> À noter : depuis Mosquitto 2.0, l'accès anonyme est **refusé par défaut** ; il faut l'autoriser explicitement dans la conf (`allow_anonymous true`).

---

### 4.3 Ingestion

**Rôle** : s'abonner aux températures et les écrire dans Postgres.

**Configuration** :

| Variable | Exemple |
|---|---|
| `MQTT_HOST`, `MQTT_PORT` | `mosquitto`, `1883` |
| `MQTT_TOPIC` | `usine/machines/+/temperature` |
| `DATABASE_URL` | `postgresql://thermoflux:***@postgres:5432/thermoflux` |

Le `+` dans le topic est un **joker MQTT** d'un niveau : il capte toutes les machines, y compris celles qu'on ajoutera plus tard.

**Comportements attendus** :
- Valider le message (JSON correct, champs présents) ; un message invalide est **loggué et ignoré**, il ne fait pas planter le service.
- Reconnexion automatique à MQTT **et** à Postgres.
- Point d'amélioration ultérieur : insertion **par lots** (toutes les N secondes ou N messages) plutôt qu'un `INSERT` par message.

**Bibliothèques** : `paho-mqtt`, `psycopg` (v3).

**Question à se poser à l'étape « 2 instances d'ingestion »** : avec un abonnement MQTT classique, **les deux instances reçoivent tous les messages**, donc chaque mesure est insérée deux fois. Solutions : abonnements partagés MQTT 5 (`$share/groupe/usine/machines/+/temperature`), ou contrainte d'unicité en base. C'est un excellent exercice de compréhension.

---

### 4.4 PostgreSQL

**Rôle** : stocker l'historique des mesures. Seul composant **avec état** : ses données vivent sur un **volume persistant**, qui survit à la destruction du conteneur.

**Schéma initial** (créé par migration Alembic, pas à la main) :

```sql
CREATE TABLE mesures (
    id            BIGSERIAL PRIMARY KEY,
    machine_id    TEXT        NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    temperature_c REAL        NOT NULL,
    recu_le       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_mesures_machine_ts ON mesures (machine_id, ts DESC);
```

- `ts` = heure de la mesure (côté machine) ; `recu_le` = heure d'arrivée en base. L'écart entre les deux mesure la latence de la chaîne.
- L'index `(machine_id, ts DESC)` rend instantanée la requête « dernière valeur de chaque machine ».

**Volumétrie** : 10 machines × 1 mesure / 5 s = 172 800 lignes / jour, ~63 millions / an. Négligeable au début, mais suffisant pour s'entraîner plus tard à la réindexation `CONCURRENTLY`, au partitionnement ou à la purge.

**Migrations** : outil **Alembic**. La migration tourne **avant** le démarrage des applis (un conteneur ou job dédié `migrate`).

**Utilisateurs** (étape ultérieure, principe du moindre privilège) :
- `iot_ingestion` : `INSERT` seulement ;
- `iot_web` : `SELECT` seulement ;
- `iot_admin` : propriétaire du schéma, utilisé uniquement par les migrations.

---

### 4.5 Web

**Rôle** : afficher les 10 températures courantes.

**Framework** : **FastAPI** (recommandé, très présent dans les offres d'emploi) ou **Flask** (le plus simple). Les deux conviennent.

**Pages / routes** :

| Route | Contenu |
|---|---|
| `GET /login`, `POST /login` | formulaire utilisateur / mot de passe |
| `GET /` | tableau des 10 machines : id, dernière température, heure de la mesure, âge de la mesure |
| `GET /api/dernieres` | même chose en JSON (utile pour le rafraîchissement et pour les tests) |
| `GET /health` | renvoie `200 OK` si l'appli tourne et joint la base (utilisé par Docker / Kubernetes) |

**Affichage** :
- Rafraîchissement automatique toutes les 5 s (un peu de JavaScript qui appelle `/api/dernieres`, ou plus simple : `<meta http-equiv="refresh" content="5">`).
- Bonus : une machine dont la dernière mesure date de plus de 30 s apparaît en **gris / « hors ligne »**. Ça permet de voir l'effet quand on arrête un conteneur simulateur.
- Bonus : couleur selon seuil (vert / orange / rouge).

**Requête « dernière valeur par machine »** (spécifique Postgres, très efficace avec l'index) :
```sql
SELECT DISTINCT ON (machine_id) machine_id, ts, temperature_c
FROM mesures
ORDER BY machine_id, ts DESC;
```

**Authentification** :
- Un seul utilisateur au départ, défini par variables d'environnement (`WEB_USER`, `WEB_PASSWORD_HASH`).
- Stocker un **hash** du mot de passe (bcrypt / argon2), jamais le mot de passe en clair.
- Session par cookie signé (`SECRET_KEY` en variable d'environnement).

---

## 5. Configuration et secrets

Règle absolue : **aucun secret dans le code ni dans Git.**

- Toute la configuration passe par **variables d'environnement** (principe dit *12-factor app*).
- En local / docker compose : un fichier `.env` **listé dans `.gitignore`**, et un fichier `.env.example` (sans vraies valeurs) **commité** pour documenter les variables attendues.
- Dans Kubernetes : objets `Secret` (et plus tard, éventuellement, un coffre type Vault / OpenBao).

---

## 6. Structure du dépôt

```
thermoflux/
├── README.md
├── .gitignore
├── .env.example
├── docker-compose.yml
│
├── simulateur/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── simulateur.py
│
├── ingestion/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── ingestion.py
│
├── web/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py
│   └── templates/
│       ├── login.html
│       └── index.html
│
├── db/
│   ├── alembic.ini
│   └── migrations/
│
├── mosquitto/
│   └── mosquitto.conf
│
├── k8s/                  # étape 3+
│   └── ...
│
└── terraform/            # étape 7
    └── ...
```

### Bonnes pratiques Dockerfile
- Partir d'une image légère : `python:3.12-slim`.
- Copier `requirements.txt` et faire le `pip install` **avant** de copier le code (le cache Docker évite de tout réinstaller à chaque modification du code).
- Ne pas tourner en `root` dans le conteneur (créer un utilisateur).
- `CMD` en forme tableau : `CMD ["python", "simulateur.py"]` (pour que les signaux d'arrêt arrivent bien au programme).

---

## 7. Étapes de progression

Chaque étape a un **objectif**, une **définition de « terminé »** et les **concepts appris**. Les images Docker construites à l'étape 2 sont **réutilisées telles quelles** jusqu'à la fin.

### Étape 1 — Le code Python en local
- **Objectif** : les 3 programmes fonctionnent hors Docker (Mosquitto et Postgres peuvent déjà tourner en conteneurs isolés).
- **Terminé quand** : un simulateur publie, l'ingestion insère, la page web affiche la valeur.
- **Concepts** : MQTT publish / subscribe, joker de topic, configuration par variables d'environnement.

### Étape 2 — docker compose sur la Dedibox ⭐ objectif immédiat
- **Objectif** : toute la chaîne démarre avec `docker compose up -d`.
- **Terminé quand** : la page web affiche les 10 machines qui se mettent à jour, accessible depuis ton navigateur.
- **Points techniques** :
  - 10 simulateurs : dans compose, déclarer 10 services qui partagent une même définition grâce aux **ancres YAML** (`x-simulateur: &simulateur` puis `<<: *simulateur`), chacun avec son `MACHINE_ID`.
  - `depends_on` avec `condition: service_healthy` pour que l'ingestion attende Postgres.
  - Un service `migrate` qui lance Alembic puis s'arrête.
  - Volume nommé pour Postgres.
- **Tests à faire** :
  - `docker compose stop simulateur_04` → la machine passe « hors ligne » sur la page.
  - `docker compose restart postgres` → l'ingestion se reconnecte seule, aucune perte au-delà de la coupure.
  - `docker compose down` puis `up` → l'historique est toujours là (volume persistant).
- **Concepts** : image vs conteneur, réseau interne Docker (les services se joignent par leur nom), volumes, santé des services.

### Étape 3 — Kubernetes (k3s) sur un seul nœud
- **Objectif** : la même chose, décrite en manifestes Kubernetes.
- **Correspondances** :
  - simulateur → **StatefulSet** à 10 réplicas : chaque pod reçoit un nom **stable** (`simulateur-0` … `simulateur-9`), qu'on injecte comme `MACHINE_ID`. Avec un simple Deployment, les noms seraient aléatoires et changeraient à chaque redémarrage.
  - ingestion, web → **Deployment**
  - postgres → **StatefulSet** + **PersistentVolumeClaim** (ou, plus tard, l'opérateur CloudNativePG)
  - mosquitto → Deployment + **Service**
  - mots de passe → **Secret** ; configuration → **ConfigMap**
  - accès web → **Ingress** (Traefik est fourni avec k3s)
  - migration → **Job**
- **Terminé quand** : la page web est accessible via l'Ingress et `kubectl scale statefulset simulateur --replicas=20` fait apparaître 20 machines.
- **Tests** : `kubectl delete pod web-xxxx` → Kubernetes le recrée seul (auto-réparation).
- **Concepts** : déclaratif, réplicas, auto-réparation, Service = adresse stable, sondes `livenessProbe` / `readinessProbe` (branchées sur `/health`).

### Étape 4 — k3d : simuler plusieurs nœuds sur une seule machine
- **Objectif** : un cluster de 3 « nœuds » (en réalité des conteneurs Docker sur la Dedibox).
- **Terminé quand** : les pods sont répartis entre les 3 nœuds (`kubectl get pods -o wide`).
- **Tests** : arrêter un nœud (`docker stop k3d-...-agent-1`) et observer Kubernetes replacer les pods sur les autres. Observer ce qui arrive à Postgres et à son volume : c'est là qu'on comprend pourquoi l'état est difficile.
- **Concepts** : ordonnancement (*scheduling*), panne de nœud, limites du stockage local.

### Étape 5 — Observabilité
- **Objectif** : voir ce qui se passe sans aller lire les logs à la main.
- **Contenu** :
  - chart Helm `kube-prometheus-stack` (Prometheus + Grafana + Alertmanager), rétention courte ;
  - Loki pour les logs ;
  - exposer des métriques maison : messages reçus / s, erreurs d'insertion, latence `recu_le - ts` (bibliothèque `prometheus-client`) ;
  - Grafana peut aussi lire directement Postgres → courbes des 10 températures.
- **Terminé quand** : un tableau de bord montre le débit, la latence, et une alerte se déclenche quand une machine se tait plus de 1 minute.
- **Concepts** : métriques vs logs, tableaux de bord, alertes.

### Étape 6 — CI/CD
- **Objectif** : chaque `git push` construit et publie les 3 images automatiquement.
- **Contenu** : GitHub Actions (ou GitLab CI) → build → tests → push vers un registre (GitHub Container Registry / GitLab Registry). Images taguées par numéro de commit, jamais seulement `latest`.
- **Bonus** : déploiement automatique sur le cluster, ou approche *GitOps* (Argo CD / Flux surveille le dépôt et applique les manifestes).
- **Concepts** : pipeline, registre d'images, versions immuables, « c'est le pipeline qui a les droits, pas l'humain ».

### Étape 7 (option) — Terraform
- **Objectif** : Terraform crée 3 petites instances Scaleway (provider officiel), on y installe k3s, on déploie, puis `terraform destroy`.
- **Coût** : quelques dizaines de centimes pour une heure de test.
- **Variante** : Ansible pour l'installation de k3s sur les instances créées par Terraform (la chaîne complète Terraform → Ansible → Kubernetes).
- **Concepts** : infrastructure déclarative, `plan` / `apply` / `destroy`, fichier *state*.

### Étapes bonus (exercices ciblés)
- **Migration expand / contract** : renommer `temperature_c` en `temperature` sans coupure, avec deux versions de l'ingestion qui cohabitent.
- **Moindre privilège** : utilisateurs Postgres séparés pour ingestion / web / migrations.
- **Sauvegardes** : backup automatique de Postgres, et **test de restauration**.
- **Insertion par lots** dans l'ingestion, et mesure du gain.
- **Deux instances d'ingestion** sans doublons (abonnement partagé MQTT 5).

---

## 8. Ce que le dépôt doit raconter en entretien

Le README final doit expliquer, pour chaque choix :
1. **ce qui a été fait** ;
2. **pourquoi** ;
3. **le compromis** : ce que ça coûte, et à quelle échelle ça devient utile ou superflu.

Exemples de points à mettre en avant :
- MQTT plutôt que Kafka : volumétrie et simplicité adaptées ; Kafka n'a de sens qu'à des volumes très supérieurs.
- StatefulSet pour les simulateurs : besoin d'une identité stable.
- Pourquoi Postgres reste unique alors qu'on multiplie le reste.
- Ce qui serait différent en production réelle (Postgres managé ou opérateur avec réplicas, secrets dans un coffre, TLS partout, plusieurs nœuds physiques).

---

## 9. Pièges à anticiper

| Piège | Symptôme | Parade |
|---|---|---|
| Postgres pas prêt au démarrage | l'ingestion plante au lancement | healthcheck + `depends_on` + reconnexion dans le code |
| Mosquitto 2 refuse l'anonyme | connexions refusées | `allow_anonymous true` dans la conf (étape 1-2) |
| `localhost` dans un conteneur | « connection refused » | dans Docker, joindre les services **par leur nom** (`postgres`, `mosquitto`) |
| Logs dans un fichier | rien dans `docker logs` | logger sur stdout |
| `.env` commité | secret dans l'historique Git | `.gitignore` dès le premier commit |
| Fuseaux horaires | heures décalées d'1 h | tout en UTC (`TIMESTAMPTZ`), conversion à l'affichage seulement |
| Volume oublié | base vide après `down` / `up` | volume nommé déclaré dans compose |
| Image reconstruite à chaque ligne de code | builds lents | `requirements.txt` copié avant le code dans le Dockerfile |