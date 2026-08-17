"""
Tests (pytest) du chargement/redimensionnement d'image (features/cursor/
cursor_image.py) — touche uniquement QImage (aucune fenêtre/widget, aucune
API Windows), fonctionne headless avec QT_QPA_PLATFORM=offscreen comme le
reste des probes Qt de ce projet.
"""
import os

from PyQt6.QtGui import QColor, QImage

from features.cursor.cursor_image import DEFAULT_SIZE, MAX_SIZE, MIN_SIZE, load_scaled_image


def _write_png(path: str, width: int, height: int) -> None:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 0, 0, 255))
    assert image.save(path, "PNG")


def test_loads_and_scales_square_image_to_requested_size(tmp_path):
    path = str(tmp_path / "square.png")
    _write_png(path, 200, 200)
    result = load_scaled_image(path, 64)
    assert result is not None
    assert result.width() == 64
    assert result.height() == 64


def test_preserves_aspect_ratio_for_non_square_image(tmp_path):
    path = str(tmp_path / "wide.png")
    _write_png(path, 200, 100)  # 2:1
    result = load_scaled_image(path, 64)
    assert result is not None
    assert result.width() == 64
    assert result.height() == 32  # même ratio 2:1


def test_returns_none_for_missing_file(tmp_path):
    assert load_scaled_image(str(tmp_path / "does_not_exist.png"), DEFAULT_SIZE) is None


def test_returns_none_for_non_image_file(tmp_path):
    path = tmp_path / "not_an_image.png"
    path.write_text("this is definitely not a PNG file")
    assert load_scaled_image(str(path), DEFAULT_SIZE) is None


def test_max_side_clamped_to_min_size(tmp_path):
    path = str(tmp_path / "square.png")
    _write_png(path, 200, 200)
    result = load_scaled_image(path, 1)  # bien en dessous de MIN_SIZE
    assert result.width() == MIN_SIZE
    assert result.height() == MIN_SIZE


def test_max_side_clamped_to_max_size(tmp_path):
    path = str(tmp_path / "square.png")
    _write_png(path, 500, 500)
    result = load_scaled_image(path, 99999)  # bien au-dessus de MAX_SIZE
    assert result.width() == MAX_SIZE
    assert result.height() == MAX_SIZE


def test_alpha_channel_preserved(tmp_path):
    path = str(tmp_path / "alpha.png")
    image = QImage(50, 50, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 255, 0, 128))
    image.save(path, "PNG")
    result = load_scaled_image(path, 32)
    assert result.hasAlphaChannel()
