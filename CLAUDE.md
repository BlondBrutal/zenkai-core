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

## Bug récurrent connu : "trou" dans les coins arrondis des tableaux

Symptôme : sur un widget de type tableau (QTableWidget) stylé avec des
coins arrondis, un petit "trou"/interstice apparaît à la pointe de
chaque coin (les 4 coins sont touchés de la même façon), comme si la
bordure et le fond n'étaient pas parfaitement alignés.

Cause identifiée (résolu une première fois sur la page Fast Flags) :
la bordure (border) du widget est bien arrondie (border-radius), mais
le FOND (background-color) est une couche distincte avec des angles
"pointus"/carrés légèrement plus grands que le rayon de la bordure —
le coin carré du fond dépasse et traverse la bordure arrondie.

Fix : appliquer EXACTEMENT le même border-radius au fond qu'à la
bordure, sur le même élément ET sur tous les éléments empilés à cet
endroit (widget principal, viewport, tout conteneur de fond) — pas
seulement la bordure visible. Si un autre tableau de l'app affiche le
même symptôme, appliquer directement ce fix plutôt que de repartir de
zéro sur le diagnostic.
