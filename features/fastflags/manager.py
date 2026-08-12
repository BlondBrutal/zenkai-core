"""
Gestion des Fast Flags Roblox : lecture/écriture du vrai fichier
ClientAppSettings.json, presets prédéfinis (Hard/Balanced/Quality), et
presets personnalisés (importés depuis un fichier externe, ou enregistrés
depuis l'éditeur) stockés dans le dossier applicatif (voir
core/paths.py:get_fastflags_presets_dir).

Emplacement du fichier Roblox : %LOCALAPPDATA%\\Roblox\\ClientSettings\\ClientAppSettings.json
— un dossier séparé du dossier d'installation ("Versions"), souvent absent
tant qu'aucun outil de config n'a encore écrit dedans : c'est normal, pas une
erreur d'installation.

Les 3 presets prédéfinis (Hard/Balanced/Quality) sont chargés depuis
assets/fastflags_presets/*.json — des fichiers RÉELS fournis par
l'utilisateur (pas des flags devinés/générés), copiés tels quels dans le
projet. Leur format (un objet JSON plat "NomDuFlag": "valeur en chaîne")
correspond déjà exactement à ce qu'attend ClientAppSettings.json, aucune
adaptation de parsing n'a donc été nécessaire.
"""
import json
import logging
import os
import re

from core.paths import get_fastflags_known_flags_path, get_fastflags_presets_dir

logger = logging.getLogger("zenkaiontop.fastflags")

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BUILTIN_PRESETS_DIR = os.path.join(_PROJECT_ROOT, "assets", "fastflags_presets")
_KNOWN_FLAGS_SEED_PATH = os.path.join(_BUILTIN_PRESETS_DIR, "known_flags.json")

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9 _-]+")


def detect_value_type(value: str) -> str:
    """Devine le type d'affichage d'une valeur de flag (BOOL/INT/STRING) —
    purement indicatif pour l'utilisateur (badge de type, base de flags
    connus) : n'affecte jamais l'écriture réelle, qui reste toujours une
    chaîne (voir docstring du module)."""
    cleaned = value.strip()
    if cleaned.lower() in ("true", "false"):
        return "BOOL"
    try:
        int(cleaned)
        return "INT"
    except ValueError:
        return "STRING"


