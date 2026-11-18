"""Journal d'audit immuable (append-only JSONL) pour ScellIA."""

from __future__ import annotations

import fcntl
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.Lock()


def get_audit_log_path() -> Path:
    """Retourne le chemin du journal d'audit JSONL (configurable par variable d'environnement)."""
    default_path = Path(os.getenv("SCELLIA_AUDIT_LOG", "data/audit_log.jsonl"))
    default_path.parent.mkdir(parents=True, exist_ok=True)
    return default_path


def append_audit_log(
    case_id: str,
    action: str,
    entree: Any,
    sortie: Any,
    horodatage: str | None = None,
    acteur: str = "agent",
) -> dict[str, Any]:
    """Ajoute une ligne immuable au journal JSONL (une ligne par appel d'outil ou décision humaine).

    Args:
        case_id: Identifiant unique du dossier.
        action: Nom de l'outil ou de l'action exécutée.
        entree: Paramètres d'entrée (sérialisables en JSON).
        sortie: Résultat produit (sérialisable en JSON).
        horodatage: Horodatage ISO-8601 UTC (généré automatiquement si absent).
        acteur: Identifiant de l'acteur ("agent", "system", ou nom du réviseur humain).

    Returns:
        L'enregistrement écrit dans le journal.
    """
    timestamp = horodatage or datetime.now(timezone.utc).isoformat()
    record = {
        "horodatage": timestamp,
        "case_id": str(case_id),
        "acteur": str(acteur),
        "action": str(action),
        "entree": entree,
        "sortie": sortie,
    }
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    log_path = get_audit_log_path()

    with _WRITE_LOCK:
        with open(log_path, "a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return record


def read_audit_log(case_id: str | None = None) -> list[dict[str, Any]]:
    """Lit les entrées du journal d'audit (filtrées optionnellement par case_id)."""
    log_path = get_audit_log_path()
    if not log_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with _WRITE_LOCK:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if case_id is None or record.get("case_id") == case_id:
                    entries.append(record)
    return entries
