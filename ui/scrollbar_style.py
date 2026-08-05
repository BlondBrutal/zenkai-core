"""
Style de scrollbar aux coins arrondis, peinte nous-mêmes via QProxyStyle.

Nécessaire car le Qt Style Sheet (border-radius sur QScrollBar::handle) ne se
dessine tout simplement pas dès que la scrollbar vit à l'intérieur d'un
QStackedWidget (vérifié : même en enfant unique, affiché dès la création,
sans aucune bascule de visibilité — donc pas un problème de polish/cache,
une vraie limitation du moteur de style Qt/Fusion dans ce contexte). Peindre
nous-mêmes contourne complètement le problème.
"""
from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QProxyStyle, QScrollBar, QStyle, QStyleOptionSlider

_GROOVE_COLOR = QColor("#26262E")
_HANDLE_COLOR = QColor("#17B897")
_HANDLE_HOVER_COLOR = QColor("#1BDAB3")
# -20% puis -10% supplémentaires (11 -> 10) : la largeur du viewport (donc
# des cadres de résultats, qui prennent toute la largeur disponible) grandit
# d'autant automatiquement — l'écart avec le bord droit de la fenêtre (marge
# de BasePage, inchangée) et l'écart avec les cadres (marge droite de
# results_layout, inchangée) restent identiques.
_THICKNESS = 10
_MIN_HANDLE_LENGTH = 20


class RoundedScrollBarStyle(QProxyStyle):
    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_ScrollBarExtent:
            return _THICKNESS
        return super().pixelMetric(metric, option, widget)

    def subControlRect(self, control, option, sub_control, widget=None):
        # Le style de base (Fusion) réserve toujours la place de deux
        # boutons flèche aux extrémités de la piste dans son calcul de la
        # zone de déplacement du curseur — même si on ne les dessine jamais
        # (QSS "height:0px" ne changeait que le rendu, pas cette réservation).
        # Résultat : le curseur ne pouvait jamais atteindre les deux bouts
        # réels de la piste. On calcule donc nous-mêmes toute la géométrie,
        # sur la pleine longueur du rail, sans rien réserver pour ces boutons.
        if control == QStyle.ComplexControl.CC_ScrollBar and isinstance(option, QStyleOptionSlider):
            groove = option.rect
            vertical = option.orientation == Qt.Orientation.Vertical
            track_length = groove.height() if vertical else groove.width()

            span = option.maximum - option.minimum
            if span <= 0:
                if sub_control == QStyle.SubControl.SC_ScrollBarSlider:
                    return groove
                return QRect()

            page_step = max(option.pageStep, 1)
            handle_length = max(_MIN_HANDLE_LENGTH, round(track_length * page_step / (page_step + span)))
            handle_length = min(handle_length, track_length)
            travel = track_length - handle_length
            offset = round(travel * (option.sliderPosition - option.minimum) / span)

            if sub_control == QStyle.SubControl.SC_ScrollBarGroove:
                return groove
            if sub_control == QStyle.SubControl.SC_ScrollBarSlider:
                if vertical:
                    return QRect(groove.x(), groove.y() + offset, groove.width(), handle_length)
                return QRect(groove.x() + offset, groove.y(), handle_length, groove.height())
            if sub_control == QStyle.SubControl.SC_ScrollBarSubPage:
                if vertical:
                    return QRect(groove.x(), groove.y(), groove.width(), offset)
                return QRect(groove.x(), groove.y(), offset, groove.height())
            if sub_control == QStyle.SubControl.SC_ScrollBarAddPage:
                if vertical:
                    top = groove.y() + offset + handle_length
                    return QRect(groove.x(), top, groove.width(), max(0, groove.bottom() - top + 1))
                left = groove.x() + offset + handle_length
                return QRect(left, groove.y(), max(0, groove.right() - left + 1), groove.height())
            if sub_control in (QStyle.SubControl.SC_ScrollBarAddLine, QStyle.SubControl.SC_ScrollBarSubLine):
                return QRect()  # pas de boutons flèche du tout

        return super().subControlRect(control, option, sub_control, widget)

    def drawComplexControl(self, control, option, painter, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar or not isinstance(option, QStyleOptionSlider):
            super().drawComplexControl(control, option, painter, widget)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        rect = QRectF(option.rect)
        vertical = option.orientation == Qt.Orientation.Vertical
        groove_radius = rect.width() / 2 if vertical else rect.height() / 2

        painter.setBrush(_GROOVE_COLOR)
        painter.drawRoundedRect(rect, groove_radius, groove_radius)

        handle_rect = QRectF(self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, widget))
        if handle_rect.width() > 0 and handle_rect.height() > 0:
            hovered = bool(option.activeSubControls & QStyle.SubControl.SC_ScrollBarSlider)
            painter.setBrush(_HANDLE_HOVER_COLOR if hovered else _HANDLE_COLOR)
            handle_radius = handle_rect.width() / 2 if vertical else handle_rect.height() / 2
            painter.drawRoundedRect(handle_rect, handle_radius, handle_radius)

        painter.restore()


