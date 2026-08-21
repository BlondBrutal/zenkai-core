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

## Architecture : verrouillage de licence "1 clé = 1 appareil"

La vérification de licence (`features/license/`) ne lit plus jamais le Gist
GitHub de licences directement depuis l'app : elle passe par un **Worker
Cloudflare** (`cloudflare-worker/worker.js`, gratuit, à déployer séparément
— voir plus bas) qui sert de relais. Raison : une vérification purement
côté client (l'ancienne version, un simple `GET` sur l'URL brute du Gist)
est **contournable** — n'importe qui peut patcher l'exécutable ou rejouer
la réponse HTTP pour se faire passer pour une clé active. Le verrouillage
"1 clé = 1 appareil" (empêcher qu'une même clé serve sur plusieurs PC) est
donc décidé **côté serveur**, jamais côté client :

- `features/license/hardware_id.py::get_hardware_id()` calcule un
  identifiant stable de la machine à partir du **MachineGuid Windows**
  (`HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid`, généré une seule
  fois à l'installation de Windows) — **jamais l'IP ou l'adresse MAC**,
  qui changent selon le réseau/le matériel. Seul un hash SHA-256 de ce
  GUID est envoyé au serveur, jamais le GUID brut.
- `features/license/license_manager.py::check_key_online()` envoie un
  `POST /activate` avec `{ "key": ..., "hardware_id": ... }` au Worker
  (URL configurée dans `config/license_config.json::activate_url`) au
  lieu de lire le registre directement.
- Le Worker (voir `cloudflare-worker/worker.js`) lit/écrit le Gist via
  l'API GitHub avec un **token stocké en secret Cloudflare**, jamais
  exposé au client. Décision : clé absente -> `not_found` ; `actif=false`
  -> `deactivated` ; pas encore de `hardware_id` enregistré sur cette
  entrée -> première activation, l'enregistre (`PATCH` du Gist) et renvoie
  `valid` ; `hardware_id` déjà enregistré et identique -> `valid` (même
  appareil qui revérifie) ; `hardware_id` déjà enregistré et différent ->
  `already_used` (bloqué, un autre appareil a déjà cette clé).
- `LicenseStatus.ALREADY_USED` (nouveau statut, `ui/pages/page_license.py`)
  affiche un message distinct de `NOT_FOUND`/`DEACTIVATED` — clé qui existe
  et est active, mais verrouillée sur un autre appareil.
- La grâce hors-ligne de 3 jours côté client (`_check_offline_grace`,
  `config/license_config.json::grace_days`) est inchangée : si le Worker
  est injoignable et qu'une clé locale valide a déjà été vérifiée dans les
  3 derniers jours, l'app reste débloquée sans réseau. Une réponse
  **définitive** du serveur (`not_found`/`deactivated`/`already_used`)
  efface au contraire tout de suite le cache local (`clear_license()`) —
  aucune grâce hors-ligne ne doit survivre à un refus explicite.

**Débloquer manuellement un ami qui change de PC** : son ancien
`hardware_id` reste verrouillé sur son entrée du Gist après un changement
de machine — éditer directement le Gist (bouton "Edit" sur la page du
Gist, https://gist.github.com/BlondBrutal/...) et remettre
`"hardware_id": null` sur son entrée (garder `"actif": true` inchangé).
Sa prochaine vérification (lancement de l'app ou bouton "Revérifier")
verrouillera automatiquement son nouveau `hardware_id`.

**Déploiement du Worker** (gratuit, compte Cloudflare personnel de
l'utilisateur — jamais fait par Claude Code, accès à un compte tiers) :
1. Créer un compte sur https://dash.cloudflare.com/sign-up (gratuit, le
   plan "Workers Free" suffit largement pour ce volume de requêtes).
2. Dans le dashboard : "Workers & Pages" -> "Create" -> "Create Worker" ->
   lui donner un nom (ex: `zenkai-license-relay`) -> "Deploy" (déploie un
   Worker vide d'abord, normal).
3. "Edit code" (éditeur en ligne) -> remplacer tout le contenu par celui
   de `cloudflare-worker/worker.js` de ce dépôt -> "Deploy".
4. Dans les réglages du Worker : "Settings" -> "Variables and Secrets" ->
   "Add" :
   - `GITHUB_TOKEN` : cocher "Encrypt" (secret) — un token GitHub avec la
     permission **"gist"** uniquement (Settings -> Developer settings ->
     Personal access tokens -> Fine-grained tokens, ou un classic token
     avec le scope `gist`), jamais un token avec des permissions plus
     larges que nécessaire.
   - `GIST_ID` : variable normale (pas besoin de chiffrer) — l'identifiant
     dans l'URL du Gist (ex: `2d05f981baa371e93727e2d773865ccc`).
   - `GIST_FILENAME` : variable normale — le nom du fichier JSON dans le
     Gist (ex: `zenkai_licenses.json`).
5. Copier l'URL du Worker affichée dans le dashboard (ex:
   `https://zenkai-license-relay.<ton-compte>.workers.dev`) et la coller
   dans `config/license_config.json::activate_url`, en ajoutant `/activate`
   à la fin.
6. Tester avec `curl` ou Postman : `POST` sur cette URL avec un body
   `{"key": "ZK-XXXX-XXXX-XXXX", "hardware_id": "test"}` doit répondre
   `{"status": "valid", "nom": "..."}` (ou `not_found` si la clé n'existe
   pas dans le Gist).

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

## Architecture : Fleasion (remplacement d'assets Roblox)

La page Fleasion (`ui/pages/page_fleasion.py`, `features/fleasion/`) gère
des presets de substitution d'assets Roblox (textures/sons/meshes) via
**Fleasion** (https://github.com/fleasion/Fleasion, GPL-3.0) — une appli
tray + proxy local qui s'intercale entre Roblox et son CDN, sans jamais
modifier les fichiers du jeu ni injecter de code. Contrairement à
AutoHotkey (Custom Script), un preset Fleasion est une liste STRUCTURÉE de
règles (Asset ID -> ID/URL/fichier local/suppression), jamais du code
arbitraire — **pas d'analyse heuristique de sécurité** pour cette page,
volontairement.

**Différence structurelle majeure avec AutoHotkey** (recherchée via
WebSearch/WebFetch sur le dépôt GitHub et fleasion.com avant
implémentation, PAS de documentation officielle CLI trouvée) : Fleasion
n'a **aucun mode CLI/headless** — c'est une appli tray unique qui charge
elle-même, à son propre démarrage, tous les fichiers JSON présents dans
`%LocalAppData%\FleasionNT\configs\`. Zenkai Core ne "lance" donc jamais un
preset précis comme un script AHK : il **dépose/retire des fichiers** dans
ce dossier (`features/fleasion/config_writer.py`, toujours dans un
sous-dossier dédié `configs\ZenkaiCore\`, jamais à la racine — pour ne
jamais toucher aux profils que l'utilisateur aurait créés lui-même via le
Dashboard Fleasion), et lance/arrête séparément le process `Fleasion.exe`
lui-même (`features/fleasion/process_manager.py`), PARTAGÉ entre tous les
presets actifs (un seul process, jamais un par preset comme pour AHK) —
comptage de références tenu dans `ui/pages/page_fleasion.py::FleasionPage`
(`_active_entry_ids`) : le process ne démarre qu'au premier preset activé,
ne s'arrête qu'au dernier qui repasse OFF.

**Le coupe-circuit global "Fleasion actif" NE tue PAS le process** —
différence assumée avec `custom_scripts_globally_enabled`/
`macros_globally_enabled` (qui arrêtent tout ce qui tourne) : OFF réécrit
seulement Statut=Off sur toutes les règles déployées de nos presets actifs
(`config_writer.undeploy_preset`), sans jamais toucher au process
`Fleasion.exe` — l'utilisateur peut aussi s'en servir pour des presets
créés hors de cette page, qu'un OFF depuis Zenkai Core ne doit pas
interrompre. C'est le toggle "Actif" **par preset**, dans la Bibliothèque
(mécanique équivalente au Start/Stop par script d'AutoHotkey), qui
lance/arrête réellement le process partagé — journalisé dans
`core/security_log.py::Category.EXTERNAL_EXECUTION` (catégorie déjà
existante, réutilisée telle quelle, pas de nouvelle catégorie créée).

**CAVEAT IMPORTANT — schéma JSON non vérifié** : le format exact du fichier
déployé (`config_writer._to_fleasion_json`, noms de champs `assetIds`/
`mode`/`replaceWith`/`status`/`name`) est construit À VUE de la
documentation publique (Asset ID(s)/Replace With/Status/Name/Mode, décrits
en langage naturel sur fleasion.com et dans le README GitHub), **jamais
vérifié contre un vrai fichier JSON exporté par une installation réelle**
(aucun exemple disponible au moment de l'implémentation). Toute la
traduction est isolée dans cette seule fonction — si les vrais noms de
champs diffèrent une fois testés en conditions réelles, c'est la SEULE
fonction à corriger. Ne jamais supposer ce schéma fiable sans l'avoir
vérifié soi-même contre une vraie installation Fleasion au préalable.

**Détection/embarquement** (`features/fleasion/fleasion_detect.py`), même
priorité qu'`ahk_detect.py` (copie embarquée d'abord, repli système
ensuite) mais deux différences : nom de fichier **versionné**
(`Fleasion*.exe` via `glob.glob`, pas un nom fixe comme `AutoHotkey64.exe`)
et repli système **best-effort** (aucun registre Windows documenté pour
Fleasion, contrairement à `HKLM/HKCU\SOFTWARE\AutoHotkey` — chemins
usuels `%LocalAppData%\Programs\Fleasion\`/`%ProgramFiles%\Fleasion\` +
`shutil.which`, à ajuster si l'installeur officiel diffère). **Le vrai
binaire Windows (`assets/runtime/fleasion/Fleasion*.exe`) et sa licence
GPL-3.0 en texte n'ont PAS été embarqués par Claude** (impossible de
télécharger/embarquer un vrai binaire externe depuis une session d'agent) —
à déposer manuellement depuis
https://github.com/fleasion/Fleasion/releases, exactement comme
`assets/runtime/ahk/` a été peuplé à l'origine pour AutoHotkey.

Stockage des presets (`features/fleasion/preset_store.py`) : un fichier
`.zkfleasion` (JSON) par preset sous
`core.paths.get_fleasion_presets_dir()`, plus un sous-dossier `<id>/assets/`
(nommé d'après l'id, JAMAIS le nom slugifié — un renommage du preset ne
doit jamais casser le chemin vers ses fichiers déjà importés) pour les
fichiers "Local" (texture/son/mesh) choisis via `QFileDialog`. Export/Import
utilisent un **ZIP** (`.zip`, pas une copie JSON brute comme le `.zkscript`
d'AutoHotkey) : un preset Fleasion combine intrinsèquement des règles ET des
fichiers locaux, qu'un JSON seul ne peut pas transporter sans casser les
références "Local" une fois réimporté ailleurs.

## Suite de tests automatisés (pytest)

`pytest` (voir `requirements-dev.txt`) couvre toute la logique pure/
sérialisation testable sans interaction manuelle : configs macros
(`.zkmacro`, Simple et Pixel), Fast Flags (`ClientAppSettings.json` +
presets), heuristiques Custom Script, traduction de touches (`key_names.py`),
détection de jeu, calcul de risque/bottleneck/cartes de statut Performance,
obfuscation de licence, i18n, config statique/persistante, et tous les
gestionnaires de process (`process_manager.py` de Custom Script/Fleasion).
Windows/psutil/pydirectinput/pynput sont TOUJOURS mockés — jamais un vrai
process lancé, jamais le vrai registre/`%APPDATA%` touché (chemins
redirigés vers `tmp_path` via `monkeypatch`). Le verrouillage de licence
"1 clé = 1 appareil" (`test_license_manager.py`, `test_hardware_id.py`) est
couvert avec un faux serveur HTTP local (stdlib `http.server`, reproduit la
décision de `cloudflare-worker/worker.js`) et un `MachineGuid` mocké —
jamais un vrai appel réseau au Worker Cloudflare ni une vraie lecture du
registre Windows.

Lancer la suite : `pytest` (ou `python -m pytest`) depuis la racine du dépôt
— `tests/conftest.py` force `QT_QPA_PLATFORM=offscreen` automatiquement
(plusieurs modules testés importent PyQt6 pour ses enums/types sans jamais
ouvrir de fenêtre), `pytest.ini` déclare `testpaths = tests`. Compatible
avec l'ancienne suite `unittest.TestCase` déjà en place (pytest exécute les
deux styles indifféremment dans le même run).

**Non automatisable** (nécessite une vraie session Windows/Qt/Roblox, à
tester manuellement) : tout `ui/` (widgets/pages/overlays Qt réels),
`features/cursor/win_cursor.py`/`roblox_overlay.py`/`crosshair_overlay.py`
(vraie manipulation de curseur système, vrais overlays toujours au-dessus),
`features/macro_simple/player.py`/`hotkey_listener.py`/`native_key_blocker.py`
et `features/macro_pixel/pixel_watcher.py`/`key_swap_listener.py` (vraie
simulation/écoute clavier-souris globale — dangereux à exécuter en CI),
`features/performance/live_monitor.py`/`fps_monitor.py`/`ping_monitor.py`
(vraie mesure CPU/GPU/réseau, PresentMon), `features/performance/fixes.py`
(vraies écritures registre/service Windows), le vrai lancement dé-élevé via
le Planificateur de tâches (`deelevate.py`, déjà testé avec la chaîne COM
mockée — seul le VRAI comportement, niveau d'intégrité du process lancé,
reste manuel), le vrai scan Windows Defender, le vrai appel réseau au
Worker Cloudflare/Gist de licences (`cloudflare-worker/worker.js` lui-même,
JavaScript, hors du périmètre de `pytest` — à tester via `curl`/Postman
une fois déployé, voir la section licence plus haut), et le vrai
lancement/détection de Roblox et de l'exécutable Fleasion (jamais
embarqué, voir plus haut).

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

**Texte coupé (descendantes g/j/p/q/y rognées) sur un bouton à hauteur
FIXE** : jamais corriger au cas par cas "à l'œil" — un bouton QSS
(`QPushButton` + classe `.xxxButton`) à hauteur LIBRE (pas de
`setFixedHeight`/`setFixedSize`) est TOUJOURS sûr par construction : Qt
calcule lui-même `sizeHint()` à partir de la vraie hauteur de police
(`QFontMetrics(police).height()`, qui réserve déjà tout l'espace
nécessaire aux descendantes) plus le padding/la bordure QSS. Le risque
n'apparaît QUE quand une hauteur fixe plus PETITE que ce calcul naturel
est imposée par-dessus (`setFixedHeight`/`setFixedSize` sur le bouton, ou
une ligne de tableau/`setRowHeight` trop juste pour un widget de cellule) :
avant d'imposer une hauteur fixe à un bouton texte (nouveau ou existant),
vérifier par un petit script Qt hors-ligne (`QFontMetrics(bouton.font()).height()`
contre la hauteur de contenu réellement disponible = hauteur fixe moins
2×bordure moins padding haut+bas) plutôt que de juger au rendu à l'œil —
un déficit de ne serait-ce qu'1px rogne déjà le texte. Trouvé et corrigé une
première fois (bouton `KeyCaptureWidget`, voir `.compactNeutralButton`
ci-dessous), puis RETROUVÉ ailleurs lors d'un audit complet de tous les
boutons de l'app (2026-08-21) — preuve que le cas par cas ne suffit pas :
- `ui/styled_dropdown.py::StyledDropdown` (dropdown "Mode") utilisait la
  classe `.neutralButton` (padding vertical 10px, pensé pour une hauteur
  libre) alors qu'il vit TOUJOURS à une hauteur fixe compacte (32px dans
  `macro_simple_tab.py`, 34px dans `page_fleasion.py`) — texte rogné en
  bas. Bascule sur `.compactNeutralButton` (theme.qss), la même variante à
  padding réduit (4px) déjà créée pour `KeyCaptureWidget` — nom généralisé
  (l'ancien nom `.hotkeyCaptureButton` ne convenait plus, réutilisée par un
  widget qui n'a rien à voir avec la capture de touche).
- `ui/sidebar.py::Sidebar` — `settings_button.setFixedHeight(36)` : 36px
  moins 2×10px de padding = 16px de contenu disponible, alors que la police
  13px de `#settingsButton` a besoin de 17px réels (`QFontMetrics.height()`)
  — déficit d'1px. Remplacé par `38px`, la hauteur naturelle que Qt calcule
  lui-même pour ce bouton (`sizeHint()`) — toujours préférer cette valeur
  mesurée à un chiffre rond deviné.
- Vérifiés SANS problème lors du même audit (déjà assez de marge) :
  `.primaryButton`/`.secondaryButton`/`.neutralButton`/`.navButton`/
  `.tableCellButton` à leurs hauteurs actuelles, toutes les tailles
  `AnimatedButton` réellement utilisées dans l'app (même la plus petite,
  `browse_btn` de Fleasion à 26px/police 11px).

**Boutons dans une cellule de tableau/ligne à hauteur fixe** (même
principe que ci-dessus, ex. `ActionCaptureWidget`/`.tableCellButton` dans
`macro_simple_tab.py`, `_CELL_HEIGHT`) : la hauteur de LIGNE (`setRowHeight`/
`_ROW_HEIGHT`) joue exactement le même rôle qu'un `setFixedHeight` direct
sur le bouton — même vérification à faire, pas seulement sur la hauteur du
widget lui-même.

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
- `QScrollArea` "nue" (conteneur de page/onglet) : appeler
  `apply_viewport_scrollbar_gap(scroll_area)` juste après `setWidget(...)` —
  **la même fonction/API que pour un widget à scrollbar interne ci-dessous**
  (`QScrollArea` est, elle aussi, un `QAbstractScrollArea`). **Jamais** un
  `margin` QSS posé sur la `QScrollBar` elle-même — vérifié sans aucun effet
  (ni horizontal ni vertical). Et surtout : **jamais non plus** un
  `padding-right` QSS posé sur la `QScrollArea` elle-même
  (`scrollarea_gap_qss()`, ancienne approche ici, retirée) — piège vérifié
  par mesure directe de géométrie (page Macro puis Performance, toutes deux
  concernées) : sur une `QScrollArea` nue, ce padding rogne tout le bloc
  viewport+scrollbar DEPUIS le bord droit AVANT qu'ils ne se partagent cet
  espace entre eux, donc le vide obtenu apparaît APRÈS la scrollbar (entre
  elle et le bord de la fenêtre/carte), jamais AVANT (entre le contenu et
  elle) — contenu et scrollbar restent accolés malgré ce padding, symptôme
  exact d'un contenu qui "touche" la barre malgré la règle en apparence bien
  appliquée. Seul `setViewportMargins` (via `apply_viewport_scrollbar_gap`)
  rétrécit réellement le viewport lui-même, indépendamment de la position de
  la scrollbar — un `padding-top`/`padding-bottom` QSS reste, lui, valide
  pour un inset vertical (voir page_performance.py) : viewport et scrollbar
  partagent alors le MÊME espace au lieu d'être côte à côte, donc pas le
  même effet de bord.
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

## Empaquetage (PyInstaller)

`ZenkaiCore.spec` (racine du dépôt, écrit à la main — voir l'exception
dédiée dans `.gitignore`, la règle générale `*.spec` visant les fichiers
auto-générés jetables d'un `pyinstaller main.py` lancé sans .spec) construit
un exécutable Windows autonome à partir de `main.py`.

**Build** : `pyinstaller ZenkaiCore.spec --noconfirm --clean` depuis la
racine du dépôt (nécessite `pyinstaller`+`pyinstaller-hooks-contrib`, tous
deux dans `requirements.txt`). Résultat dans `dist/ZenkaiCore/` (dossier
`build/`/`dist/` déjà gitignorés, jamais committés).

**Mode "onedir", pas "onefile"** — choix déterminant pour CETTE app
précisément, pas une préférence générique :
- L'app se relance elle-même en admin à CHAQUE démarrage
  (`core/elevation.py::relaunch_as_admin`, voir sa docstring). Un
  "onefile" ré-extrairait tout le bundle (runtime Python + Qt6 + tous les
  binaires embarqués : AutoHotkey64/32.exe, PresentMon, un jour Fleasion)
  dans un dossier temporaire À CHAQUE lancement — et donc DEUX FOIS de
  suite à chaque démarrage normal (une fois pour le process non élevé,
  une deuxième fois pour le process élevé qui le relance), avec le délai
  d'extraction correspondant.
- Un exécutable "onefile" auto-extractible est aussi plus systématiquement
  signalé par les antivirus/Windows Defender (technique de packing
  courante chez les malwares) qu'un dossier "onedir" classique.
- Contrepartie assumée : distribuer un dossier plutôt qu'un fichier unique
  — zippé pour la distribution (`dist/ZenkaiCore/` → `.zip`), ce qui reste
  la pratique standard de toute façon.

**Ressources embarquées** (`datas` du .spec) : `assets/`, `vendor/presentmon/`,
`config/`, `translations/`, `CHANGELOG.json` — copiés TELS QUELS, à la même
profondeur relative qu'en dev. Nécessaire car tous les modules qui lisent
ces dossiers (`ahk_detect.py`, `fleasion_detect.py`, `fps_monitor.py`,
`fastflags/manager.py`, `core/static_config.py`, `core/i18n.py`,
`core/changelog.py`, `ui/sidebar.py`, `ui/main_window.py`, `ui/tray.py`,
`ui/splash.py`) recalculent leur chemin depuis leur propre `__file__`
jusqu'à la racine du bundle (`sys._MEIPASS`, qui pointe vers
`dist/ZenkaiCore/_internal/` avec PyInstaller ≥ 6 en mode onedir) — le
même mécanisme qu'en dev (racine = racine du dépôt), donc AUCUN code n'a eu
besoin d'être modifié pour fonctionner une fois empaqueté. Si un nouveau
module lit un fichier sous `assets/`/`vendor/`/`config/`/`translations/`,
réutiliser cette même convention (`__file__`-relative, jamais un chemin
relatif nu du genre `open("assets/...")` qui suppose un `cwd` précis) —
sinon l'ajouter aussi aux `datas` du .spec.

**Icône** : `assets/logo/logo.ico` (déjà présent dans le dépôt), posée à la
fois sur l'`EXE()` du .spec (icône du fichier .exe) et déjà appliquée à la
fenêtre elle-même au runtime (`main.py`, indépendant du build).

**Pas de manifeste `requireAdministrator`** : l'app gère elle-même son
élévation UAC au démarrage avec un repli explicite "continuer sans droits
admin" si l'utilisateur refuse le prompt (voir `core/elevation.py`) — un
manifeste forcé imposerait l'élévation au niveau Windows et casserait ce
choix. Ne jamais ajouter `uac_admin=True` (ou un manifeste XML équivalent)
à l'`EXE()` du .spec sans relire cette note.

**Piège pywin32 déjà rencontré** : `win32timezone` doit être listé
explicitement dans `hiddenimports` du .spec. Jamais importé nulle part
dans notre propre code, mais requis en coulisses par pywin32 dès qu'une
propriété COM de type DATE est convertie (`import wmi` dans
`features/performance/system_info.py`, `Schedule.Service` dans
`features/custom_script/deelevate.py`) — PyInstaller ne le détecte pas
tout seul (jamais un `import win32timezone` littéral dans le code de
pywin32 lui-même, chargé dynamiquement). Sans cette ligne, l'erreur
n'apparaît qu'à l'usage réel (première requête WMI ou premier lancement
dé-élevé), jamais au moment du build — si une erreur `ModuleNotFoundError`
similaire apparaît un jour pour un autre module jamais importé
explicitement, le réflexe est le même : l'ajouter à `hiddenimports`
plutôt que de chercher un `import` manquant dans notre propre code.

**Vérification faite lors de la mise en place** (build réel, testé sur
cette machine) : build via la commande ci-dessus (aucune erreur, warnings
non bloquants uniquement — dépendances optionnelles Linux/macOS de
`pynput`, `pywin32.gen_py`...) ; toutes les ressources confirmées présentes
dans `dist/ZenkaiCore/_internal/` ; le dossier `dist/ZenkaiCore/` copié
HORS du dépôt (`%TEMP%`) puis l'exe lancé depuis là — log applicatif
(`%APPDATA%\ZenkaiCore\logs\zenkaiontop.log`) confirmant un démarrage
complet (élévation, chargement des traductions/du thème, construction de
TOUTES les pages y compris Fleasion/Custom Script/Performance, vérification
de licence réseau réelle exécutée sur son thread dédié), fenêtre "Zenkai
Core" visible et réactive (`Get-Process` : `Responding = True`). Le process
s'est avéré tourner à un niveau d'intégrité supérieur à celui du terminal
de build (élévation UAC réussie sans invite visible — probablement une
politique locale "élever sans invite" déjà configurée sur cette machine) :
confirmation supplémentaire que le chemin élevé fonctionne aussi, mais pas
un test représentatif du VRAI prompt UAC interactif (impossible à cliquer
depuis un terminal automatisé) — à confirmer une fois par un double-clic
manuel sur une machine avec le prompt UAC standard actif.
