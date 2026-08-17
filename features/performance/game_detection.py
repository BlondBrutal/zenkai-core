"""
Détection d'un jeu connu actuellement EN COURS D'EXÉCUTION (parmi les
processus du système, pas seulement la fenêtre au premier plan) — sert au
bouton dynamique "Optimiser pour {jeu détecté}" de la page Performance (voir
ui/pages/page_performance.py::_build_optimize_card) et à l'overlay Ping/FPS
(voir features/performance/ping_monitor.py/fps_monitor.py).

Parcourt psutil.process_iter() plutôt que la fenêtre active de Windows
(ancienne approche ici, voir historique) : détecte donc le jeu même quand
c'est Zenkai Core lui-même qui a le focus (ex: l'utilisateur retouche un
réglage pendant que le jeu tourne en arrière-plan, ou l'overlay est affiché
PAR-DESSUS le jeu — auquel cas la fenêtre au premier plan est souvent
l'overlay lui-même, pas le jeu), pas seulement quand le jeu est lui-même la
fenêtre active.

KNOWN_GAMES est un simple dict "nom d'exécutable -> nom affiché" : pour
reconnaître un nouveau jeu plus tard, il suffit d'ajouter une ligne ici,
aucune autre logique à toucher.
"""
import psutil

# Nom d'exécutable Roblox, en minuscules (psutil.Process.name() est comparé
# en minuscules ci-dessous) — clé de référence pour distinguer "c'est
# Roblox" (recommandation Fast Flags pertinente) de "c'est un autre jeu
# connu" (seules les 4 corrections Windows génériques ont du sens).
ROBLOX_EXE_NAME = "robloxplayerbeta.exe"

# Ajouter un jeu ici (nom d'exe en minuscules -> nom affiché) suffit à le
# faire reconnaître par detect_foreground_game(), sans rien changer d'autre.
#
# Le nom d'exe doit être celui du process RÉELLEMENT propriétaire de la
# fenêtre de jeu au premier plan (pas forcément le nom du raccourci/lanceur
# visible sur le Bureau) : plusieurs jeux ci-dessous lancent un launcher
# séparé (ex. Riot Client pour Valorant) puis un process "*-Win64-Shipping"
# distinct pour la fenêtre de jeu elle-même — c'est ce second nom qu'il faut
# reconnaître ici.
KNOWN_GAMES: dict[str, str] = {
    ROBLOX_EXE_NAME: "Roblox",
    "valorant-win64-shipping.exe": "Valorant",
    "valorant.exe": "Valorant",
    "csgo.exe": "Counter-Strike: Global Offensive",
    "cs2.exe": "Counter-Strike 2",
    "fortniteclient-win64-shipping.exe": "Fortnite",
    "leagueclient.exe": "League of Legends",
    "league of legends.exe": "League of Legends",
    "dota2.exe": "Dota 2",
    "r5apex.exe": "Apex Legends",
    "overwatch.exe": "Overwatch 2",
    "rainbowsix.exe": "Rainbow Six Siege",
    "rocketleague.exe": "Rocket League",
    "tslgame.exe": "PUBG: Battlegrounds",
    "gta5.exe": "Grand Theft Auto V",
    # "javaw.exe" (Minecraft Java Edition) volontairement absent : ce nom de
    # process est partagé par N'IMPORTE QUELLE application Java (IDE, outils
    # divers...), pas seulement Minecraft — l'ajouter déclencherait "Optimiser
    # pour Minecraft" au premier plan d'une appli Java sans rapport, un faux
    # positif trompeur. Seule l'édition Bedrock, au nom d'exe unique, est
    # reconnue ci-dessous.
    "minecraft.windows.exe": "Minecraft",
}


def detect_foreground_game() -> tuple[str, str] | None:
    """Renvoie (nom_exe, nom_affiché) du premier processus EN COURS
    D'EXÉCUTION dont le nom (en minuscules) est une clé de KNOWN_GAMES, ou
    None si aucun jeu connu ne tourne actuellement — c'est ce None qui
    déclenche le libellé neutre "Optimiser pour Windows" côté page
    Performance. Ne lève jamais d'exception : un souci ici ne doit jamais
    faire planter la page Performance/l'overlay, juste faire retomber sur le
    libellé neutre.

    Si plusieurs jeux connus tournent en même temps (rare), le premier
    trouvé par psutil.process_iter() gagne — pas d'ordre de priorité
    particulier, ce cas n'a pas de "bonne" réponse évidente."""
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info.get("name") or "").lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            display_name = KNOWN_GAMES.get(name)
            if display_name is not None:
                return name, display_name
    except Exception:
        pass
    return None
