"""Couche 3 : Error Level Analysis (ELA) — re-compression JPEG q=90 et détection de zones suspectes."""

from __future__ import annotations

import io
import statistics
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops


def error_level_analysis(path: str, quality: int = 90, grid_size: int = 10) -> dict[str, Any]:
    """Réalise une analyse ELA (re-compression JPEG à q=90) et identifie les zones hétérogènes.

    Une retouche locale (copier-coller, tampon, ré-enregistrement partiel) ne vieillit pas
    comme le reste de l'image lors de la re-compression et produit un écart d'erreur localisé.

    Args:
        path: Chemin vers l'image à analyser.
        quality: Qualité JPEG de référence pour la re-compression (défaut : 90).
        grid_size: Découpage en grille (grid_size x grid_size) pour l'analyse zonale.

    Returns:
        Dictionnaire avec score ELA [0, 1], statistiques globales et coordonnées des zones suspectes.
    """
    img_path = Path(path)
    if not img_path.exists():
        raise FileNotFoundError(f"Image introuvable : {path}")

    with Image.open(img_path) as raw_img:
        original = raw_img.convert("RGB")
        width, height = original.size

        buffer = io.BytesIO()
        original.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        with Image.open(buffer) as recompressed:
            recompressed_rgb = recompressed.convert("RGB")
            diff = ImageChops.difference(original, recompressed_rgb).convert("L")

    # Statistiques par bloc
    block_w = max(1, width // grid_size)
    block_h = max(1, height // grid_size)
    blocks: list[dict[str, Any]] = []

    for row in range(grid_size):
        for col in range(grid_size):
            x0 = col * block_w
            y0 = row * block_h
            x1 = width if col == grid_size - 1 else (col + 1) * block_w
            y1 = height if row == grid_size - 1 else (row + 1) * block_h

            crop = diff.crop((x0, y0, x1, y1))
            pixels = list(crop.getdata())
            if not pixels:
                continue
            mean_err = sum(pixels) / len(pixels)
            max_err = max(pixels)
            blocks.append(
                {
                    "row": row,
                    "col": col,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "mean_err": mean_err,
                    "max_err": max_err,
                }
            )

    means = [b["mean_err"] for b in blocks]
    global_mean = round(sum(means) / len(means), 3) if means else 0.0
    median_err = statistics.median(means) if means else 0.0
    deviations = [abs(m - median_err) for m in means]
    mad = statistics.median(deviations) if deviations else 0.0
    stdev_err = round(statistics.pstdev(means), 3) if len(means) > 1 else 0.0

    # Seuil robuste basé sur la médiane et la MAD
    threshold_delta = max(2.2, 3.0 * mad)
    suspicious_zones: list[dict[str, Any]] = []

    for b in blocks:
        delta = abs(b["mean_err"] - median_err)
        is_high_outlier = b["mean_err"] > median_err + threshold_delta and b["mean_err"] > median_err * 1.35
        is_low_outlier = median_err > 2.5 and b["mean_err"] < median_err * 0.45 and delta > threshold_delta

        if is_high_outlier or is_low_outlier:
            direction = "erreur_elevee" if is_high_outlier else "erreur_anormalement_faible"
            intensity = min(1.0, round(delta / max(median_err + 1.0, 6.0), 3))
            suspicious_zones.append(
                {
                    "x": round(b["x0"] / width, 4),
                    "y": round(b["y0"] / height, 4),
                    "width": round((b["x1"] - b["x0"]) / width, 4),
                    "height": round((b["y1"] - b["y0"]) / height, 4),
                    "pixel_box": [b["x0"], b["y0"], b["x1"], b["y1"]],
                    "mean_error": round(b["mean_err"], 3),
                    "intensity": intensity,
                    "reason": (
                        f"Zone hétérogène ELA ({direction}) : écart de {round(delta, 2)} "
                        f"vs médiane {round(median_err, 2)}."
                    ),
                }
            )

    # Trier par intensité décroissante et limiter aux 12 zones les plus marquantes
    suspicious_zones.sort(key=lambda z: z["intensity"], reverse=True)
    suspicious_zones = suspicious_zones[:12]

    # Calcul du score ELA [0, 1]
    if suspicious_zones:
        max_intensity = suspicious_zones[0]["intensity"]
        zone_factor = min(1.0, len(suspicious_zones) / 5.0)
        score = min(0.96, 0.55 + 0.25 * max_intensity + 0.16 * zone_factor)
    elif global_mean < 1.8:
        # Image très lisse ou doublement compressée sans bruit naturel de capteur
        score = 0.55
    else:
        score = 0.12

    return {
        "couche": "ela",
        "score": round(score, 3),
        "qualite_recompression": quality,
        "dimensions": {"width": width, "height": height},
        "statistiques": {
            "erreur_moyenne_globale": global_mean,
            "erreur_mediane_blocs": round(median_err, 3),
            "ecart_type_blocs": stdev_err,
            "mad_blocs": round(mad, 3),
            "nb_zones_suspectes": len(suspicious_zones),
        },
        "zones_suspectes": suspicious_zones,
    }
