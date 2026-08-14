"""
Bibliothèque des scripts personnalisés (page Custom Script) : un fichier
.zkscript (JSON) par script sous core.paths.get_custom_scripts_dir(), même
principe que features/macro_simple/macro_simple.py (.zkmacro) — jamais de
clé dans core/config.py settings.json pour ces données par item (ce fichier
ne sert qu'à de petits interrupteurs globaux, voir
custom_scripts_globally_enabled).

Le verdict d'analyse (heuristique + Defender) est stocké À CÔTÉ du texte du
script et d'un hash SHA-256 de ce texte : toute modification du script
invalide silencieusement l'ancien verdict (voir is_analysis_current) sans
jamais le faire disparaître du disque (utile pour l'audit / journal de
sécurité) — simplement il n'est plus considéré fiable par l'UI tant qu'une
nouvelle analyse (déclenchée par "Enregistrer"/"Réanalyser") n'a pas été
faite.
"""
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

from core.paths import get_custom_scripts_dir

logger = logging.getLogger("zenkaiontop.custom_script")

SEVERITY_NONE = "none"
SEVERITY_MODERATE = "moderate"
SEVERITY_SEVERE = "severe"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class ScriptAnalysis:
    heuristic_severity: str = SEVERITY_NONE
    heuristic_categories: list = field(default_factory=list)  # ex. ["files", "network"]
    heuristic_finding_keys: list = field(default_factory=list)  # clés i18n, jamais de texte brut
    defender_available: bool = False  # False = MpCmdRun.exe introuvable, aucun scan réel effectué
    defender_clean: bool | None = None  # None = pas encore scanné / scan inconclusif ; jamais interprété comme "sûr"
    defender_exit_code: int | None = None
    analyzed_hash: str = ""  # sha256 du script_text au moment de CETTE analyse
    analyzed_at: str = ""  # ISO 8601
    unlocked: bool = False  # True seulement si l'utilisateur a validé show_high_risk_confirm pour CE hash précis

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScriptAnalysis":
        return cls(
            heuristic_severity=str(data.get("heuristic_severity", SEVERITY_NONE)),
            heuristic_categories=list(data.get("heuristic_categories", [])),
            heuristic_finding_keys=list(data.get("heuristic_finding_keys", [])),
            defender_available=bool(data.get("defender_available", False)),
            defender_clean=data.get("defender_clean"),
            defender_exit_code=data.get("defender_exit_code"),
            analyzed_hash=str(data.get("analyzed_hash", "")),
            analyzed_at=str(data.get("analyzed_at", "")),
            unlocked=bool(data.get("unlocked", False)),
        )


@dataclass
class CustomScriptEntry:
    id: str
    name: str
    script_text: str
    created_at: str
    updated_at: str
    analysis: ScriptAnalysis | None = None

    def content_hash(self) -> str:
        return hashlib.sha256(self.script_text.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "script_text": self.script_text,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "analysis": self.analysis.to_dict() if self.analysis else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CustomScriptEntry":
        analysis = data.get("analysis")
        return cls(
            id=str(data.get("id", uuid.uuid4().hex)),
            name=str(data.get("name", "")),
            script_text=str(data.get("script_text", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            analysis=ScriptAnalysis.from_dict(analysis) if analysis else None,
        )


def is_analysis_current(entry: CustomScriptEntry) -> bool:
    """True seulement si un verdict existe ET a été calculé sur le texte
    ACTUEL du script (invalidation par hash à chaque modification)."""
    return entry.analysis is not None and entry.analysis.analyzed_hash == entry.content_hash()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "script"


def ahk_companion_path(zkscript_path: str) -> str:
    """Chemin du .ahk généré juste avant chaque lancement/scan, à côté du
    .zkscript — jamais la source de vérité (le champ script_text du
    .zkscript l'est), uniquement un artefact régénéré à chaque fois."""
    return os.path.splitext(zkscript_path)[0] + ".ahk"


def save_script(entry: CustomScriptEntry, existing_path: str | None = None) -> str:
    """Sauvegarde entry.to_dict() en JSON et renvoie le chemin utilisé (le
    même que existing_path, ou un nouveau nommé d'après entry.name)."""
    if existing_path:
        path = existing_path
    else:
        path = os.path.join(get_custom_scripts_dir(), f"{_slugify(entry.name)}-{entry.id[:8]}.zkscript")
    entry.updated_at = _now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry.to_dict(), f, indent=2, ensure_ascii=False)
    return path


def list_scripts() -> list[tuple[str, CustomScriptEntry]]:
    """(chemin, entry) pour chaque .zkscript valide. Fichier illisible/
    corrompu ignoré silencieusement (jamais de crash), même principe que
    list_macro_simple_macros()."""
    results = []
    scripts_dir = get_custom_scripts_dir()
    for filename in sorted(os.listdir(scripts_dir)):
        if not filename.endswith(".zkscript"):
            continue
        path = os.path.join(scripts_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            results.append((path, CustomScriptEntry.from_dict(data)))
        except Exception as exc:
            logger.warning("Script personnalisé illisible ignoré (%s) : %s", path, exc)
    return results


def export_script(source_path: str, dest_path: str) -> None:
    """Copie brute du .zkscript vers dest_path — même principe que
    features/macro_pixel/pixel_macro.py::export_macro (le fichier lui-même
    EST déjà le format d'échange, pas besoin de le retraiter)."""
    with open(source_path, "r", encoding="utf-8") as f:
        data = f.read()
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(data)


def delete_script(path: str) -> None:
    """Supprime le .zkscript ET son .ahk compagnon s'il existe — jamais
    d'exception si l'un des deux est déjà absent."""
    for candidate in (path, ahk_companion_path(path)):
        try:
            if os.path.isfile(candidate):
                os.remove(candidate)
        except OSError as exc:
            logger.warning("Suppression impossible (%s) : %s", candidate, exc)
