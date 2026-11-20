# Mémo Docker

Image = modèle figé. Conteneur = une exécution d'une image. Volume = données qui survivent au conteneur.

## Images

| Commande | Effet |
|---|---|
| `docker images` | lister les images |
| `docker build -t nom ./dossier` | construire depuis `dossier/Dockerfile` |
| `docker pull image:tag` | télécharger |
| `docker image inspect nom` | détails (variables, volumes, ports, CMD) |
| `docker history nom` | couches et tailles |
| `docker rmi nom` | supprimer (échoue si un conteneur l'utilise) |

## Conteneurs : cycle de vie

| Commande | Effet |
|---|---|
| `docker run -d --name x image` | créer **et** démarrer en arrière-plan |
| `docker ps` | conteneurs en marche |
| `docker ps -a` | tous, y compris arrêtés (`Exited`) |
| `docker stop x` | arrêter proprement (SIGTERM, puis SIGKILL après 10 s) |
| `docker start x` | relancer un conteneur arrêté (même conteneur, même config) |
| `docker restart x` | stop puis start |
| `docker kill x` | arrêt brutal |
| `docker rm x` | supprimer (doit être arrêté) |
| `docker rm -f x` | arrêter **et** supprimer |

`stop` n'efface rien. `rm` supprime le conteneur, pas ses volumes nommés.

## Options de `docker run`

| Option | Rôle |
|---|---|
| `-d` | en arrière-plan |
| `--name x` | nom fixe (sinon aléatoire) |
| `--rm` | supprimer le conteneur à l'arrêt (jobs ponctuels) |
| `-e VAR=val` | variable d'environnement |
| `--network r` | rejoindre le réseau `r` (accès aux autres par leur nom) |
| `-p hôte:conteneur` | publier un port (`-p 127.0.0.1:8000:8000` = local seulement) |
| `-v nom:/chemin` | monter un volume (`-v ./f:/chemin:ro` = fichier en lecture seule) |
| `-it` | terminal interactif |

## Observer

| Commande | Effet |
|---|---|
| `docker logs x` | logs |
| `docker logs -f --tail 20 x` | suivre en direct, 20 dernières lignes (Ctrl+C pour sortir) |
| `docker inspect x` | tout le détail (JSON) |
| `docker inspect x --format "{{.State.Status}}"` | un seul champ |
| `docker stats` | CPU et mémoire en direct |
| `docker top x` | processus du conteneur |
| `docker port x` | ports publiés |

## Entrer dans un conteneur

| Commande | Effet |
|---|---|
| `docker exec x commande` | lancer une commande dans un conteneur en marche |
| `docker exec -it x sh` | ouvrir un shell (`exit` pour sortir) |
| `docker cp x:/chemin ./local` | copier un fichier du conteneur vers le PC |

## Volumes et réseaux

| Commande | Effet |
|---|---|
| `docker volume ls` / `docker volume inspect v` | lister / détailler |
| `docker volume rm v` | supprimer **les données** |
| `docker network ls` / `docker network inspect r` | lister / voir qui est branché |

## Nettoyage

| Commande | Effet |
|---|---|
| `docker system df` | place occupée |
| `docker container prune` | supprime les conteneurs arrêtés |
| `docker image prune` | supprime les images sans nom |
| `docker system prune` | arrêtés + réseaux inutilisés + images sans nom |
| `docker system prune --volumes` | **efface aussi les volumes inutilisés** |

## Compose (ce projet : `-f docker-compose.dev.yml`)

| Commande | Effet |
|---|---|
| `docker compose -f f.yml up -d --wait` | créer et démarrer, attendre « healthy » |
| `docker compose -f f.yml ps` | état des services |
| `docker compose -f f.yml logs -f service` | logs d'un service |
| `docker compose -f f.yml down` | arrêter et supprimer, **garde** les volumes |
| `docker compose -f f.yml down -v` | idem **et supprime les volumes** (base vide) |
| `docker compose -f f.yml config` | fichier interprété (affiche les secrets en clair) |

## Pièges fréquents

| Symptôme | Cause / solution |
|---|---|
| `name is already in use` | conteneur du même nom existant : `docker rm -f nom` |
| `port is already allocated` | port pris : changer le nombre de gauche de `-p` |
| `connection refused` vers `localhost` | dans un conteneur, `localhost` = lui-même ; utiliser le nom du service |
| `failed to resolve host` | oubli de `--network` |
| Conteneur `Exited` aussitôt | `docker logs nom` donne la cause |
| Rien ne change après modification du code | reconstruire l'image (`docker build`) puis recréer le conteneur |
| `$VAR` mal lue dans `sh -c` | PowerShell la lit avant le conteneur : mettre la commande entre apostrophes `'...'` |
