"""
Détection de l'exécutable Fleasion (https://github.com/fleasion/Fleasion,
GPL-3.0 — substitution locale d'assets Roblox) utilisé par la page Fleasion.
Même priorité que features/custom_script/ahk_detect.py : copie PORTABLE
embarquée dans le dépôt en priorité (assets/runtime/fleasion/Fleasion*.exe),
repli sur une installation système en dernier recours.

Différences avec AutoHotkey (voir CLAUDE.md, section "Architecture :
Fleasion") :
- Nom de fichier VERSIONNÉ (ex. "Fleasion-v2.3.0.exe"), pas un nom fixe —
  glob.glob() plutôt qu'un nom en dur.
- Fleasion n'a PAS d'installeur/registre documenté (contrairement à
  AutoHotkey, qui écrit InstallDir dans HKLM/HKCU) : le repli système
  ci-dessous est BEST-EFFORT (chemins usuels non officiellement confirmés,
  jamais vérifiés contre un vrai installeur Fleasion) — à ajuster si
  l'installeur officiel utilise un autre emplacement.
"""
import glob
import logging
import os
import shutil

logger = logging.getLogger("zenkaiontop.fleasion")

# features/fleasion/fleasion_detect.py -> features/fleasion -> features ->
# racine du dépôt (même convention locale que _REPO_ROOT dans
# features/custom_script/ahk_detect.py).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_EMBEDDED_FLEASION_DIR = os.path.join(_REPO_ROOT, "assets", "runtime", "fleasion")


def find_embedded_fleasion_interpreter() -> str | None:
    candidates = sorted(glob.glob(os.path.join(_EMBEDDED_FLEASION_DIR, "Fleasion*.exe")))
    return candidates[0] if candidates else None


def _fallback_dirs() -> list[str]:
    local_appdata = os.environ.get("LocalAppData", os.path.expanduser("~"))
    return [
        os.path.join(local_appdata, "Programs", "Fleasion"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Fleasion"),
    ]


def find_system_fleasion_interpreter() -> str | None:
    for base in _fallback_dirs():
        candidate = os.path.join(base, "Fleasion.exe")
        if os.path.isfile(candidate):
            return candidate
        for match in sorted(glob.glob(os.path.join(base, "Fleasion*.exe"))):
            return match
    return shutil.which("Fleasion")


def find_fleasion_interpreter() -> str | None:
    embedded = find_embedded_fleasion_interpreter()
    if embedded is not None:
        return embedded
    logger.warning(
        "Exécutable Fleasion embarqué introuvable (%s) : repli sur une installation système.",
        _EMBEDDED_FLEASION_DIR,
    )
    return find_system_fleasion_interpreter()


def health_check() -> str:
    """"ok" | "missing" — même convention que
    features/custom_script/ahk_detect.py::health_check()."""
    return "ok" if find_fleasion_interpreter() else "missing"
