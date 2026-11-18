"""Initialisation centralisée du client Google GenAI (AI Studio ou Vertex AI via ADC)."""

from __future__ import annotations

import os
from google import genai


def get_gemini_model() -> str:
    """Retourne le nom du modèle Gemini configuré via GEMINI_MODEL (défaut : gemini-2.5-flash)."""
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"


def is_vertex_mode() -> bool:
    """Indique si le mode Vertex AI est activé via GEMINI_USE_VERTEX=true."""
    return os.getenv("GEMINI_USE_VERTEX", "").strip().lower() in ("1", "true", "yes")


def has_gemini_credentials() -> bool:
    """Vérifie si les variables d'environnement requises pour Gemini sont présentes."""
    if is_vertex_mode():
        return bool(os.getenv("GEMINI_PROJECT", "").strip() and os.getenv("GEMINI_LOCATION", "").strip())
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def get_genai_client() -> genai.Client | None:
    """Instancie le client google-genai sans aucun identifiant codé en dur.

    Supporte :
    - AI Studio : GEMINI_API_KEY
    - Vertex AI : GEMINI_USE_VERTEX=true + GEMINI_PROJECT + GEMINI_LOCATION (via ADC)
    """
    if is_vertex_mode():
        project = os.getenv("GEMINI_PROJECT", "").strip()
        location = os.getenv("GEMINI_LOCATION", "").strip() or "europe-west1"
        if not project:
            return None
        return genai.Client(vertexai=True, project=project, location=location)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    return genai.Client(api_key=api_key)
