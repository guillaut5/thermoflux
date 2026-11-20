"""Web : affiche la derniere temperature de chaque machine.

Routes : /login, /logout, / (page), /api/dernieres (JSON), /health.
Configuration par variables d'environnement. Logs sur stdout.
"""
import hmac
import logging
import os
import sys
from datetime import timezone
from pathlib import Path

import psycopg
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from auth import verify_password

logging.basicConfig(
    stream=sys.stdout, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("web")


def env(name, default=None, cast=str):
    value = os.environ.get(name)
    if value is None or value == "":
        if default is None:
            sys.exit("Variable d'environnement manquante : %s" % name)
        return default
    return cast(value)


DATABASE_URL = env("DATABASE_URL")
WEB_USER = env("WEB_USER")
WEB_PASSWORD_HASH = env("WEB_PASSWORD_HASH")
SECRET_KEY = env("SECRET_KEY")
# Une machine sans mesure depuis plus de ce delai est « hors ligne »
OFFLINE_AFTER_S = env("OFFLINE_AFTER_S", 30, float)
TEMP_WARN_C = env("TEMP_WARN_C", 55, float)
TEMP_ALERT_C = env("TEMP_ALERT_C", 60, float)
# A mettre a true des que le site est servi en HTTPS
COOKIE_SECURE = env("COOKIE_SECURE", "false").lower() == "true"

if len(SECRET_KEY) < 32:
    sys.exit("SECRET_KEY trop courte (32 caracteres minimum)")

# On ne publie pas /docs ni /openapi.json : ils decrivent l'API sans authentification
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="thermoflux_session",
    max_age=8 * 3600,
    same_site="lax",
    https_only=COOKIE_SECURE,
)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Derniere valeur par machine (specifique Postgres, rapide grace a l'index machine_id, ts DESC)
LATEST_SQL = """
SELECT DISTINCT ON (machine_id)
       machine_id, ts, temperature_c, EXTRACT(EPOCH FROM (now() - ts)) AS age_s
FROM mesures
ORDER BY machine_id, ts DESC
"""


def statut(age_s, temperature_c):
    if age_s > OFFLINE_AFTER_S:
        return "hors_ligne"
    if temperature_c >= TEMP_ALERT_C:
        return "alerte"
    if temperature_c >= TEMP_WARN_C:
        return "chaud"
    return "ok"


def dernieres_mesures():
    # Une connexion par requete : simple, et elle se retablit seule apres une panne
    with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
        rows = conn.execute(LATEST_SQL).fetchall()
    return [
        {
            "machine_id": machine_id,
            "ts": ts.astimezone(timezone.utc).isoformat(),
            "temperature_c": round(temperature_c, 2),
            "age_s": round(float(age_s), 1),
            "statut": statut(float(age_s), temperature_c),
        }
        for machine_id, ts, temperature_c, age_s in rows
    ]


def is_logged_in(request):
    return request.session.get("user") == WEB_USER


@app.get("/login")
def login_page(request: Request):
    if is_logged_in(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    # On verifie toujours le mot de passe, meme si l'utilisateur est faux :
    # le temps de reponse ne revele pas si l'utilisateur existe.
    password_ok = verify_password(password, WEB_PASSWORD_HASH)
    user_ok = hmac.compare_digest(username.encode(), WEB_USER.encode())
    if not (password_ok and user_ok):
        log.warning("Echec de connexion pour l'utilisateur %r", username[:50])
        return templates.TemplateResponse(
            request, "login.html", {"error": "Identifiants incorrects."}, status_code=401
        )
    request.session.clear()
    request.session["user"] = WEB_USER
    log.info("Connexion de %r", WEB_USER)
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/")
def index(request: Request):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "index.html", {"offline_after_s": OFFLINE_AFTER_S}
    )


@app.get("/api/dernieres")
def api_dernieres(request: Request):
    if not is_logged_in(request):
        return JSONResponse({"detail": "non authentifie"}, status_code=401)
    try:
        return dernieres_mesures()
    except psycopg.Error as exc:
        log.error("Erreur PostgreSQL : %s", str(exc).strip())
        return JSONResponse({"detail": "base indisponible"}, status_code=503)


@app.get("/health")
def health():
    """200 si l'appli tourne ET joint la base. Sans authentification (sondes Docker / Kubernetes)."""
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as exc:
        log.error("Health : base injoignable (%s)", str(exc).strip())
        return JSONResponse({"status": "degraded"}, status_code=503)
    return {"status": "ok"}
