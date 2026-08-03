"""
Config d'une macro Pixel (Partie 1.4 du brief) : un pixel surveillé, une
couleur cible (correspondance exacte), une touche de réaction. Le
déclenchement reprend le comportement de PixelWatchLoop dans
"Global Macro v2.ahk" (page TP) — front montant de correspondance de
couleur, plus un "temps de recharge" (cooldown_seconds, toujours actif,
0 = pas de délai) qui reprend TP_COOLDOWN_MS du même fichier : un
déclenchement bloqué par le cooldown reste retenté à chaque itération tant
que la couleur continue de correspondre, sans exiger un nouveau front montant
(voir features/macro_pixel/pixel_watcher.py). Le "changement rapide de
touche" (swap_*, toujours actif dès qu'une touche swap est définie) reprend
ChangementToucheHandler du même fichier : une touche dédiée échange à la
volée la touche de réaction avec une seconde touche de réaction (voir
features/macro_pixel/key_swap_listener.py). Sauvegardée en `.zkmacro` (JSON)
dans le dossier macros de l'app (core/paths.get_macros_dir), pour que la
Bibliothèque (page_macro.py) puisse lister/importer/exporter across tous les
types de macro de façon uniforme.
"""
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass

from core.paths import get_macros_dir

logger = logging.getLogger("zenkaiontop.macro_pixel")

MACRO_TYPE = "pixel"


@dataclass
class PixelMacroConfig:
    name: str
    x: int
    y: int
    target_color: tuple[int, int, int]
    key: str = ""
    swap_key: str = ""
    swap_target_key: str = ""
    cooldown_seconds: float = 0.0
    type: str = MACRO_TYPE

    def to_dict(self) -> dict:
        data = asdict(self)
        data["target_color"] = list(self.target_color)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PixelMacroConfig":
        return cls(
            name=str(data.get("name", "")),
            x=int(data["x"]),
            y=int(data["y"]),
            target_color=tuple(data.get("target_color", (0, 0, 0)))[:3],
            key=str(data.get("key", "")),
            swap_key=str(data.get("swap_key", "")),
            swap_target_key=str(data.get("swap_target_key", "")),
            cooldown_seconds=float(data.get("cooldown_seconds", 0.0)),
            type=MACRO_TYPE,
        )


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "macro"


def save_pixel_macro(macro: PixelMacroConfig, existing_path: str | None = None) -> str:
    """Sauvegarde la macro et retourne le chemin du fichier .zkmacro utilisé
    (celui donné, ou un nouveau nommé d'après la macro)."""
    if existing_path:
        path = existing_path
    else:
        filename = f"{_slugify(macro.name)}-{uuid.uuid4().hex[:8]}.zkmacro"
        path = os.path.join(get_macros_dir(), filename)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(macro.to_dict(), f, indent=2, ensure_ascii=False)
    return path


def list_pixel_macros() -> list[tuple[str, PixelMacroConfig]]:
    """Liste (chemin, config) de toutes les macros Pixel valides trouvées
    dans le dossier macros. Ignore silencieusement les fichiers illisibles
    ou d'un autre type — jamais de crash pour un fichier externe corrompu."""
    results = []
    macros_dir = get_macros_dir()
    for filename in sorted(os.listdir(macros_dir)):
        if not filename.endswith(".zkmacro"):
            continue
        path = os.path.join(macros_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("type") != MACRO_TYPE:
                continue
            results.append((path, PixelMacroConfig.from_dict(data)))
        except Exception as exc:
            logger.warning("Macro illisible ignorée (%s) : %s", path, exc)
    return results


def delete_macro(path: str) -> None:
    try:
        os.remove(path)
    except OSError as exc:
        logger.error("Impossible de supprimer la macro %s : %s", path, exc)


def import_macro(source_path: str) -> tuple[str, PixelMacroConfig]:
    """Copie un fichier .zkmacro externe dans le dossier macros de l'app."""
    with open(source_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("type") != MACRO_TYPE:
        raise ValueError(f"Ce fichier n'est pas une macro Pixel (type={data.get('type')!r}).")
    macro = PixelMacroConfig.from_dict(data)
    dest = save_pixel_macro(macro)
    return dest, macro


def export_macro(macro_path: str, dest_path: str) -> None:
    with open(macro_path, "r", encoding="utf-8") as f:
        data = f.read()
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(data)
