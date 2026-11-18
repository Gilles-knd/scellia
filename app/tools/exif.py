"""Couche 1 : Extraction et vérification des métadonnées EXIF via Pillow."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

EDITING_SOFTWARE_KEYWORDS = (
    "photoshop",
    "gimp",
    "lightroom",
    "snapseed",
    "canva",
    "affinity",
    "pixelmator",
    "paint.net",
    "midjourney",
    "stable diffusion",
    "dall-e",
)


def _parse_exif_datetime(raw: str | None) -> datetime | None:
    """Parse une date EXIF standard (YYYY:MM:DD HH:MM:SS) ou ISO."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(cleaned[:19], fmt)
        except ValueError:
            continue
    return None


def _parse_declared_date(raw: str | None) -> datetime | None:
    """Parse la date déclarée par l'assuré."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(cleaned[:10], fmt)
        except ValueError:
            continue
    return None


def _convert_gps_to_decimal(gps_info: dict[int, Any]) -> dict[str, float] | None:
    """Convertit les coordonnées GPS EXIF DMS en degrés décimaux."""
    try:
        lat_vals = gps_info.get(2)
        lat_ref = gps_info.get(1, "N")
        lon_vals = gps_info.get(4)
        lon_ref = gps_info.get(3, "E")
        if not lat_vals or not lon_vals:
            return None

        def to_deg(vals: Any) -> float:
            d, m, s = [float(v) for v in vals]
            return d + (m / 60.0) + (s / 3600.0)

        lat = to_deg(lat_vals)
        if str(lat_ref).upper() == "S":
            lat = -lat
        lon = to_deg(lon_vals)
        if str(lon_ref).upper() == "W":
            lon = -lon
        return {"latitude": round(lat, 6), "longitude": round(lon, 6)}
    except Exception:
        return None


def extract_exif(path: str, declared_date: str | None = None) -> dict[str, Any]:
    """Extrait les métadonnées EXIF (date/heure, GPS, appareil, logiciel) et détecte les incohérences datées.

    Args:
        path: Chemin vers l'image à analyser.
        declared_date: Date du sinistre déclaré (YYYY-MM-DD), utilisée pour détecter les incohérences temporelles.

    Returns:
        Dictionnaire structuré avec les champs EXIF, les incohérences et un score de risque [0, 1].
    """
    img_path = Path(path)
    if not img_path.exists():
        raise FileNotFoundError(f"Image introuvable : {path}")

    with Image.open(img_path) as img:
        exif = img.getexif()
        image_format = img.format
        dimensions = {"width": img.width, "height": img.height}

    tags: dict[str, Any] = {}
    if exif:
        for tag_id, value in exif.items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            tags[tag_name] = value
        # Sous-IFD Exif (DateTimeOriginal, etc.)
        try:
            exif_ifd = exif.get_ifd(0x8769)
            for tag_id, value in exif_ifd.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                tags[tag_name] = value
        except Exception:
            pass
        # Sous-IFD GPS
        gps_decimal = None
        try:
            gps_ifd = exif.get_ifd(0x8825)
            if gps_ifd:
                gps_decimal = _convert_gps_to_decimal(dict(gps_ifd))
        except Exception:
            gps_decimal = None
    else:
        gps_decimal = None

    make = str(tags.get("Make", "")).strip() or None
    model = str(tags.get("Model", "")).strip() or None
    software = str(tags.get("Software", "")).strip() or None
    raw_dt = tags.get("DateTimeOriginal") or tags.get("DateTimeDigitized") or tags.get("DateTime")
    dt_str = str(raw_dt).strip() if raw_dt else None

    has_exif = bool(tags)
    incoherences: list[dict[str, Any]] = []
    score = 0.05

    if not has_exif:
        score = 0.45
        incoherences.append(
            {
                "type": "exif_absent",
                "severite": "moyenne",
                "detail": "Aucune métadonnée EXIF présente (suppression possible par messagerie, export web ou génération IA).",
            }
        )
    else:
        capture_dt = _parse_exif_datetime(dt_str)
        claim_dt = _parse_declared_date(declared_date)
        if capture_dt and claim_dt and capture_dt.date() < claim_dt.date():
            delta_days = (claim_dt.date() - capture_dt.date()).days
            score = max(score, 0.78)
            incoherences.append(
                {
                    "type": "date_prise_anterieure_au_sinistre",
                    "severite": "elevee",
                    "detail": (
                        f"Date de prise EXIF ({capture_dt.strftime('%Y-%m-%d')}) antérieure "
                        f"de {delta_days} jour(s) à la date de sinistre déclarée ({claim_dt.strftime('%Y-%m-%d')})."
                    ),
                    "date_exif": capture_dt.isoformat(),
                    "date_declaree": claim_dt.strftime("%Y-%m-%d"),
                    "ecart_jours": delta_days,
                }
            )
        elif not capture_dt:
            score = max(score, 0.30)
            incoherences.append(
                {
                    "type": "horodatage_exif_absent",
                    "severite": "faible",
                    "detail": "Métadonnées EXIF présentes mais sans date de prise de vue (DateTimeOriginal).",
                }
            )

        if software and any(kw in software.lower() for kw in EDITING_SOFTWARE_KEYWORDS):
            score = min(1.0, max(score, 0.55) + 0.15)
            incoherences.append(
                {
                    "type": "logiciel_edition_detecte",
                    "severite": "elevee",
                    "detail": f"Logiciel d'édition détecté dans le champ EXIF Software : '{software}'.",
                }
            )

        if not make and not model:
            score = min(1.0, score + 0.10)

    return {
        "couche": "exif",
        "score": round(min(1.0, max(0.0, score)), 3),
        "has_exif": has_exif,
        "format": image_format,
        "dimensions": dimensions,
        "appareil": {"make": make, "model": model},
        "logiciel": software,
        "date_prise_vue": dt_str,
        "gps": gps_decimal,
        "incoherences": incoherences,
    }
