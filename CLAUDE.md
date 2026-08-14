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

## Bug récurrent connu : plantage silencieux au changement de langue (reload_language)

Symptôme : l'app se ferme sans se rouvrir, aucune exception Python,
aucune trace dans les logs applicatifs — ressemble à un vrai
redémarrage raté, mais `reload_language()` (`ui/main_window.py`) ne
relance jamais le process, seulement l'UI.

Cause identifiée : `QStackedWidget.removeWidget()` appelé sur le
widget COURANT fait automatiquement basculer `currentIndex()` sur le
widget suivant — ce qui déclenche un vrai `showEvent()` sur lui, même
en pleine boucle de démontage où on ne voulait RIEN afficher. Si une
page suivante démarre un thread depuis `showEvent()` (ex:
`PerformancePage`/`LiveMonitorThread`, monitoring en direct activé par
défaut), ce thread frais tourne encore quand CETTE MÊME page est
elle-même détruite un peu plus loin dans la boucle — `hideEvent()` ne
l'arrête pas forcément (certains threads survivent volontairement à un
simple hide(), ex: overlay Performance qui doit continuer pendant
qu'on va jouer). Qt plante alors avec un `qFatal("QThread: Destroyed
while thread is still running")` dès que la suppression différée du
widget est traitée : un abort natif (Qt6Core.dll, confirmé via le
journal d'erreurs applicatives Windows, code `0xc0000409`), jamais une
exception Python catchable — un simple `try/except` autour du code de
reconstruction ne voit donc jamais rien.

Piège vérifié : `stack.setCurrentIndex(-1)` NE suffit PAS à empêcher
cette promotion — contrairement à `QStackedLayout`, `QStackedWidget` ne
traite pas `-1` comme "aucun widget courant" et re-promeut quand même
un widget dès le `removeWidget()` suivant.

Fix (voir `MainWindow.reload_language()`) :
1. Un widget `QWidget()` PLACEHOLDER jetable devient le widget courant
   (`setCurrentWidget`) avant toute suppression, et seulement retiré
   une fois toutes les anciennes pages parties — aucune vraie page ne
   redevient donc jamais "courante" pendant le démontage, donc plus
   aucun `showEvent` parasite.
2. Toute page qui possède un thread/timer qui peut légitimement
   survivre à un `hide()` (par conception, comme le monitoring
   Performance) doit définir une méthode `shutdown()` qui l'arrête de
   façon INCONDITIONNELLE et SYNCHRONE (`.stop()` + `.wait(2000)`,
   jamais un simple `.terminate()`) — `MainWindow` l'appelle sur
   chaque ancienne page juste avant `hide()`/`deleteLater()`, en plus
   (jamais à la place) du nettoyage habituel de `hideEvent`. Si une
   nouvelle page a un thread/timer démarré depuis `showEvent()` ou
   qu'un state persiste volontairement après `hide()`, lui ajouter ce
   même `shutdown()` plutôt que de repartir de zéro sur le diagnostic.

## Architecture : Custom Script / interpréteur AutoHotkey

La page Custom Script (`ui/pages/page_custom_script.py`,
`features/custom_script/`) n'utilise PAS une installation AutoHotkey
système par défaut : un interpréteur **AutoHotkey v2 portable est embarqué
directement dans le dépôt**, sous `assets/runtime/ahk/`
(`AutoHotkey64.exe`, `AutoHotkey32.exe`, `license.txt`). C'est cette copie
qui est utilisée en priorité (voir
`features/custom_script/ahk_detect.py::find_embedded_ahk_interpreter`) —
aucune installation système n'est nécessaire en usage normal.

Une détection d'installation système (registre
`HKLM`/`HKCU\SOFTWARE\AutoHotkey`, ou `%ProgramFiles%\AutoHotkey`) reste un
**repli secondaire uniquement**, pour le cas résiduel où la copie embarquée
serait absente/corrompue — jamais le chemin normal. Ce repli reconnaît à la
fois les noms d'exécutables v2 (`AutoHotkey64.exe`/`AutoHotkey32.exe`/
`AutoHotkeyUX.exe`) et v1.1 classiques (`AutoHotkeyU64.exe`/etc.), au cas où
seule une installation v1.1 traînerait sur le PC — mais l'analyse
heuristique (`features/custom_script/heuristics.py`) et tous les textes UI
ciblent la syntaxe **v2**.

Si un nouveau composant a besoin de lancer l'interpréteur, toujours passer
par `find_ahk_interpreter()` (jamais coder en dur un chemin) et par
`features/custom_script/process_manager.py::start_script`/`stop_script`
pour le suivi/arrêt fiable (jamais un `subprocess.Popen` fire-and-forget).

