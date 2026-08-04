# Instructions permanentes pour Claude Code — Zenkai Core

## Sauvegarde Git automatique

Ce projet est versionné avec Git et sauvegardé sur un dépôt GitHub privé
(`https://github.com/BlondBrutal/zenkai-core.git`).

Règle à appliquer systématiquement, à chaque session :

1. Après avoir terminé une modification de fichiers (peu importe
   laquelle), vérifie la date du dernier commit avec :
   ```
   git log -1 --format=%cd --date=iso
   ```
2. Si plus de 24 heures se sont écoulées depuis ce dernier commit (ou
   si aucun commit n'existe), fais automatiquement :
   ```
   git add .
   git commit -m "Sauvegarde automatique - résumé court des changements récents"
   git push
   ```
   Utilise un message de commit décrivant réellement ce qui a changé
   depuis la dernière sauvegarde, pas un message générique.
3. Si moins de 24 heures se sont écoulées, ne fais rien de spécial
   (pas besoin de committer à chaque petite modification).
4. Ne demande pas confirmation pour ce commit/push automatique — c'est
   une tâche de routine, pas une décision de conception.

Le dossier `keygen/` et les fichiers sensibles (`.env`, logs) sont déjà
exclus via `.gitignore` — ne jamais les retirer de cette exclusion.
