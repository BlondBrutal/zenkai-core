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

## Design system — Zenkai Core

Base établie (extraite de `assets/styles/theme.qss`, `ui/status_colors.py`,
`ui/animated_button.py`) à réutiliser par défaut pour toute nouvelle page
ou tout nouveau composant, plutôt que d'improviser de nouvelles valeurs.

**Couleurs**
- Fond app : `#1A1A1F` — Sidebar : `#17171C` — Cartes : `#1F1F25` ou
  `#202027` selon le contexte (voir composants ci-dessous).
- Bordures neutres : `#2A2A32` (cadres/listes) ou `#33333C` (champs/tableaux).
- Accent turquoise (couleur de marque, statut OK) : `#17B897`
  (hover `#1BDAB3`, pressed `#129076`).
- Statuts (voir `ui/status_colors.py`, jamais d'emoji pour un statut) :
  OK `#17B897`, Warning `#D9A441`, Critical `#E0645A`, Neutral `#9BA1AB`.
- Texte principal `#E7E9EE`, texte secondaire `#9BA1AB`/`#C7CBD3`.

**Typographie** : `Segoe UI Variable Text` partout. Titres de page 22px/700,
sous-titres 13px, corps 12-13px, en-têtes de tableau 11px/700.

**Rayons et espacements**
- Boutons : `border-radius: 10px`. Petits boutons dans une cellule de
  tableau : `6px`. Cartes principales : `14px`. Cartes secondaires
  (navTabButton, listes, champs, combobox) : `8px`. Scrollbars : `5px`
  (moitié de leur largeur/hauteur — toujours arrondi complet).
- Le rayon d'un cadre englobant (`QFrame.tableCard`, header inclus) doit
  être répété sur CHAQUE couche empilée à cet endroit (voir bug des coins
  ci-dessus) — jamais un seul `border-radius` isolé en espérant qu'il
  s'applique en cascade.
- Padding bouton standard : `10px 18px`. Bouton compact en cellule :
  `2px 4px` / `4px 18px` selon la hauteur fixe du champ.

**Boutons (`AnimatedButton`, `ui/animated_button.py`)** — préférer ce
composant peint à la main plutôt qu'un `QPushButton` + classe QSS
(`.primaryButton` etc. existent en QSS mais ont un historique de bug de
rendu au montage dynamique) :
- `primary` : fond turquoise plein, texte sombre — action principale.
- `secondary`/`default` : contour transparent, texte turquoise — action
  courante non destructive.
- `neutral` : contour gris, texte turquoise clair — action discrète (ex:
  bouton "Définir" d'une touche).
- `danger` : contour gris (jamais rouge), seul le texte est rouge
  (`STATUS_CRITICAL`) — action destructive, sans faire ressortir le
  bouton au repos.

**Tableaux/listes** : jamais de fond plein au clic/sélection
(`QTableWidget::item:selected { background-color: transparent; }`) — seule
la couleur du curseur de texte ou un léger halo turquoise
(`rgba(23,184,151,40)`) marquent un état sélectionné/actif, jamais un
aplat de couleur.

Quand une nouvelle préférence visuelle récurrente émerge en cours de
projet (ex: comportement de clic, style d'un nouveau type de composant),
l'ajouter ici plutôt que de la re-décider à chaque nouvelle page.