def _read_json_dict(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("JSON illisible (%s) : %s", path, exc)
        return {}


def _load_builtin_preset(key: str) -> dict[str, str]:
    path = os.path.join(_BUILTIN_PRESETS_DIR, f"{key}.json")
    flags = _read_json_dict(path)
    if not flags:
        # Ne devrait jamais arriver avec une installation normale (les 3
        # fichiers sont livrés avec le projet) : signale une install/build
        # cassée plutôt que d'échouer silencieusement avec un preset vide.
        logger.error("Preset intégré '%s' introuvable ou vide (%s)", key, path)
    return flags


# Chargés une seule fois au démarrage depuis les fichiers réels fournis par
# l'utilisateur (voir docstring du module) — jamais de contenu généré/deviné.
PRESETS: dict[str, dict[str, str]] = {
    key: _load_builtin_preset(key) for key in ("hard", "balanced", "quality")
}


def get_client_app_settings_path() -> str:
    """Retourne le chemin du fichier Fast Flags de Roblox (ne le crée pas :
    seule une écriture réelle crée le dossier si besoin)."""
    base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    return os.path.join(base, "Roblox", "ClientSettings", "ClientAppSettings.json")


def read_current_flags() -> dict:
    """Lit le fichier Roblox actuel. Ne lève jamais d'exception : fichier
    absent ou corrompu = considéré comme vide (réglages par défaut)."""
    return _read_json_dict(get_client_app_settings_path())


def write_flags(flags: dict) -> bool:
    """Écrit `flags` tel quel dans le vrai fichier Roblox (remplace tout le
    contenu précédent). Crée le dossier ClientSettings s'il n'existe pas
    encore. Retourne False sans lever d'exception si l'écriture échoue
    (droits, disque plein, etc.) — l'appelant doit alors afficher une erreur
    plutôt que de supposer que c'est appliqué."""
    return _write_json_dict(get_client_app_settings_path(), flags)


def reset_to_default() -> bool:
    """Vide le fichier Roblox (objet JSON vide = aucun override, comportement
    100% par défaut, sans avoir à désinstaller/réparer quoi que ce soit)."""
    return write_flags({})


def detect_active_preset() -> str | None:
    """Compare le contenu RÉEL du fichier Roblox à chaque preset prédéfini
    connu. Retourne None si aucun ne correspond exactement (fichier absent,
    vide, ou personnalisé) — jamais une valeur en cache."""
    current = read_current_flags()
    for key, flags in PRESETS.items():
        if current == flags:
            return key
    return None


# ------------------------------------------------------------------
# Presets personnalisés (importés ou enregistrés depuis l'éditeur)
# ------------------------------------------------------------------
def list_custom_presets() -> list[tuple[str, str]]:
    """Retourne [(chemin, nom)] pour chaque preset personnalisé, trié par
    nom. Le nom vient du nom de fichier (sans extension)."""
    directory = get_fastflags_presets_dir()
    entries = []
    try:
        for filename in os.listdir(directory):
            if filename.lower().endswith(".json"):
                name = os.path.splitext(filename)[0]
                entries.append((os.path.join(directory, filename), name))
    except OSError as exc:
        logger.warning("Lecture des presets personnalisés impossible (%s)", exc)
    entries.sort(key=lambda entry: entry[1].lower())
    return entries


def load_custom_preset(path: str) -> dict:
    """Lit un preset personnalisé (ou un fichier importé) — jamais
    d'exception : contenu invalide = dict vide."""
    return _read_json_dict(path)


def save_custom_preset(name: str, flags: dict) -> str | None:
    """Sauvegarde `flags` comme nouveau preset réutilisable dans la
    Bibliothèque. Le nom de fichier dérive du nom donné (nettoyé des
    caractères spéciaux) ; un suffixe numérique est ajouté en cas de
    collision plutôt que d'écraser un preset existant du même nom."""
    directory = get_fastflags_presets_dir()
    base = _SAFE_NAME_RE.sub("", name).strip() or "preset"
    candidate = base
    counter = 2
    while os.path.exists(os.path.join(directory, f"{candidate}.json")):
        candidate = f"{base} ({counter})"
        counter += 1
    path = os.path.join(directory, f"{candidate}.json")
    return path if _write_json_dict(path, flags) else None


def import_flags_file(source_path: str) -> str | None:
    """Importe un fichier JSON externe (ClientAppSettings.json existant, ou
    export d'un autre outil) comme nouveau preset de la Bibliothèque. Valide
    que le contenu est bien un objet JSON avant de le copier ; retourne None
    si le fichier est invalide, illisible, ou si l'écriture échoue. Les noms
    de flags rencontrés enrichissent aussi la base de "flags connus" (voir
    _learn_flags_from) — jamais de nom deviné, uniquement des noms vus dans
    un vrai fichier fourni par l'utilisateur."""
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("Fichier à importer invalide (%s) : %s", source_path, exc)
        return None
    if not isinstance(data, dict):
        return None
    name = os.path.splitext(os.path.basename(source_path))[0]
    path = save_custom_preset(name, data)
    if path is not None:
        _learn_flags_from(data)
    return path


def delete_custom_preset(path: str) -> None:
    try:
        os.remove(path)
    except OSError as exc:
        logger.warning("Suppression du preset personnalisé impossible (%s)", exc)


def export_flags_file(flags: dict, dest_path: str) -> bool:
    """Écrit `flags` (preset intégré OU personnalisé, peu importe l'origine)
    dans un fichier JSON choisi par l'utilisateur — export "à plat", sans
    lien avec le système de presets de la Bibliothèque (contrairement à
    save_custom_preset, qui enregistre DANS ce système)."""
    return _write_json_dict(dest_path, flags)


# ------------------------------------------------------------------
# Base de "flags connus" (panneau "Parcourir les flags connus") : une base
# de départ ("seed", assets/fastflags_presets/known_flags.json) extraite des
# 3 presets réels fournis par l'utilisateur, enrichie au fil du temps par les
# imports de l'utilisateur — jamais de nom de flag inventé/deviné.
# ------------------------------------------------------------------
def get_known_flags() -> dict[str, str]:
    """Retourne {nom_du_flag: type détecté}, base intégrée + flags appris."""
    merged = dict(_read_json_dict(_KNOWN_FLAGS_SEED_PATH))
    merged.update(_read_json_dict(get_fastflags_known_flags_path()))
    return merged


def _learn_flags_from(flags: dict) -> None:
    """Ajoute à la base "apprise" les noms de `flags` pas encore connus.
    Appelé uniquement depuis import_flags_file (voir sa docstring) : jamais
    depuis une saisie manuelle dans l'éditeur, pour ne jamais faire entrer un
    nom potentiellement mal orthographié dans la base."""
    seed = _read_json_dict(_KNOWN_FLAGS_SEED_PATH)
    learned_path = get_fastflags_known_flags_path()
    learned = _read_json_dict(learned_path)
    changed = False
    for name, value in flags.items():
        if name not in seed and name not in learned:
            learned[name] = detect_value_type(str(value))
            changed = True
    if changed:
        _write_json_dict(learned_path, learned)


# ------------------------------------------------------------------
# Helper JSON d'écriture (la lecture, _read_json_dict, est définie plus haut
# — utilisée dès le chargement des presets intégrés au niveau module)
# ------------------------------------------------------------------
def _write_json_dict(path: str, data: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as exc:
        logger.error("Impossible d'écrire %s (%s)", path, exc)
        return False
