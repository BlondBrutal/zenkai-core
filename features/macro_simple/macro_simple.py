"""
Config d'une macro Simple (Partie 1.4 du brief, "Macro type 1") : une
séquence d'actions clavier/souris construite manuellement étape par étape
par l'utilisateur (voir ui/action_capture_widget.py et
ui/pages/macro_simple_tab.py), rejouée via une touche de déclenchement
globale (features/macro_simple/hotkey_listener.py + player.py) selon un mode :
- Hold ("tant que maintenu") : boucle tant que la touche reste enfoncée.
- Toggle ("ON/OFF") : un appui lance en boucle, un second appui arrête.
- Repeat ("Répétition") : un appui lance exactement `repeat_count` passages
  de la séquence puis s'arrête tout seul (repeat_count n'a de sens que pour
  ce mode — Hold/Toggle bouclent sans limite, bornés uniquement par leur
  propre condition d'arrêt naturelle ; voir _start_player dans
  ui/pages/macro_simple_tab.py).

Il n'y a pas d'équivalent direct dans "Global Macro v2.ahk" à reprendre ici :
ce fichier ne contient que des séquences figées ("glitch boosts") et un
déclencheur pixel (déjà porté dans features/macro_pixel/), pas de moteur
d'enregistrement/rejeu générique. Le format ci-dessous est donc conçu depuis
zéro, mais reste cohérent avec PixelMacroConfig (features/macro_pixel/
pixel_macro.py) : même dossier de sauvegarde (.zkmacro JSON dans
core.paths.get_macros_dir), même champ "type" utilisé par la Bibliothèque
(page_macro.py) pour lister/importer par type. `delete_macro`/`export_macro`
sont génériques (aucune logique propre à un type) et donc partagés tels
quels depuis features.macro_pixel.pixel_macro plutôt que dupliqués ici.
"""
import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field

from core.paths import get_macros_dir

logger = logging.getLogger("zenkaiontop.macro_simple")

MACRO_TYPE = "simple"

ACTION_KEY = "key"
ACTION_MOUSE = "mouse"

TRIGGER_TOGGLE = "toggle"
TRIGGER_HOLD = "hold"
TRIGGER_REPEAT = "repeat"


@dataclass
class MacroStep:
    action: str  # ACTION_KEY ou ACTION_MOUSE
    value: str  # nom de touche pydirectinput, ou "left"/"right"/"middle" pour un clic
    x: int = 0  # coordonnées écran, utilisées seulement pour ACTION_MOUSE
    y: int = 0
    hold_ms: int = 50  # durée de maintien : keydown -> keyup
    delay_after_ms: int = 50  # délai avant l'action suivante : keyup -> prochain keydown
    # Si True (ACTION_MOUSE uniquement) : l'action se joue là où se trouve
    # déjà le curseur au moment du rejeu, sans déplacement préalable vers
    # x/y (qui restent stockés mais ignorés par le player tant que ce
    # drapeau est actif — voir features/macro_simple/player.py).
    use_current_position: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MacroStep":
        return cls(
            action=str(data.get("action", ACTION_KEY)),
            value=str(data.get("value", "")),
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            hold_ms=max(0, int(data.get("hold_ms", 50))),
            delay_after_ms=max(0, int(data.get("delay_after_ms", 50))),
            use_current_position=bool(data.get("use_current_position", False)),
        )


@dataclass
class MacroSimpleConfig:
    name: str
    hotkey: str = ""
    trigger_mode: str = TRIGGER_TOGGLE
    repeat_count: int = 1  # utilisé seulement en mode TRIGGER_REPEAT
    # Délai entre deux passages complets de la séquence tant que la macro
    # tourne, utilisé seulement en mode TRIGGER_HOLD/TRIGGER_TOGGLE (bouclent
    # sans limite — voir MacroPlayerThread.run) : sans intérêt en mode
    # TRIGGER_REPEAT (nombre de passages fixe, déjà borné par repeat_count).
    loop_delay_ms: int = 0
    steps: list[MacroStep] = field(default_factory=list)
    type: str = MACRO_TYPE

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "hotkey": self.hotkey,
            "trigger_mode": self.trigger_mode,
            "repeat_count": self.repeat_count,
            "loop_delay_ms": self.loop_delay_ms,
            "steps": [step.to_dict() for step in self.steps],
            "type": self.type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MacroSimpleConfig":
        return cls(
            name=str(data.get("name", "")),
            hotkey=str(data.get("hotkey", "")),
            trigger_mode=str(data.get("trigger_mode", TRIGGER_TOGGLE)),
            repeat_count=max(1, int(data.get("repeat_count", 1))),
            steps=[MacroStep.from_dict(s) for s in data.get("steps", [])],
            type=MACRO_TYPE,
        )


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug or "macro"


def save_macro_simple(macro: MacroSimpleConfig, existing_path: str | None = None) -> str:
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


def list_macro_simple_macros() -> list[tuple[str, MacroSimpleConfig]]:
    """Liste (chemin, config) de toutes les macros Simple valides trouvées
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
            results.append((path, MacroSimpleConfig.from_dict(data)))
        except Exception as exc:
            logger.warning("Macro illisible ignorée (%s) : %s", path, exc)
    return results


def import_macro(source_path: str) -> tuple[str, MacroSimpleConfig]:
    """Copie un fichier .zkmacro externe dans le dossier macros de l'app."""
    with open(source_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("type") != MACRO_TYPE:
        raise ValueError(f"Ce fichier n'est pas une macro Simple (type={data.get('type')!r}).")
    macro = MacroSimpleConfig.from_dict(data)
    dest = save_macro_simple(macro)
    return dest, macro
