"""
Bibliothèque des presets Fleasion (page Fleasion) : un fichier .zkfleasion
(JSON) par preset sous core.paths.get_fleasion_presets_dir(), plus un
sous-dossier <id>/assets/ par preset pour les fichiers "Local" (texture/
son/mesh) qu'il référence — même principe que
features/custom_script/script_store.py (.zkscript), avec en plus ce
dossier d'assets puisqu'un preset Fleasion combine intrinsèquement des
règles ET des fichiers locaux (un script AHK, lui, est un simple texte
autonome, jamais accompagné d'un fichier séparé).

Le dossier d'assets est nommé d'après entry.id (jamais le nom slugifié du
preset, contrairement au nom de fichier .zkfleasion lui-même) : un
renommage du preset ne doit jamais faire "perdre" les fichiers déjà
importés en cassant le chemin vers leur dossier.
"""
import json
import logging
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime

from core.paths import get_fleasion_presets_dir

logger = logging.getLogger("zenkaiontop.fleasion")

MODE_ID = "id"
MODE_URL = "url"
MODE_LOCAL = "local"
MODE_REMOVE = "remove"
ALL_MODES = (MODE_ID, MODE_URL, MODE_LOCAL, MODE_REMOVE)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class FleasionRule:
    asset_ids: str = ""  # un ou plusieurs Asset ID Roblox (virgule/espace/point-virgule)
    mode: str = MODE_ID  # une des constantes MODE_* ci-dessus
    target: str = ""  # ID / URL / chemin relatif "/nom_fichier.ext" (local) / vide (remove)
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FleasionRule":
        mode = str(data.get("mode", MODE_ID))
        if mode not in ALL_MODES:
            mode = MODE_ID
        return cls(
            asset_ids=str(data.get("asset_ids", "")),
            mode=mode,
            target=str(data.get("target", "")),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass
class FleasionPresetEntry:
    id: str
    name: str
    rules: list = field(default_factory=list)  # list[FleasionRule]
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "rules": [rule.to_dict() for rule in self.rules],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FleasionPresetEntry":
        return cls(
            id=str(data.get("id", uuid.uuid4().hex)),
            name=str(data.get("name", "")),
            rules=[FleasionRule.from_dict(r) for r in data.get("rules", [])],
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "preset"


def preset_json_path(entry: FleasionPresetEntry) -> str:
    return os.path.join(get_fleasion_presets_dir(), f"{_slugify(entry.name)}-{entry.id[:8]}.zkfleasion")


def preset_assets_dir(entry: FleasionPresetEntry) -> str:
    """Dossier des fichiers "Local" importés pour ce preset — jamais
    référencés depuis leur emplacement d'origine, toujours copiés ici
    d'abord (voir ui/pages/page_fleasion.py::_on_browse_target_clicked).
    Nommé d'après entry.id (stable), pas le nom du preset (voir docstring
    du module)."""
    assets_dir = os.path.join(get_fleasion_presets_dir(), entry.id, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    return assets_dir


def save_preset(entry: FleasionPresetEntry, existing_path: str | None = None) -> str:
    """Sauvegarde entry.to_dict() en JSON et renvoie le chemin utilisé (le
    même que existing_path, ou un nouveau nommé d'après entry.name)."""
    path = existing_path or preset_json_path(entry)
    entry.updated_at = _now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry.to_dict(), f, indent=2, ensure_ascii=False)
    return path


def list_presets() -> list[tuple[str, FleasionPresetEntry]]:
    """(chemin, entry) pour chaque .zkfleasion valide. Fichier illisible/
    corrompu ignoré silencieusement (jamais de crash), même principe que
    features/custom_script/script_store.py::list_scripts."""
    results = []
    presets_dir = get_fleasion_presets_dir()
    for filename in sorted(os.listdir(presets_dir)):
        if not filename.endswith(".zkfleasion"):
            continue
        path = os.path.join(presets_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append((path, FleasionPresetEntry.from_dict(data)))
        except Exception as exc:
            logger.warning("Preset Fleasion illisible ignoré (%s) : %s", path, exc)
    return results


def delete_preset(path: str, entry: FleasionPresetEntry) -> None:
    """Supprime le .zkfleasion ET son dossier d'assets associé s'il existe
    — jamais d'exception si l'un des deux est déjà absent."""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError as exc:
        logger.warning("Suppression impossible (%s) : %s", path, exc)
    assets_parent = os.path.join(get_fleasion_presets_dir(), entry.id)
    if os.path.isdir(assets_parent):
        shutil.rmtree(assets_parent, ignore_errors=True)


def export_preset(entry: FleasionPresetEntry, dest_zip_path: str) -> None:
    """ZIP contenant le preset (JSON) + son dossier assets/ (s'il existe) —
    un JSON seul, contrairement au .zkscript d'AutoHotkey (texte autonome),
    perdrait toute référence "Local" (fichier introuvable une fois
    réimporté ailleurs) : le ZIP est le vrai format d'échange ici."""
    with zipfile.ZipFile(dest_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("preset.json", json.dumps(entry.to_dict(), indent=2, ensure_ascii=False))
        assets_dir = os.path.join(get_fleasion_presets_dir(), entry.id, "assets")
        if os.path.isdir(assets_dir):
            for filename in sorted(os.listdir(assets_dir)):
                file_path = os.path.join(assets_dir, filename)
                if os.path.isfile(file_path):
                    zf.write(file_path, arcname=f"assets/{filename}")


def import_preset(zip_path: str) -> FleasionPresetEntry:
    """Importe un ZIP produit par export_preset : toujours un NOUVEAU
    preset (id régénéré, jamais d'écrasement silencieux d'un preset
    existant), fichiers "Local" recopiés dans le dossier d'assets du
    nouveau preset."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open("preset.json") as f:
            data = json.load(f)
        entry = FleasionPresetEntry.from_dict(data)
        entry.id = uuid.uuid4().hex
        assets_dir = preset_assets_dir(entry)
        for name in zf.namelist():
            if name.startswith("assets/") and not name.endswith("/"):
                filename = name[len("assets/"):]
                with zf.open(name) as src, open(os.path.join(assets_dir, filename), "wb") as dst:
                    shutil.copyfileobj(src, dst)
    save_preset(entry)
    return entry
