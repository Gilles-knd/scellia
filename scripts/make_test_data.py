"""Génère les 3 images de test locales (vraie, retouchée, générée) et samples/manifest.json."""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw

ROOT_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT_DIR / "samples"


def _draw_car_scene(seed: int = 42, add_sensor_noise: bool = True) -> Image.Image:
    """Dessine une scène automobile synthétique réaliste (carrosserie, pare-brise, plaque, route)."""
    rng = random.Random(seed)
    w, h = 800, 520
    img = Image.new("RGB", (w, h), (205, 218, 232))
    draw = ImageDraw.Draw(img)

    # Route et arrière-plan
    draw.rectangle([0, 310, w, h], fill=(68, 72, 80))
    draw.rectangle([0, 305, w, 312], fill=(180, 180, 175))

    # Carrosserie véhicule
    draw.rounded_rectangle([140, 170, 660, 370], radius=28, fill=(45, 78, 120), outline=(25, 45, 75), width=3)
    # Pare-brise
    draw.polygon([(210, 175), (275, 110), (525, 110), (590, 175)], fill=(140, 175, 205), outline=(30, 40, 55))
    # Phares
    draw.rounded_rectangle([165, 245, 235, 285], radius=8, fill=(245, 240, 210), outline=(90, 90, 90))
    draw.rounded_rectangle([565, 245, 635, 285], radius=8, fill=(245, 240, 210), outline=(90, 90, 90))
    # Plaque d'immatriculation
    draw.rectangle([320, 290, 480, 326], fill=(245, 245, 245), outline=(40, 40, 40), width=2)
    draw.rectangle([320, 290, 342, 326], fill=(28, 78, 165))
    # Roues
    draw.ellipse([170, 330, 270, 420], fill=(28, 28, 30))
    draw.ellipse([530, 330, 630, 420], fill=(28, 28, 30))

    if add_sensor_noise:
        pixels = img.load()
        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y]
                n = rng.randint(-14, 14)
                pixels[x, y] = (
                    max(0, min(255, r + n)),
                    max(0, min(255, g + n)),
                    max(0, min(255, b + n)),
                )
    return img


def _build_full_exif(date_str: str, software: str = "17.4.1") -> bytes:
    """Construit un bloc EXIF complet via Pillow (Make, Model, Software, DateTimeOriginal, GPS)."""
    exif = Image.Exif()
    exif[271] = "Apple"  # Make
    exif[272] = "iPhone 15 Pro"  # Model
    exif[305] = software  # Software
    exif[306] = date_str  # DateTime

    # ExifIFD (0x8769) -> DateTimeOriginal (36867), DateTimeDigitized (36868)
    exif_ifd = exif.get_ifd(0x8769)
    exif_ifd[36867] = date_str
    exif_ifd[36868] = date_str

    # GPSInfo (0x8825) -> Paris (48.8566 N, 2.3522 E)
    gps_ifd = exif.get_ifd(0x8825)
    gps_ifd[1] = "N"
    gps_ifd[2] = (48.0, 51.0, 23.8)
    gps_ifd[3] = "E"
    gps_ifd[4] = (2.0, 21.0, 7.9)

    return exif.tobytes()


def main() -> None:
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    declared_date = "2026-11-18"

    # (a) Photo vraie : EXIF complet cohérent avec la date déclarée, bruit capteur homogène
    real_img = _draw_car_scene(seed=101, add_sensor_noise=True)
    real_path = SAMPLES_DIR / "photo_vraie.jpg"
    real_img.save(
        real_path,
        format="JPEG",
        quality=85,
        exif=_build_full_exif("2026:11:18 09:15:00", software="17.4.1"),
    )

    # (b) Photo retouchée : recadrage + ré-enregistrement partiel (zone hétérogène ELA) + date EXIF antérieure
    base_for_edit = _draw_car_scene(seed=202, add_sensor_noise=True)
    tmp_edit = SAMPLES_DIR / "_tmp_base.jpg"
    base_for_edit.save(tmp_edit, format="JPEG", quality=62)
    with Image.open(tmp_edit) as reloaded:
        # Recadrage léger
        cropped = reloaded.crop((20, 15, 780, 505)).copy()
    tmp_edit.unlink(missing_ok=True)

    # Insertion d'une zone retouchée très nette / contrastée (impact ajouté artificiellement)
    patch_draw = ImageDraw.Draw(cropped)
    for idx in range(0, 140, 8):
        color = (240, 40, 40) if (idx // 8) % 2 == 0 else (20, 20, 20)
        patch_draw.rectangle([230 + idx, 185, 238 + idx, 295], fill=color)
    patch_draw.line([(230, 185), (370, 295)], fill=(255, 255, 255), width=4)
    patch_draw.line([(370, 185), (230, 295)], fill=(255, 255, 255), width=4)

    retouched_path = SAMPLES_DIR / "photo_retouchee.jpg"
    cropped.save(
        retouched_path,
        format="JPEG",
        quality=98,
        exif=_build_full_exif("2025:06:10 14:22:00", software="Adobe Photoshop 25.0"),
    )

    # (c) Image générée : sans EXIF, texture trop lisse, double compression JPEG
    gen_img = _draw_car_scene(seed=303, add_sensor_noise=False)
    tmp_gen = SAMPLES_DIR / "_tmp_gen.jpg"
    gen_img.save(tmp_gen, format="JPEG", quality=96)
    gen_path = SAMPLES_DIR / "image_generee.jpg"
    with Image.open(tmp_gen) as re_gen:
        re_gen.save(gen_path, format="JPEG", quality=82)
    tmp_gen.unlink(missing_ok=True)

    manifest = {
        "declared_date": declared_date,
        "claim_type": "Collision / Choc avant",
        "samples": [
            {
                "id": "photo_vraie",
                "file": "samples/photo_vraie.jpg",
                "verite_terrain": "authentique",
                "description": "Photo prise le jour du sinistre avec EXIF complet (Apple iPhone 15 Pro, GPS) et bruit homogène.",
                "expected_risk": "faible",
            },
            {
                "id": "photo_retouchee",
                "file": "samples/photo_retouchee.jpg",
                "verite_terrain": "retouchee",
                "description": "Recadrage + zone d'impact ajoutée (ELA hétérogène) + date EXIF antérieure au sinistre (2025-06-10).",
                "expected_risk": "eleve",
            },
            {
                "id": "image_generee",
                "file": "samples/image_generee.jpg",
                "verite_terrain": "generee_ia",
                "description": "Absence totale d'EXIF, texture synthétique lisse, double compression JPEG.",
                "expected_risk": "modere_a_eleve",
            },
        ],
    }
    manifest_path = SAMPLES_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Jeu de test généré dans {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
