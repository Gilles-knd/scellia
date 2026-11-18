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

# Traduction des signaux techniques en langage de gestionnaire de sinistres.
_HUMAN_PHRASES = {
    "date_prise_anterieure_au_sinistre": "La photo a été prise avant la date de l'accident déclaré : le dommage montré existait donc déjà. C'est l'indicateur le plus fort d'un dossier frauduleux.",
    "logiciel_edition_detecte": "Le fichier porte la trace d'un logiciel de retouche : l'image n'est pas une photo directe du véhicule, elle a été modifiée après prise de vue.",
    "exif_absent": "Le fichier ne contient aucune information d'origine — ni date, ni appareil photo. Une photo prise par un téléphone envoie presque toujours ces informations ; leur absence est typique d'une image fabriquée par une intelligence artificielle ou nettoyée avant l'envoi.",
    "exif_coherent": "Les informations d'origine sont présentes et crédibles : l'appareil qui a pris la photo et la date de prise de vue sont compatibles avec le sinistre déclaré.",
    "retouche_locale_ela": "Des zones précises de l'image se comportent différemment du reste quand on les récompresse : c'est la signature d'un élément ajouté ou retouché localement (rayure ou déformation collée sur une photo sinon honnête).",
    "ela_homogene": "L'analyse de compression de l'image ne révèle aucune zone retouchée : l'ensemble paraît homogène.",
    "provenance_c2pa": "Le fichier ne porte pas d'étiquette numérique de provenance (le standard international qui certifie qu'une photo sort bien d'un appareil et n'a pas été modifiée). Son origine ne peut donc pas être certifiée — mais rien ne prouve non plus qu'elle a été fabriquée.",
    "generation_ia": "L'aspect général de l'image ne se comporte pas comme une vraie photo : textures anormalement lisses, contours trop propres. C'est le rendu typique d'une image produite par une intelligence artificielle.",
    "uniformite_anormale": "L'image présente une uniformité inhabituelle pour une prise de vue réelle.",
    "inspection_visuelle_coherente": "L'inspection visuelle ne relève rien d'anormal : dégâts, reflets et perspectives paraissent physiquement cohérents.",
}


def build_rapport_lisible(
    score_global: float,
    preuves: list[dict[str, Any]],
    recommandation: str,
    exif_result: dict[str, Any],
    ela_result: dict[str, Any],
) -> str:
    """Rédige la synthèse du dossier dans le langage d'un gestionnaire de sinistres."""
    niveau = "élevé" if score_global >= 0.60 else ("modéré" if score_global >= 0.35 else "faible")
    lignes: list[str] = [
        f"Niveau de risque estimé : {niveau} ({round(score_global * 100)} %).",
        "",
        "Ce que nous voyons :",
    ]
    signaux = [p for p in preuves if p["severite"] in ("elevee", "moyenne")]
    elements_ok = [p for p in preuves if p["severite"] == "faible"]
    if signaux:
        for p in signaux:
            phrase = _HUMAN_PHRASES.get(p["type"])
            lignes.append(f"- {phrase if phrase else p['detail']}")
    else:
        lignes.append("- Aucun signal de fraude détecté sur les quatre vérifications.")
    if elements_ok and signaux:
        lignes.append("Points rassurants :")
        for p in elements_ok:
            phrase = _HUMAN_PHRASES.get(p["type"])
            lignes.append(f"- {phrase if phrase else p['detail']}")
    lignes += [
        "",
        f"Recommandation : {recommandation}",
        "Rappel de la règle : cette synthèse est une aide à la décision. Aucun dossier n'est validé ni rejeté sans la décision d'un gestionnaire humain identifié, enregistrée dans le journal.",
    ]
    return "\n".join(lignes)



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

    # Signal composé fort : aucune origine vérifiable (EXIF absent, score exif déjà relevé par exif.py)
    # + texture typique de l'IA détectée par la vision -> on ne dilue pas, on alerte.
    traces_ia = bool(vision_result.get("traces_ia_detectees"))
    if traces_ia and (exif_result.get("score", 0) >= 0.40):
        weighted = max(weighted, 0.62)

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

    rapport = build_rapport_lisible(
        score_global=score_global,
        preuves=preuves,
        recommandation=recommandation,
        exif_result=exif_result,
        ela_result=ela_result,
    )

    return {
        "case_id": resolved_case_id,
        "score_global": score_global,
        "scores_par_couche": scores_par_couche,
        "preuves": preuves,
        "zones_suspectes": zones_suspectes,
        "recommandation": recommandation,
        "rapport_lisible": rapport,
        "statut": "en_attente_validation_humaine",
    }
