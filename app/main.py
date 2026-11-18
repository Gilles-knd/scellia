"""Point d'entrée unique FastAPI pour ScellIA."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from app.agent import run_instruction
from app.tools.audit import append_audit_log, get_audit_log_path

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 Mo strict
ALLOWED_DECISIONS = {"valider", "expert", "rejet_motive"}
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="ScellIA — Instruction Forensique de Sinistres Auto",
    version="1.0.0",
    description="Agent IA d'instruction de dossiers de sinistres avec preuve multicouche et décision humaine obligatoire.",
)

# Registre en mémoire des dossiers scellés (aucune image n'y est jamais stockée)
_CASE_STORE: dict[str, dict[str, Any]] = {}


class DecisionRequest(BaseModel):
    case_id: str
    decision: str
    reviewer_name: str = ""
    motif: str = ""


@app.get("/health")
def health() -> dict[str, str]:
    """Endpoint de santé pour Cloud Run."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Sert l'interface utilisateur unique."""
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Interface introuvable.")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/instruct")
async def instruct_case(
    file: UploadFile = File(...),
    claim_type: str = Form("Collision / Choc"),
    declared_date: str = Form(""),
) -> dict[str, Any]:
    """Instruit un dossier de sinistre à partir d'une photo dans un répertoire isolé, puis supprime l'image."""
    raw_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Le fichier image est vide.")
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image trop volumineuse (limite : 10 Mo).")

    # Nettoyage et bornage des entrées utilisateur non fiables
    safe_claim_type = (claim_type or "Non précisé").strip()[:120]
    safe_declared_date = (declared_date or "").strip()[:32]

    case_id = uuid.uuid4().hex[:12]
    work_dir = Path(tempfile.gettempdir()) / "scellia_cases" / case_id
    work_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(work_dir, 0o700)

    image_path = work_dir / "evidence.img"

    try:
        image_path.write_bytes(raw_bytes)
        # Vérifier que le fichier est bien une image valide
        try:
            with Image.open(image_path) as img:
                img.verify()
        except (UnidentifiedImageError, OSError):
            raise HTTPException(status_code=400, detail="Format d'image invalide ou corrompu.")

        case_file = run_instruction(
            case_id=case_id,
            image_path=str(image_path),
            claim_type=safe_claim_type,
            declared_date=safe_declared_date,
        )
        _CASE_STORE[case_id] = case_file
        return case_file
    finally:
        # Sécurité : aucune persistance de l'image après instruction (suppression immédiate du répertoire isolé)
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/decision")
def submit_decision(payload: DecisionRequest) -> dict[str, Any]:
    """Enregistre la décision humaine obligatoire et l'écrit dans le journal d'audit JSONL."""
    reviewer = (payload.reviewer_name or "").strip()
    if not reviewer:
        raise HTTPException(
            status_code=400,
            detail="Le nom du réviseur (reviewer_name) est obligatoire pour toute décision humaine.",
        )

    case_id = (payload.case_id or "").strip()
    if not case_id:
        raise HTTPException(status_code=400, detail="L'identifiant du dossier (case_id) est obligatoire.")

    decision = (payload.decision or "").strip()
    if decision not in ALLOWED_DECISIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Décision invalide. Valeurs autorisées : {sorted(ALLOWED_DECISIONS)}.",
        )

    motif = (payload.motif or "").strip()[:500]
    if decision == "rejet_motive" and not motif:
        raise HTTPException(
            status_code=400,
            detail="Un motif est obligatoire pour un rejet motivé.",
        )

    status_map = {
        "valider": "valide_par_humain",
        "expert": "expertise_terrain_declenchee",
        "rejet_motive": "rejete_avec_motif",
    }
    new_status = status_map[decision]

    if case_id in _CASE_STORE:
        _CASE_STORE[case_id]["statut"] = new_status
        _CASE_STORE[case_id]["decision_humaine"] = {
            "decision": decision,
            "reviewer_name": reviewer,
            "motif": motif,
        }

    audit_entry = append_audit_log(
        case_id=case_id,
        action=f"decision_humaine_{decision}",
        entree={"decision": decision, "motif": motif},
        sortie={"statut": new_status},
        acteur=reviewer,
    )

    return {
        "case_id": case_id,
        "statut": new_status,
        "decision": decision,
        "reviewer_name": reviewer,
        "motif": motif,
        "audit_entry": audit_entry,
    }


@app.get("/audit/{case_id}")
def get_case_audit(case_id: str) -> dict[str, Any]:
    """Retourne les lignes du journal d'audit JSONL associées à un case_id (lecture seule)."""
    log_path = get_audit_log_path()
    entries: list[dict[str, Any]] = []
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("case_id") == case_id:
                        entries.append(rec)
                except json.JSONDecodeError:
                    continue
    return {"case_id": case_id, "entries": entries}
