"""
Traduction d'un preset Zenkai Core (features/fleasion/preset_store.py) vers
le(s) fichier(s) de config que Fleasion lit lui-même dans
%LocalAppData%\\FleasionNT\\configs\\ — voir CLAUDE.md, section
"Architecture : Fleasion" pour le contexte complet.

CAVEAT IMPORTANT : le schéma JSON exact ci-dessous (noms de champs) est
construit À VUE de la documentation publique de Fleasion (Asset ID(s)/
Replace With/Status/Name/Mode, décrits en langage naturel sur fleasion.com
et dans le README GitHub, jamais vus dans un vrai fichier JSON exporté) —
PAS vérifié contre une vraie installation. Toute la traduction est isolée
dans `_to_fleasion_json()` ci-dessous : si les vrais noms de champs
diffèrent une fois testés avec une installation réelle, c'est la SEULE
fonction à corriger.

Toujours déployé dans un sous-dossier DÉDIÉ (ZenkaiCore\\) du dossier
configs\\ de Fleasion, jamais à sa racine : ne touche donc jamais aux
profils que l'utilisateur aurait créés lui-même via le Dashboard Fleasion.
"""
import json
import logging
import os
import shutil
import sys

from features.fleasion.preset_store import MODE_LOCAL, FleasionPresetEntry, preset_assets_dir

logger = logging.getLogger("zenkaiontop.fleasion")

_ZENKAI_SUBFOLDER = "ZenkaiCore"


def get_fleasion_deploy_dir() -> str:
    """%LocalAppData%\\FleasionNT\\configs\\ZenkaiCore\\ — créé si besoin.
    En dehors de Windows (tests/dev), retombe sur un dossier local
    équivalent, même principe que core/paths.py::get_app_data_dir."""
    if sys.platform == "win32":
        base = os.path.join(os.environ.get("LocalAppData", os.path.expanduser("~")), "FleasionNT")
    else:
        base = os.path.join(os.path.expanduser("~"), ".fleasionnt_appdata")
    deploy_dir = os.path.join(base, "configs", _ZENKAI_SUBFOLDER)
    os.makedirs(deploy_dir, exist_ok=True)
    return deploy_dir


def _deployed_config_path(entry: FleasionPresetEntry) -> str:
    return os.path.join(get_fleasion_deploy_dir(), f"{entry.id}.json")


def _deployed_assets_dir(entry: FleasionPresetEntry) -> str:
    return os.path.join(get_fleasion_deploy_dir(), f"{entry.id}_assets")


def _to_fleasion_json(entry: FleasionPresetEntry, active: bool) -> list[dict]:
    """Une liste de règles — le Dashboard Fleasion décrit chaque profil
    comme Asset ID(s)/Replace With/Status/Name/Mode (voir docstring du
    module) ; faute d'exemple réel, ce fichier est une LISTE d'objets au
    format le plus proche possible de cette description. `active` gouverne
    le Statut de TOUTES les règles à la fois (utilisé par undeploy_preset
    pour tout repasser Off sans supprimer le fichier)."""
    rules = []
    for rule in entry.rules:
        target = rule.target
        if rule.mode == MODE_LOCAL and target:
            # Convention documentée : un chemin "/nom_fichier.ext" résout
            # relativement au dossier associé à ce fichier de config.
            target = f"/{os.path.basename(target)}"
        rules.append({
            "name": entry.name,
            "assetIds": rule.asset_ids,
            "mode": rule.mode,
            "replaceWith": target,
            "status": bool(active and rule.enabled),
        })
    return rules


def deploy_preset(entry: FleasionPresetEntry, active: bool = True) -> str:
    """Régénère TOUJOURS le fichier de config déployé + recopie les
    fichiers "Local" depuis le dossier d'assets du preset — jamais réutilisé
    d'un déploiement précédent, même principe que
    features/custom_script/process_manager.py::write_companion_ahk_file.
    Renvoie le chemin déployé."""
    deployed_path = _deployed_config_path(entry)
    with open(deployed_path, "w", encoding="utf-8") as f:
        json.dump(_to_fleasion_json(entry, active=active), f, indent=2, ensure_ascii=False)

    deployed_assets = _deployed_assets_dir(entry)
    if os.path.isdir(deployed_assets):
        shutil.rmtree(deployed_assets, ignore_errors=True)
    source_assets = preset_assets_dir(entry)
    local_rules = [rule for rule in entry.rules if rule.mode == MODE_LOCAL and rule.target]
    if local_rules:
        os.makedirs(deployed_assets, exist_ok=True)
        for rule in local_rules:
            filename = os.path.basename(rule.target)
            source_file = os.path.join(source_assets, filename)
            if os.path.isfile(source_file):
                shutil.copyfile(source_file, os.path.join(deployed_assets, filename))
    return deployed_path


def undeploy_preset(entry: FleasionPresetEntry) -> None:
    """Repasse Statut=Off sur toutes les règles de ce preset (ne supprime
    PAS le fichier ni les assets copiés) — utilisé par le toggle "Actif" par
    preset en position OFF, et par le coupe-circuit global (voir
    ui/pages/page_fleasion.py). Ne fait rien si ce preset n'a jamais été
    déployé (fichier absent)."""
    deployed_path = _deployed_config_path(entry)
    if not os.path.isfile(deployed_path):
        return
    with open(deployed_path, "w", encoding="utf-8") as f:
        json.dump(_to_fleasion_json(entry, active=False), f, indent=2, ensure_ascii=False)


def remove_deployed_preset(entry: FleasionPresetEntry) -> None:
    """Supprime complètement le fichier + les assets déployés pour ce
    preset (utilisé quand le preset lui-même est supprimé de la
    Bibliothèque, pas seulement désactivé)."""
    deployed_path = _deployed_config_path(entry)
    try:
        if os.path.isfile(deployed_path):
            os.remove(deployed_path)
    except OSError as exc:
        logger.warning("Suppression du déploiement Fleasion impossible (%s) : %s", deployed_path, exc)
    deployed_assets = _deployed_assets_dir(entry)
    if os.path.isdir(deployed_assets):
        shutil.rmtree(deployed_assets, ignore_errors=True)
