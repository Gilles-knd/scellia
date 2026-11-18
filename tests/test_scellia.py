"""Tests minimum pytest pour ScellIA : format dossier, audit log, /decision et jeu de test."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import MAX_UPLOAD_BYTES, app
from app.tools.audit import append_audit_log

ROOT_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT_DIR / "samples"


@pytest.fixture()
def isolated_audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isole le journal d'audit JSONL dans un fichier temporaire par test."""
    log_file = tmp_path / "audit_log.jsonl"
    monkeypatch.setenv("SCELLIA_AUDIT_LOG", str(log_file))
    return log_file


def test_append_audit_log_is_append_only(isolated_audit_log: Path) -> None:
    """Vérifie que append_audit_log ajoute une ligne JSONL par appel sans écraser les précédentes."""
    append_audit_log("case_1", "extract_exif", {"a": 1}, {"score": 0.1}, acteur="agent")
    append_audit_log("case_1", "check_c2pa", {"b": 2}, {"score": 0.2}, acteur="agent")
    append_audit_log("case_1", "decision_humaine_valider", {"decision": "valider"}, {"statut": "ok"}, acteur="Claire")

    lines = isolated_audit_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [p["action"] for p in parsed] == [
        "extract_exif",
        "check_c2pa",
        "decision_humaine_valider",
    ]
    assert parsed[2]["acteur"] == "Claire"


def test_decision_requires_non_empty_reviewer(isolated_audit_log: Path) -> None:
    """Vérifie que POST /decision sans reviewer_name (ou vide) renvoie HTTP 400."""
    client = TestClient(app)

    resp_missing = client.post(
        "/decision",
        json={"case_id": "abc123", "decision": "valider"},
    )
    assert resp_missing.status_code == 400

    resp_blank = client.post(
        "/decision",
        json={"case_id": "abc123", "decision": "valider", "reviewer_name": "   "},
    )
    assert resp_blank.status_code == 400

    resp_ok = client.post(
        "/decision",
        json={"case_id": "abc123", "decision": "valider", "reviewer_name": "Claire Martin"},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["statut"] == "valide_par_humain"


def test_instruct_three_samples_and_audit_trail(isolated_audit_log: Path) -> None:
    """Vérifie le format du case file, la cohérence des 3 images de test et les lignes d'audit."""
    manifest = json.loads((SAMPLES_DIR / "manifest.json").read_text(encoding="utf-8"))
    declared_date = manifest["declared_date"]
    claim_type = manifest["claim_type"]

    client = TestClient(app)
    results: dict[str, dict] = {}

    for sample in manifest["samples"]:
        img_path = ROOT_DIR / sample["file"]
        with open(img_path, "rb") as f:
            resp = client.post(
                "/instruct",
                files={"file": (img_path.name, f, "image/jpeg")},
                data={"claim_type": claim_type, "declared_date": declared_date},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Format du dossier scellé
        assert "case_id" in data and data["case_id"]
        assert "score_global" in data
        assert set(data["scores_par_couche"].keys()) == {"exif", "c2pa", "ela", "vision"}
        assert isinstance(data["preuves"], list) and len(data["preuves"]) >= 4
        assert "recommandation" in data and data["recommandation"]
        assert data["statut"] == "en_attente_validation_humaine"

        results[sample["id"]] = data

        # Vérifier qu'une ligne d'audit existe par appel d'outil (4 analyseurs + assemblage = 5)
        audit_lines = [
            json.loads(line)
            for line in isolated_audit_log.read_text(encoding="utf-8").strip().splitlines()
            if json.loads(line)["case_id"] == data["case_id"]
        ]
        actions = {entry["action"] for entry in audit_lines}
        assert {
            "extract_exif",
            "check_c2pa",
            "error_level_analysis",
            "vision_review",
            "assemble_case_file",
        }.issubset(actions)

    # Les 3 scores globaux sont distincts et cohérents avec le manifest
    score_vraie = results["photo_vraie"]["score_global"]
    score_retouchee = results["photo_retouchee"]["score_global"]
    score_generee = results["image_generee"]["score_global"]

    assert len({score_vraie, score_retouchee, score_generee}) == 3
    assert score_retouchee > score_vraie
    assert score_generee > score_vraie
    assert len(results["photo_retouchee"]["zones_suspectes"]) > 0


def test_upload_size_limit(isolated_audit_log: Path) -> None:
    """Vérifie que les fichiers dépassant 10 Mo sont rejetés avec HTTP 413."""
    client = TestClient(app)
    oversized = b"\xff\xd8\xff" + b"0" * MAX_UPLOAD_BYTES
    resp = client.post(
        "/instruct",
        files={"file": ("huge.jpg", oversized, "image/jpeg")},
        data={"claim_type": "Collision", "declared_date": "2026-11-18"},
    )
    assert resp.status_code == 413
