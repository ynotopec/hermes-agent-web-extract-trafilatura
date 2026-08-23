# Trafilatura-Local

Service HTTP local pour l'extraction de contenu web basé sur **Trafilatura** — le meilleur outil open-source de text extraction, avec un **F1-score de 0.924** contre 0.690 pour beautifulsoup4.

## Pourquoi ?

`web_fetch.py` original utilisait une extraction HTML→markdown basée sur des regex, avec un F1-estimé ~0.69. Cela causait des problèmes de boilerplate et de détection de contenu.

Après analyse de la littérature et benchmarks officiels (ScrapingHub/Zyte, Trafilatura eval), **trafilatura est le meilleur outil open-source** :
- F1 0.924 vs 0.690 (beautifulsoup4) et 0.663 (html2text)
- Boilerplate removal robust
- Gestion des HTML malformés
- Multi-langue (FR, EN, DE, etc.)

Le service trafilatura local (port 8990) existait déjà via le plugin `web-extract`. Ce projet le versionne proprement avec un systemd service persistant.

## Architecture

```
web_fetch.py → HTTP request → Trafilatura-Local (FastAPI, port 8990)
                                       ↓
                                trafilatura.extract()
                                       ↓
                                Markdown output
```

## Installation

```bash
# 1. Créer l'environnement virtuel (déjà fait)
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# 2. Installer le service systemd
cp trafilatura-local.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable trafilatura-local.service

# 3. Démarrer
systemctl --user start trafilatura-local.service
```

## Utilisation

### API

**Health check :**
```bash
curl http://localhost:8990/health
```

**Extraction single/multiple URL :**
```bash
# GET
curl 'http://localhost:8990/extract?url=https://example.com'

# POST
curl -X POST -H 'Content-Type: application/json' \
  -d '{"urls": ["https://example.com"], "format": "markdown"}' \
  http://localhost:8990/extract
```

### Depuis web_fetch.py

Remplacer l'appel curl local par une requête HTTP au service :

```python
# Avant (ancien web_fetch.py)
import subprocess
result = subprocess.run(["python3", "web_fetch.py", url], ...)

# Après (nouveau)
import requests
resp = requests.post("http://localhost:8990/extract", json={
    "urls": [url], "format": "markdown"
})
content = resp.json()["results"][0]["content"]
```

## Fichiers

| Fichier | Rôle |
|---------|------|
| `server.py` | Serveur FastAPI principal |
| `pyproject.toml` | Méta-données du projet |
| `requirements.txt` | Dépendances Python |
| `trafilatura-local.service` | Service systemd (--user) |
| `.gitignore` | Ignore le venv et fichiers temporaires |

## Survie au reboot

Le service systemd est enable → automatiquement démarré à chaque boot. Vérification :
```bash
systemctl --user is-enabled trafilatura-local  # enabled
systemctl --user is-active trafilatura-local   # active
```

## Benchmarks de référence

Source : [ScrapingHub/Zyte Article Extraction Benchmark](https://github.com/scrapinghub/article-extraction-benchmark) + [Trafilatura Evaluation](https://trafilatura.readthedocs.io/en/latest/evaluation.html)

| Outil | F1 | Précision | Rappel |
|-------|-----|-----------|--------|
| **Trafilatura (standard)** | **0.924** | 0.906 | 0.943 |
| Trafilatura (precision) | 0.920 | 0.925 | 0.915 |
| magic-html | 0.889 | 0.887 | 0.891 |
| justext | 0.862 | 0.864 | 0.859 |
| beautifulsoup4 | 0.690 | 0.532 | 0.980 |
| html2text | 0.663 | 0.525 | 0.900 |