# Repli direct sur l'instance quand RoundedScrollBarStyle ne s'applique
# toujours pas de façon fiable (même limitation "profondément niché" que
# celle documentée en tête de fichier, mais vérifiée ici sur une scrollbar
# différente — celle de la QScrollArea de MacroPage) : constaté par
# échantillonnage de pixels, la piste restait totalement invisible (fond de
# la page qui transparaissait) malgré ce QProxyStyle ET la QSS globale déjà
# posée dans theme.qss. Appliquer le style directement sur l'instance
# contourne le problème quelle qu'en soit la cause exacte (même technique que
# pour les popups de QComboBox, voir macro_simple_tab.py). Piste ET thumb
# ont un border-radius = moitié de l'épaisseur (5px pour 10px) : les deux
# bouts (haut/bas) sont donc de vraies demi-cercles, pas juste des coins
# arrondis à angle.
def _direct_scrollbar_qss(thickness: int, min_handle_length: int, margin: str) -> str:
    radius = thickness // 2
    return f"""
QScrollBar:vertical {{
    background: {_GROOVE_COLOR.name()};
    width: {thickness}px;
    margin: {margin};
    border: none;
    border-radius: {radius}px;
}}
QScrollBar::handle:vertical {{
    background: {_HANDLE_COLOR.name()};
    min-height: {min_handle_length}px;
    border-radius: {radius}px;
}}
QScrollBar::handle:vertical:hover {{
    background: {_HANDLE_HOVER_COLOR.name()};
}}
/* Piste toujours réservée (voir style_scrollbar_directly), mais quand il n'y
   a rien à défiler (scrollbar désactivée : min == max), le thumb calculé par
   Qt occupe toute la piste dans une couleur vive — on le fond dans la piste
   plutôt que de le masquer complètement, pour garder la largeur réservée
   identique sur les 3 sous-onglets sans jamais afficher de barre pleine. */
QScrollBar::handle:vertical:disabled {{
    background: {_GROOVE_COLOR.name()};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    background: none;
    border: none;
}}
/* border-radius répété ici : add-page/sub-page sont des rectangles de
   remplissage SÉPARÉS du cadre QScrollBar:vertical lui-même — sans leur
   propre rayon, ils gardent des coins carrés au tout premier/dernier bout
   de la piste (juste avant le thumb, à l'opposé), peu importe le
   border-radius déjà posé sur le cadre englobant. */
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background-color: {_GROOVE_COLOR.name()};
    border-radius: {radius}px;
}}
"""


_DIRECT_SCROLLBAR_QSS = _direct_scrollbar_qss(_THICKNESS, _MIN_HANDLE_LENGTH, "0px")


def style_scrollbar_directly(
    bar: QScrollBar, *, thickness: int = _THICKNESS, min_handle_length: int = _MIN_HANDLE_LENGTH,
    margin: str = "0px",
) -> None:
    """À appeler explicitement sur une scrollbar dont le rendu QProxyStyle
    ne prend pas (piste invisible, extrémités carrées) : garantit le rendu
    peu importe la cascade de style, en se posant directement sur l'instance.
    `thickness`/`min_handle_length`/`margin` par défaut = look app-wide
    inchangé ; PerformancePage passe des valeurs plus généreuses pour ses 3
    onglets (barre plus épaisse, détachée du bord droit)."""
    bar.setStyleSheet(_direct_scrollbar_qss(thickness, min_handle_length, margin))
