# Zenkai Core

Logiciel desktop Windows pour les joueurs PvP de Blox Fruits (Roblox) :
macros (autorisées en PvP compétitif) + optimisation PC/jeu (Fast Flags
Roblox officiels, sans contournement d'anti-cheat).

**Statut actuel : scaffolding.** Structure du projet, thème, logo, sidebar
et 8 pages (vides pour l'instant) sont en place. Les fonctionnalités sont
implémentées une par une dans l'ordre défini dans
`ZenkaiOnTop - (Prompt).txt` (Licence → Macro Pixel → Macro Simple →
Paramètres → Diagnostic → Fast Flags → Macro Combo → Fast Flags auto-launch
→ outil keygen).

## Installation (développement)

```
pip install -r requirements.txt
python main.py
```

Nécessite Python 3.11+ sur Windows.

## Structure du projet

Voir `ZenkaiOnTop - (Prompt).txt` pour le détail complet de l'architecture
et des fonctionnalités prévues.

## Sécurité & CGU Roblox

Ce projet n'effectue aucun hooking du process Roblox, aucune manipulation
mémoire, et ne contourne aucun anti-cheat. L'édition de Fast Flags se fait
uniquement via le fichier de configuration officiel `ClientAppSettings.json`,
comme le font Bloxstrap/Voidstrap.
