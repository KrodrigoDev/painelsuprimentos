"""Atalho: python run.py  (equivale a python -m app.main)."""
from app import desempenho
from app.config import SETTINGS
from app.main import app

if __name__ == "__main__":
    desempenho.iniciar_aquecimento()             # lê as bases em segundo plano antes do 1º acesso
    app.run(debug=SETTINGS.debug, port=SETTINGS.port, host="0.0.0.0")
