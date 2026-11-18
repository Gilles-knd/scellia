# ScellIA — Agent d'instruction forensique de sinistres auto

MVP développé pour le hackathon **Deloitte × Google Cloud**.  
ScellIA instruit un dossier de sinistre automobile à partir d'une photo et produit un **dossier d'expertise scellé** (score de fraude par couche de preuve, chaîne de preuves, journal d'audit JSONL immuable, décision humaine obligatoire).

---

## Architecture

- **Backend** : Python FastAPI (`app/main.py`), point d'entrée unique.
- **Agent dédié (`app/agent.py`)** : SDK `google-genai`, modèle configuré via `GEMINI_MODEL` (défaut : `gemini-2.5-flash`).
  - Support AI Studio (`GEMINI_API_KEY`) et Vertex AI (`GEMINI_USE_VERTEX=true` + `GEMINI_PROJECT` + `GEMINI_LOCATION` via ADC).
  - Boucle stricte : `plan → exécution des 4 analyseurs → assemblage → journalisation`.
  - Aucune action sensible (valider, mandater un expert, rejeter) n'est accessible à l'agent : seul `POST /decision` enregistre la décision humaine.
- **4 couches d'analyse (`app/tools/`)** :
  1. `extract_exif` (`exif.py`) : extraction EXIF via Pillow (date, GPS, appareil, logiciel) et détection d'incohérences datées.
  2. `check_c2pa` (`c2pa.py`) : recherche des Content Credentials (C2PA / JUMBF / `caBX`) dans JPEG/PNG ; si absent, statut strict `"aucune provenance vérifiable"` (jamais une accusation).
  3. `error_level_analysis` (`ela.py`) : re-compression JPEG à `q=90`, analyse zonale par grille et détection de zones hétérogènes.
  4. `vision_review` (`vision.py`) : appel Gemini Vision avec sortie JSON structurée (anomalies physiques et traces de génération IA, confiance 0–1). *Choix technique de simplicité/résilience* : si aucun identifiant Gemini n'est configuré en local hors-ligne, un mode repli déterministe (`offline_heuristic_fallback`) permet d'exécuter le pipeline complet de bout en bout.
- **Assemblage & Audit** :
  - `assemble_case_file` (`assembler.py`) : agrège les 4 couches en un JSON unique avec `statut: "en_attente_validation_humaine"`.
  - `append_audit_log` (`audit.py`) : journal JSONL append-only (`data/audit_log.jsonl`), une ligne par appel d'outil et par décision humaine.
- **Frontend (`app/static/index.html`)** : page HTML unique servie par FastAPI (drag & drop, overlay des zones suspectes ELA, boutons de décision humaine, journal d'audit).

---

## Sécurité dès la conception

- Taille d'upload limitée à **10 Mo** (`HTTP 413` au-delà).
- Répertoire de travail isolé par `case_id` (`chmod 0700`).
- **Aucune persistance de l'image** après instruction : suppression immédiate du répertoire temporaire dans un bloc `finally`.
- Secrets uniquement par variables d'environnement (aucun identifiant codé en dur).
- Journal d'audit immuable (ouverture en mode append avec verrouillage `flock`).
- Protection des entrées : le type de sinistre et la date déclarée sont traités comme données non fiables et ne sont jamais injectés dans le `system_prompt`.

---

## Lancement en local & Tests

```bash
# Générer les 3 images de test et samples/manifest.json
python scripts/make_test_data.py

# Lancer les tests pytest
python -m pytest -v

# Démarrer le serveur localement
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

---

## Déploiement Google Cloud Run

```bash
gcloud auth application-default login
gcloud config set project <PROJECT_ID>
gcloud services enable run.googleapis.com aiplatform.googleapis.com
docker build -t gcr.io/<PROJECT_ID>/scellia . && docker push gcr.io/<PROJECT_ID>/scellia
gcloud run deploy scellia --image gcr.io/<PROJECT_ID>/scellia --platform managed --region europe-west1 --allow-unauthenticated --set-env-vars GEMINI_MODEL=gemini-2.5-flash,GEMINI_LOCATION=eu
```

> **Variante Vertex AI** : retirer `GEMINI_API_KEY` et ajouter `GEMINI_USE_VERTEX=true` (ainsi que `GEMINI_PROJECT=<PROJECT_ID>`).
