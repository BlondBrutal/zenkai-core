"""
Analyse heuristique statique d'un script AutoHotkey v2 (texte brut, jamais
exécuté). Purement regex/mots-clés, aucune I/O — instantané, appelé de façon
SYNCHRONE au clic sur "Enregistrer"/"Réanalyser" (contrairement au scan
Defender, qui lui est asynchrone, voir defender_scan.py).

La plupart des motifs ciblent des noms de commandes/fonctions inchangés
entre v1.1 et v2 (FileDelete, RegWrite, RegDelete, Run, RunWait, RunAs —
seule la syntaxe d'appel change, pas le nom). Catégorie "network" : détecte
`Download(` (fonction v2) EN PLUS de `UrlDownloadToFile` (toujours utile si
un script v1.1 est quand même collé/importé tel quel).

Renvoie des CLÉS i18n, jamais de texte brut (même convention que
features/risk/risk_score.py::RiskEstimate) : la traduction se fait à
l'affichage (voir ui/pages/page_custom_script.py), jamais ici.

Ceci reste une heuristique : elle réduit le risque mais ne garantit jamais
qu'un script est sûr (voir le microcopy permanent affiché à côté de tout
badge, page_custom_script.py) — un attaquant motivé peut toujours obfusquer
au-delà de ce que ces règles simples détectent.
"""
import re
from dataclasses import dataclass, field

SEVERITY_NONE = "none"
SEVERITY_MODERATE = "moderate"
SEVERITY_SEVERE = "severe"

# Poids par catégorie détectée (une seule fois par catégorie, peu importe le
# nombre d'occurrences) — voir _score_to_severity ci-dessous pour les seuils.
_WEIGHTS = {
    "files": 1,
    "registry": 1,
    "network": 1,
    "execution": 1,
    "shell_execution": 2,  # Run/RunWait invoquant cmd.exe/powershell(.exe)
    "elevation": 2,
    "persistence": 2,
    "obfuscation": 2,
}
_SEVERE_THRESHOLD = 4
_MODERATE_THRESHOLD = 1

_CATEGORY_PATTERNS: dict[str, list[re.Pattern]] = {
    "files": [re.compile(r"\bFileDelete\b", re.I), re.compile(r"\bFileRemoveDir\b", re.I)],
    "registry": [re.compile(r"\bRegWrite\b", re.I), re.compile(r"\bRegDelete\b", re.I)],
    "network": [
        re.compile(r"\bUrlDownloadToFile\b", re.I),
        re.compile(r"\bDownload\s*\(", re.I),  # Download(url, chemin) — fonction v2
        re.compile(r"WinHttp\.WinHttpRequest", re.I),
        re.compile(r"MSXML2\.XMLHTTP", re.I),
    ],
    # \bRun\b ne matche jamais à l'intérieur de "RunAs" (pas de frontière de
    # mot entre "Run" et "As", tous deux des caractères de mot) : pas besoin
    # d'exclusion explicite.
    "execution": [re.compile(r"\bRun\b", re.I), re.compile(r"\bRunWait\b", re.I)],
    "elevation": [re.compile(r"\bRunAs\b", re.I)],
    "persistence": [
        re.compile(r"\\Startup\\", re.I),
        re.compile(r"Start Menu\\Programs\\Startup", re.I),
        re.compile(r"\\Run\\", re.I),
        re.compile(r"\\RunOnce\\", re.I),
    ],
}
# Indicateurs cmd.exe/powershell — traités à part de "execution" (poids
# renforcé), recherchés sur tout le texte plutôt que ligne par ligne (v1 :
# simplification volontaire, un faux positif ici ne fait que pousser vers un
# avertissement plus prudent, jamais l'inverse).
_SHELL_INDICATORS = re.compile(r"\b(cmd(\.exe)?\s*/c|powershell(\.exe)?\s*-)", re.I)

_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{80,}={0,2}")
_STRING_CONCAT_CHAIN = re.compile(r'(?:"[^"\n]*"\s*\.\s*){3,}')

# UrlDownloadToFile/Download(), cible/variable -> plus tard un Run/RunWait
# référençant la MÊME cible : escalade forcée en "severe" (exigence
# explicite), indépendamment du score par ailleurs. Download(url, chemin)
# couvert au même titre qu'UrlDownloadToFile (v1.1) — c'est la fonction v2
# équivalente, le même risque combiné s'applique.
_DOWNLOAD_LEGACY = re.compile(r"UrlDownloadToFile\s*,\s*[^,]+,\s*([^\s,\)]+)", re.I)
_DOWNLOAD_FUNC = re.compile(r"UrlDownloadToFile\s*\(\s*[^,]+,\s*([^,\)]+)", re.I)
_DOWNLOAD_V2 = re.compile(r"\bDownload\s*\(\s*[^,]+,\s*([^,\)]+)", re.I)


@dataclass
class HeuristicResult:
    categories: set = field(default_factory=set)
    severity: str = SEVERITY_NONE
    score: int = 0
    finding_keys: list = field(default_factory=list)


def _score_to_severity(score: int) -> str:
    if score >= _SEVERE_THRESHOLD:
        return SEVERITY_SEVERE
    if score >= _MODERATE_THRESHOLD:
        return SEVERITY_MODERATE
    return SEVERITY_NONE


def _detect_download_then_run(script_text: str) -> bool:
    targets = []
    for pattern in (_DOWNLOAD_LEGACY, _DOWNLOAD_FUNC, _DOWNLOAD_V2):
        targets += [m.group(1).strip().strip('"') for m in pattern.finditer(script_text)]
    if not targets:
        return False
    for target in targets:
        # Nom de variable (sans %) OU chemin littéral : les deux formes sont
        # cherchées, en frontière de mot pour éviter un faux positif sur une
        # sous-chaîne (ex: cible "a" matchant "abc").
        needle = re.escape(target.strip("%"))
        if not needle:
            continue
        if re.search(rf"\bRun(Wait)?\b[^\n]*\b{needle}\b", script_text, re.I):
            return True
    return False


def analyze_script(script_text: str) -> HeuristicResult:
    categories: set[str] = set()
    finding_keys: list[str] = []

    for category, patterns in _CATEGORY_PATTERNS.items():
        if any(p.search(script_text) for p in patterns):
            categories.add(category)
            finding_keys.append(f"script_security.finding.{category}")

    if "execution" in categories and _SHELL_INDICATORS.search(script_text):
        categories.add("shell_execution")
        finding_keys.append("script_security.finding.shell_execution")

    if _BASE64_RUN.search(script_text) or _STRING_CONCAT_CHAIN.search(script_text):
        categories.add("obfuscation")
        finding_keys.append("script_security.finding.obfuscation")

    score = sum(_WEIGHTS[c] for c in categories)
    severity = _score_to_severity(score)

    if _detect_download_then_run(script_text):
        categories.add("download_then_run")
        finding_keys.append("script_security.finding.download_then_run")
        severity = SEVERITY_SEVERE  # override inconditionnel, voir docstring de _DOWNLOAD_* ci-dessus

    return HeuristicResult(categories=categories, severity=severity, score=score, finding_keys=finding_keys)
