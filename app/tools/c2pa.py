"""Couche 2 : Vérification des Content Credentials (C2PA) dans les sections JPEG/PNG."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

C2PA_SIGNATURES = (b"c2pa", b"jumb", b"urn:c2pa", b"c2pa.claim", b"caBX")


def _scan_jpeg_for_c2pa(data: bytes) -> dict[str, Any]:
    """Parcourt les marqueurs JPEG (APP11 / JUMBF / APP1 XMP) à la recherche de données C2PA."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return {"found": False, "sections": []}

    pos = 2
    sections_found: list[str] = []
    length = len(data)

    while pos + 4 <= length:
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        pos += 2

        # SOS (Start of Scan) ou EOI : fin des en-têtes
        if marker in (0xDA, 0xD9):
            break
        # Marqueurs sans payload
        if marker == 0x00 or (0xD0 <= marker <= 0xD7) or marker == 0x01:
            continue

        if pos + 2 > length:
            break
        seg_len = struct.unpack(">H", data[pos : pos + 2])[0]
        if seg_len < 2 or pos + seg_len > length:
            break

        payload = data[pos + 2 : pos + seg_len]
        # APP11 = 0xEB (JUMBF / C2PA), APP1 = 0xE1 (XMP)
        if marker in (0xEB, 0xE1):
            lower_payload = payload.lower()
            if any(sig.lower() in lower_payload for sig in C2PA_SIGNATURES):
                sections_found.append(f"APP{marker - 0xE0}")

        pos += seg_len

    return {"found": bool(sections_found), "sections": sections_found}


def _scan_png_for_c2pa(data: bytes) -> dict[str, Any]:
    """Parcourt les chunks PNG (caBX / iTXt / tEXt) à la recherche de données C2PA."""
    png_sig = b"\x89PNG\r\n\x1a\n"
    if len(data) < 8 or data[:8] != png_sig:
        return {"found": False, "sections": []}

    pos = 8
    sections_found: list[str] = []
    length = len(data)

    while pos + 12 <= length:
        chunk_len = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        data_start = pos + 8
        data_end = data_start + chunk_len
        if data_end + 4 > length:
            break

        chunk_data = data[data_start:data_end]
        if chunk_type == b"caBX":
            sections_found.append("caBX")
        elif chunk_type in (b"iTXt", b"tEXt", b"zTXt"):
            if any(sig.lower() in chunk_data.lower() for sig in C2PA_SIGNATURES):
                sections_found.append(chunk_type.decode("ascii", errors="ignore"))

        pos = data_end + 4
        if chunk_type == b"IEND":
            break

    return {"found": bool(sections_found), "sections": sections_found}


def check_c2pa(path: str) -> dict[str, Any]:
    """Recherche les Content Credentials (C2PA) dans les sections JPEG/PNG.

    Si absent, le statut retourné est strictement 'aucune provenance vérifiable'
    (jamais une accusation de fraude).

    Args:
        path: Chemin vers le fichier image.

    Returns:
        Dictionnaire structuré avec statut C2PA, sections détectées et score neutre/faible.
    """
    img_path = Path(path)
    if not img_path.exists():
        raise FileNotFoundError(f"Image introuvable : {path}")

    raw = img_path.read_bytes()
    if raw[:2] == b"\xff\xd8":
        container = "JPEG"
        scan = _scan_jpeg_for_c2pa(raw)
    elif raw[:8] == b"\x89PNG\r\n\x1a\n":
        container = "PNG"
        scan = _scan_png_for_c2pa(raw)
    else:
        container = "AUTRE"
        has_sig = any(sig.lower() in raw.lower() for sig in C2PA_SIGNATURES)
        scan = {"found": has_sig, "sections": ["raw_scan"] if has_sig else []}

    if scan["found"]:
        return {
            "couche": "c2pa",
            "statut": "provenance_c2pa_detectee",
            "c2pa_present": True,
            "conteneur": container,
            "sections_detectees": scan["sections"],
            "score": 0.0,
            "note": "Des métadonnées Content Credentials (C2PA) ont été détectées dans le fichier.",
        }

    return {
        "couche": "c2pa",
        "statut": "aucune provenance vérifiable",
        "c2pa_present": False,
        "conteneur": container,
        "sections_detectees": [],
        "score": 0.20,
        "note": (
            "Aucune provenance vérifiable : l'absence de Content Credentials (C2PA) est fréquente "
            "sur les smartphones grand public et ne constitue pas une preuve de fraude."
        ),
    }
