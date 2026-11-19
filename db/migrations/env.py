import os
import sys

from alembic import context
from sqlalchemy import create_engine, pool


def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Variable d'environnement manquante : DATABASE_URL")
    # DATABASE_URL est au format libpq (postgresql://...) ; SQLAlchemy veut
    # nommer le driver : on utilise psycopg v3.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def run_migrations_online():
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
