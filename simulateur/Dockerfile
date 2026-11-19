FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependances d'abord : le cache Docker evite de tout reinstaller a chaque modif du code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulateur.py .

# Pas de root dans le conteneur
RUN useradd --system --no-create-home appuser
USER appuser

# Forme tableau : SIGTERM arrive directement au programme
CMD ["python", "simulateur.py"]