**Lancement dé-élevé (`features/custom_script/deelevate.py`)** : quand
l'app tourne élevée (`core.elevation.is_admin()`), un script est lancé via
une **tâche planifiée Windows temporaire et jetable** (COM
`Schedule.Service`, enregistrée directement à la RACINE du Planificateur
`"\\"` — jamais un sous-dossier dédié, voir plus bas —, nom unique par
lancement, `RunLevel=TASK_RUNLEVEL_LUA`, supprimée juste après avoir
récupéré le PID via `IRunningTask.EnginePID`) — **jamais**
`CreateProcessAsUser` avec un jeton dupliqué. Cette première approche a été
essayée puis abandonnée : elle suppose `SeAssignPrimaryTokenPrivilege` sur
le jeton appelant, un privilège **absent par défaut d'un jeton
Administrateur standard même élevé via UAC** (seuls SYSTEM et certains
comptes de service l'ont) — un problème structurel de Windows, pas une
question de correctif. Le service Planificateur de tâches tourne en SYSTEM
et possède ce privilège lui-même, donc construit le jeton dé-élevé à notre
place. Ne jamais revenir à `CreateProcessAsUser`/duplication de jeton pour
ce besoin précis sans d'abord relire cette note.

Une deuxième version rangeait ces tâches dans un sous-dossier dédié
`\ZenkaiCore\` (`GetFolder`/`CreateFolder`) — abandonné aussi : cause d'un
`ERROR_ALREADY_EXISTS` récurrent dont la cause exacte est restée
introuvable malgré plusieurs correctifs (repli sur relecture, logging
détaillé de l'échec initial de `GetFolder`...). La racine `"\\"` existe
TOUJOURS nativement (jamais besoin de `GetFolder`/`CreateFolder`) ; le nom
de tâche unique (UUID) et le nettoyage immédiat après usage suffisent déjà
à éviter toute collision/résidu. Ne jamais réintroduire de sous-dossier
dédié pour ce besoin précis sans d'abord relire cette note.

Précision pour ne pas confondre avec un bug déjà rencontré : ceci n'a
**aucun rapport** avec l'ancien mécanisme "tâche planifiée avec privilèges
élevés" retiré du projet (bug de fenêtre fantôme/boucle) — celui-là servait
à faire tourner TOUTE L'APP élevée sans reprompt UAC à chaque démarrage
(auto-élévation persistante). Ici, la tâche est un lanceur ponctuel pour UN
SEUL process enfant, au niveau LUA (dé-élevé, pas élevé), supprimée en
quelques secondes — sans rapport avec la séquence de démarrage de l'app.

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
- Le rayon d'un cadre englobant (ex : `QTableWidget#stepsTable` avec son
  `QHeaderView` intégré, voir `theme.qss`) doit être répété sur CHAQUE
  couche empilée à cet endroit (voir bug des coins ci-dessus) — jamais un
  seul `border-radius` isolé en espérant qu'il s'applique en cascade.
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

**Tableaux/listes** : jamais de fond plein au clic/sélection/survol
(`QTableWidget::item:selected { background-color: transparent; }`) — seule
la couleur du curseur de texte ou un léger halo turquoise
(`rgba(23,184,151,40)`) marquent un état sélectionné/actif, jamais un
aplat de couleur. S'applique aussi à `QListWidget` : le style app-wide
(`theme.qss`) donne par défaut un fond turquoise translucide à
`QListWidget::item:selected` — pour une liste dont les lignes portent déjà
leur propre widget peint (badge coloré, interrupteur...), surcharger
localement sur l'instance (`list_widget.setStyleSheet(...)`, jamais
`theme.qss` globalement) pour repasser `:hover`/`:selected` en
`background-color: transparent`. Attention au **double padding** dans ce
cas : `QListWidget::item` a un `padding: 6px 8px` app-wide qui s'additionne
aux marges internes du widget de ligne (`QHBoxLayout.setContentsMargins`)
— si la ligne contient un élément à hauteur fixe (ex. `ToggleSwitch`,
24px), ce padding en trop peut le faire paraître coupé/mal centré ; repasser
aussi `QListWidget::item { padding: 0px; }` dans la même surcharge locale
et laisser les marges du widget de ligne être la seule source de padding.

**Scrollbars — espace entre le contenu et la barre** : tout contenu
défilable (carte, tableau, éditeur, liste) avec une scrollbar VISIBLE doit
réserver un espace de `12px` entre son propre bord droit et la barre —
jamais un contenu collé directement contre elle. Règle centralisée dans
`ui/scrollbar_style.py` (`CONTENT_SCROLLBAR_GAP`, jamais une valeur en dur
recopiée page par page) :
- `QScrollArea` "nue" (conteneur de page/onglet) : utiliser
  `scrollarea_gap_qss()` dans son propre `setStyleSheet("QScrollArea { ...
  " + scrollarea_gap_qss() + " }")`. **Jamais** un `margin` QSS posé sur la
  `QScrollBar` elle-même — vérifié sans aucun effet (ni horizontal ni
  vertical) — c'est la `QScrollArea` qu'il faut rogner via `padding`,
  viewport ET scrollbar se déplaçant ensemble.
- Tout widget à scrollbar INTERNE (`QListWidget`, `QTableWidget`,
  `QPlainTextEdit`... — tous des `QAbstractScrollArea`) : appeler
  `apply_viewport_scrollbar_gap(widget)` juste après sa création, qui pose
  `setViewportMargins(0, 0, 12, 0)` — l'API Qt native pour ça sur ces
  widgets, déjà vérifiée par capture d'écran réelle.
- Ne pas appliquer cette règle à un widget dont la scrollbar verticale est
  volontairement masquée (`setVerticalScrollBarPolicy(ScrollBarAlwaysOff)`,
  ex: le tableau d'étapes de Macro Simple, dont le défilement molette reste
  possible sans barre visible) : rien à détacher, l'ajout serait un no-op
  qui grignoterait inutilement la largeur de contenu déjà mesurée au pixel
  près.
- Toute nouvelle page avec un contenu défilable doit appliquer cette règle
  dès sa conception, pas seulement quand quelqu'un remarque que le contenu
  touche la barre.

Quand une nouvelle préférence visuelle récurrente émerge en cours de
projet (ex: comportement de clic, style d'un nouveau type de composant),
l'ajouter ici plutôt que de la re-décider à chaque nouvelle page.
