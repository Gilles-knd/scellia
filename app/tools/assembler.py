"""Assemblage du dossier d'expertise scellé à partir des 4 couches d'analyse."""

from __future__ import annotations

import uuid
from typing import Any

LAYER_WEIGHTS = {
    "exif": 0.30,
    "c2pa": 0.10,
    "ela": 0.35,
    "vision": 0.25,
}


def assemble_case_file(
    exif_result: dict[str, Any],
    c2pa_result: dict[str, Any],
    ela_result: dict[str, Any],
    vision_result: dict[str, Any],
    case_id: str | None = None,
) -> dict[str, Any]:
    """Agrège les 4 résultats d'analyse en un dossier d'expertise scellé unique.

    Le statut initial est toujours 'en_attente_validation_humaine' : l'agent n'est
    jamais autorisé à clôturer, valider ou rejeter un sinistre sans décision humaine.
    """
    resolved_case_id = case_id or uuid.uuid4().hex[:12]

    scores_par_couche = {
        "exif": round(float(exif_result.get("score", 0.0)), 3),
        "c2pa": round(float(c2pa_result.get("score", 0.0)), 3),
        "ela": round(float(ela_result.get("score", 0.0)), 3),
        "vision": round(float(vision_result.get("score", 0.0)), 3),
    }

    weighted = sum(scores_par_couche[k] * LAYER_WEIGHTS[k] for k in LAYER_WEIGHTS)

    # Si une couche majeure lève un signal fort, éviter qu'une autre couche neutre ne le dilue excessivement
    max_major = max(scores_par_couche["exif"], scores_par_couche["ela"], scores_par_couche["vision"])
    if max_major >= 0.65:
        weighted = max(weighted, 0.52)

    score_global = round(min(1.0, max(0.0, weighted)), 3)

    preuves: list[dict[str, Any]] = []

    # Preuves EXIF
    if exif_result.get("incoherences"):
        for inc in exif_result["incoherences"]:
            preuves.append(
                {
                    "couche": "exif",
                    "type": inc.get("type", "incoherence_exif"),
                    "severite": inc.get("severite", "moyenne"),
                    "detail": inc.get("detail", ""),
                }
            )
    else:
        preuves.append(
            {
                "couche": "exif",
                "type": "exif_coherent",
                "severite": "faible",
                "detail": (
                    f"Métadonnées EXIF cohérentes (appareil : "
                    f"{exif_result.get('appareil', {}).get('make') or 'N/A'} "
                    f"{exif_result.get('appareil', {}).get('model') or ''}, "
                    f"date : {exif_result.get('date_prise_vue') or 'N/A'})."
                ),
            }
        )

    # Preuve C2PA
    preuves.append(
        {
            "couche": "c2pa",
            "type": "provenance_c2pa",
            "severite": "faible",
            "detail": f"Statut C2PA : {c2pa_result.get('statut', 'aucune provenance vérifiable')}.",
        }
    )

    # Preuves ELA
    zones_suspectes = ela_result.get("zones_suspectes", [])
    if zones_suspectes:
        preuves.append(
            {
                "couche": "ela",
                "type": "retouche_locale_ela",
                "severite": "elevee",
                "detail": (
                    f"{len(zones_suspectes)} zone(s) hétérogène(s) détectée(s) par re-compression ELA (q=90)."
                ),
            }
        )
    else:
        preuves.append(
            {
                "couche": "ela",
                "type": "ela_homogene",
                "severite": "faible",
                "detail": (
                    f"Distribution ELA homogène (erreur moyenne : "
                    f"{ela_result.get('statistiques', {}).get('erreur_moyenne_globale', 'N/A')})."
                ),
            }
        )

    # Preuves Vision
    if vision_result.get("anomalies"):
        for anom in vision_result["anomalies"]:
            preuves.append(
                {
                    "couche": "vision",
                    "type": anom.get("type", "anomalie_visuelle"),
                    "severite": anom.get("severite", "moyenne"),
                    "detail": anom.get("description", ""),
                }
            )
    else:
        preuves.append(
            {
                "couche": "vision",
                "type": "inspection_visuelle_coherente",
                "severite": "faible",
                "detail": vision_result.get("synthese", "Aucune anomalie visuelle majeure détectée."),
            }
        )

    if score_global >= 0.60:
        recommandation = (
            "Alerte fraude élevée — expertise contradictoire et vérification des originaux obligatoires."
        )
    elif score_global >= 0.35:
        recommandation = (
            "Indices modérés — demande de justificatifs complémentaires ou revue par un gestionnaire."
        )
    else:
        recommandation = (
            "Risque faible — éléments techniques cohérents, sous réserve de validation humaine."
        )

    return {
        "case_id": resolved_case_id,
        "score_global": score_global,
        "scores_par_couche": scores_par_couche,
        "preuves": preuves,
        "zones_suspectes": zones_suspectes,
        "recommandation": recommandation,
        "statut": "en_attente_validation_humaine",
    }
