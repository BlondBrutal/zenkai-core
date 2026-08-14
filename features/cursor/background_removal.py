"""
Détourage automatique d'un fond uni (noir OU blanc) sur une image importée
pour un curseur/crosshair.

Principe : un remplissage (flood fill) qui part UNIQUEMENT des bords/coins
de l'image, jamais un filtre de couleur appliqué à toute l'image — sinon du
noir ou du blanc qui ferait partie du SUJET lui-même (ex: le contour noir
dessiné à l'intérieur d'un viseur) serait effacé à tort. Seuls les pixels
connectés au bord ET suffisamment proches de la couleur de fond détectée
deviennent transparents ; un pixel de la même couleur mais entouré par le
sujet (donc jamais atteint par le remplissage) reste intact.
"""
from collections import deque

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage

# Écart (sur le canal le plus éloigné) toléré entre un pixel et la couleur
# de fond détectée pour le considérer comme "fond" pendant le remplissage.
_BORDER_TOLERANCE = 30
# Écart toléré entre la couleur moyenne des 4 coins et le noir/blanc pur
# pour déclencher le détourage — au-delà, le bord n'est pas jugé assez
# proche d'un fond uni noir/blanc et l'image n'est pas modifiée.
_REFERENCE_TOLERANCE = 40
# Résolution de travail plafonnée : le résultat est de toute façon
# redimensionné à MAX_SIZE (128px, voir cursor_image.py) avant application,
# donc traiter au-delà de ce plafond n'apporterait aucune précision visible
# tout en ralentissant inutilement le remplissage (fait en Python pur, sans
# numpy/Pillow, ni dépendance du projet).
_MAX_PROCESS_DIM = 256


def _channel_diff(a: QColor, b: QColor) -> int:
    # "Distance" simple entre 2 couleurs : le plus grand écart parmi les 3
    # canaux (rouge/vert/bleu) — plus ce nombre est petit, plus les couleurs
    # se ressemblent.
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue()))


def _detect_background_reference(image: QImage) -> QColor | None:
    """Couleur de fond moyenne des 4 coins, seulement si elle est assez
    proche du noir ou du blanc pur — sinon None (pas de fond uni détecté)."""
    w, h = image.width(), image.height()
    corners = [
        image.pixelColor(0, 0), image.pixelColor(w - 1, 0),
        image.pixelColor(0, h - 1), image.pixelColor(w - 1, h - 1),
    ]
    avg = QColor(
        sum(c.red() for c in corners) // 4,
        sum(c.green() for c in corners) // 4,
        sum(c.blue() for c in corners) // 4,
    )
    for pure in (QColor(0, 0, 0), QColor(255, 255, 255)):
        if _channel_diff(avg, pure) <= _REFERENCE_TOLERANCE:
            return avg
    return None


def remove_solid_background(image: QImage) -> QImage:
    """Rend transparents les pixels de fond uni (noir/blanc) connectés aux
    bords de l'image. Retourne l'image INCHANGÉE (même résolution) si aucun
    fond uni noir/blanc n'est détecté aux coins."""
    if image.isNull():
        return image

    work = image.convertToFormat(QImage.Format.Format_ARGB32)
    if max(work.width(), work.height()) > _MAX_PROCESS_DIM:
        work = work.scaled(
            _MAX_PROCESS_DIM, _MAX_PROCESS_DIM,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
    w, h = work.width(), work.height()
    if w < 2 or h < 2:
        return image

    reference = _detect_background_reference(work)
    if reference is None:
        return image

    visited = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()

    def _visit(x: int, y: int) -> None:
        idx = y * w + x
        if visited[idx]:
            return
        color = work.pixelColor(x, y)
        if _channel_diff(color, reference) > _BORDER_TOLERANCE:
            return
        visited[idx] = 1
        color.setAlpha(0)
        work.setPixelColor(x, y, color)
        queue.append((x, y))

    for x in range(w):
        _visit(x, 0)
        _visit(x, h - 1)
    for y in range(h):
        _visit(0, y)
        _visit(w - 1, y)

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                _visit(nx, ny)

    return work
