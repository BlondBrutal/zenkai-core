# -*- mode: python ; coding: utf-8 -*-
"""
Fichier .spec PyInstaller pour empaqueter Zenkai Core en exécutable Windows
autonome. Build en mode "onedir" (un dossier contenant l'exe + ses
dépendances), PAS "onefile" — voir CLAUDE.md, section "Empaquetage
(PyInstaller)", pour la justification détaillée : l'app se relance
elle-même en admin à CHAQUE démarrage (core/elevation.py::
relaunch_as_admin), ce qui doublerait le coût d'extraction d'un onefile à
chaque lancement normal (extrait une fois pour le process non élevé, une
deuxième fois pour le process élevé qui le remplace).

Usage : `pyinstaller ZenkaiCore.spec --noconfirm --clean` depuis la racine
du dépôt. Résultat dans dist/ZenkaiCore/ (à distribuer en zip).
"""
import sys

block_cipher = None

# Ressources bundlées TELLES QUELLES à la racine du dossier de sortie —
# tous les modules qui les lisent (ahk_detect.py, fleasion_detect.py,
# fps_monitor.py, fastflags/manager.py, static_config.py, i18n.py,
# changelog.py, ui/sidebar.py, ui/main_window.py, ui/tray.py, ui/splash.py)
# recalculent leur chemin depuis leur propre __file__ jusqu'à la racine du
# bundle (même convention qu'en dev, où cette racine = racine du dépôt) —
# donc CHAQUE dossier ci-dessous doit rester à la même profondeur relative
# qu'en dev (assets/ à la racine, pas dans un sous-dossier "resources/" ou
# équivalent).
datas = [
    ("assets", "assets"),
    ("vendor/presentmon", "vendor/presentmon"),
    ("config", "config"),
    ("translations", "translations"),
    ("CHANGELOG.json", "."),
]

# win32timezone : jamais importé explicitement nulle part dans ce projet,
# mais requis en coulisses par pywin32 dès qu'une propriété COM de type DATE
# est convertie (WMI - features/performance/system_info.py::import wmi -,
# et Schedule.Service - features/custom_script/deelevate.py). PyInstaller ne
# le détecte pas tout seul (jamais un "import win32timezone" littéral dans
# le code de pywin32 lui-même, chargé dynamiquement) : sans cette ligne,
# l'erreur n'apparaît qu'à l'usage réel (première requête WMI ou premier
# lancement dé-élevé), jamais au moment du build.
hiddenimports = ["win32timezone"]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZenkaiCore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Pas de manifeste "requireAdministrator" ici : l'app gère sa propre
    # élévation UAC au runtime (core/elevation.py::relaunch_as_admin, avec
    # repli explicite "continuer sans droits admin" si l'utilisateur refuse
    # le prompt) — un manifeste forcé bloquerait ce choix et empêcherait
    # tout lancement non élevé.
    icon="assets/logo/logo.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ZenkaiCore",
)
