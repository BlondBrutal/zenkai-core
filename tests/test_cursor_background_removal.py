import unittest

from PyQt6.QtGui import QColor, QImage

from features.cursor.background_removal import remove_solid_background


def _make_image(pixels: list[list[tuple[int, int, int]]]) -> QImage:
    """Construit une QImage ARGB32 opaque à partir d'une grille [y][x] de
    couleurs (r, g, b)."""
    h = len(pixels)
    w = len(pixels[0])
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    for y, row in enumerate(pixels):
        for x, (r, g, b) in enumerate(row):
            image.setPixelColor(x, y, QColor(r, g, b, 255))
    return image


class TestRemoveSolidBackground(unittest.TestCase):
    def test_black_border_becomes_transparent(self):
        black, white = (0, 0, 0), (255, 255, 255)
        image = _make_image([
            [black, black, black, black, black],
            [black, white, white, white, black],
            [black, white, white, white, black],
            [black, white, white, white, black],
            [black, black, black, black, black],
        ])
        result = remove_solid_background(image)
        self.assertEqual(result.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(result.pixelColor(2, 2).alpha(), 255)

    def test_white_border_becomes_transparent(self):
        black, white = (0, 0, 0), (255, 255, 255)
        image = _make_image([
            [white, white, white, white, white],
            [white, black, black, black, white],
            [white, black, black, black, white],
            [white, black, black, black, white],
            [white, white, white, white, white],
        ])
        result = remove_solid_background(image)
        self.assertEqual(result.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(result.pixelColor(2, 2).alpha(), 255)

    def test_enclosed_black_subject_pixel_survives(self):
        # Un pixel noir entouré par le sujet (jamais atteint depuis le bord)
        # ne doit jamais devenir transparent, même sur fond noir.
        black, white = (0, 0, 0), (255, 255, 255)
        image = _make_image([
            [black, black, black, black, black],
            [black, white, white, white, black],
            [black, white, black, white, black],
            [black, white, white, white, black],
            [black, black, black, black, black],
        ])
        result = remove_solid_background(image)
        self.assertEqual(result.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(result.pixelColor(2, 2).alpha(), 255)
        self.assertEqual(result.pixelColor(2, 2).red(), 0)

    def test_non_uniform_colorful_border_is_left_untouched(self):
        # Coins de couleurs vives (pas noir/blanc) : pas de fond uni détecté,
        # l'image ne doit pas être modifiée du tout.
        red, blue, green, yellow, white = (
            (220, 20, 20), (20, 20, 220), (20, 220, 20), (220, 220, 20), (255, 255, 255),
        )
        image = _make_image([
            [red, red, red],
            [blue, white, green],
            [yellow, yellow, yellow],
        ])
        result = remove_solid_background(image)
        for y in range(3):
            for x in range(3):
                self.assertEqual(result.pixelColor(x, y).alpha(), 255)

    def test_fully_opaque_image_returned_untouched_when_no_background(self):
        image = _make_image([[(30, 60, 90), (40, 70, 100)], [(50, 80, 110), (60, 90, 120)]])
        result = remove_solid_background(image)
        self.assertEqual(result.pixelColor(0, 0).getRgb(), image.pixelColor(0, 0).getRgb())

    def test_null_image_is_returned_as_is(self):
        image = QImage()
        result = remove_solid_background(image)
        self.assertTrue(result.isNull())


if __name__ == "__main__":
    unittest.main()
