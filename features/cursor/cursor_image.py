"""
Chargement/redimensionnement d'image partagé par le curseur Windows et
l'overlay Roblox : mise à l'échelle proportionnelle (plus grand côté =
`max_side`), en conservant le canal alpha d'origine — identique au principe
de BuildCursorIconFromFile / BuildCursorBitmapForOverlay dans l'AHK d'origine
(mêmes dimensions de sortie), mais via Qt plutôt que GDI+.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage

MIN_SIZE = 16
MAX_SIZE = 128
DEFAULT_SIZE = 32


def load_scaled_image(path: str, max_side: int) -> QImage | None:
    """Charge `path` et le redimensionne (plus grand côté = max_side, ratio
    conservé). Retourne None si le fichier est illisible ou vide."""
    image = QImage(path)
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        return None

    side = max(MIN_SIZE, min(MAX_SIZE, int(max_side)))
    scaled = image.scaled(
        side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    return scaled
