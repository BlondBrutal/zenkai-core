"""
Capture de la couleur d'un pixel à l'écran.

`grab_pixel_color` (capture ponctuelle) et `PersistentPixelReader` (lectures
répétées en boucle serrée) utilisent tous les deux `mss` (BitBlt). Une
tentative de bascule vers `GetPixel` (Win32, DC caché — la méthode utilisée
par PixelGetColor dans "Global Macro v2.ahk") a été testée pour aller plus
vite, mais abandonnée : vérifiée contre un widget de couleur fixe connue,
elle renvoyait des valeurs incohérentes d'un appel à l'autre sur cette
machine (composition DWM + accélération matérielle modernes rendent la
lecture DC-écran legacy non fiable), alors que `mss` restait exact à chaque
lecture. Correction avant vitesse : on reste donc sur `mss`, en réutilisant
une seule instance pour toute la durée du watcher plutôt que d'en recréer
une par lecture (chaque construction réénumère les moniteurs et recrée ses
ressources internes).
"""
import mss


def grab_pixel_color(x: int, y: int) -> tuple[int, int, int]:
    """Retourne la couleur (R, G, B) du pixel à la position écran (x, y)."""
    with mss.mss() as sct:
        shot = sct.grab({"left": x, "top": y, "width": 1, "height": 1})
        b, g, r = shot.raw[0], shot.raw[1], shot.raw[2]
        return (r, g, b)


class PersistentPixelReader:
    """Lecteur de pixel pour un polling en boucle serrée : garde une seule
    capture `mss` ouverte pour toute la durée du watcher au lieu d'en
    recréer une à chaque lecture."""

    def __init__(self) -> None:
        self._sct = mss.mss()

    def read(self, x: int, y: int) -> tuple[int, int, int]:
        shot = self._sct.grab({"left": x, "top": y, "width": 1, "height": 1})
        b, g, r = shot.raw[0], shot.raw[1], shot.raw[2]
        return (r, g, b)

    def close(self) -> None:
        self._sct.close()
