"""
Primitives Win32 (ctypes) pour remplacer le curseur système par une image
avec un vrai canal alpha par pixel.

Repris de la logique de BuildCursorIconFromFile / MakeBlankCursor dans
"Global Macro v2.ahk", en corrigeant le bug de halo déjà rencontré côté AHK
avec l'ancienne approche color-key : le bitmap couleur passé à
CreateIconIndirect est un vrai DIB 32bpp avec un canal alpha prémultiplié
par pixel (masque AND entièrement opaque, l'alpha du bitmap couleur gère
seule la transparence) — jamais de WinSetTransColor / clé de couleur.
"""
import ctypes
from ctypes import wintypes

from PyQt6.QtGui import QImage

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

OCR_NORMAL = 32512
SPI_SETCURSORS = 0x57
BI_RGB = 0
DIB_RGB_COLORS = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.CreateIconIndirect.restype = wintypes.HICON
user32.CreateIconIndirect.argtypes = [ctypes.POINTER(_ICONINFO)]
user32.SetSystemCursor.argtypes = [wintypes.HICON, wintypes.UINT]
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]


def _build_premultiplied_dib(image: QImage) -> tuple[int, int, int]:
    """HBITMAP 32bpp top-down avec un vrai canal alpha prémultiplié par
    pixel, copié directement depuis les scanlines Qt (BGRA en mémoire sur
    little-endian, identique à l'ordre attendu par un DIB Windows 32bpp)."""
    img = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0:
        return 0, 0, 0

    bmi = _BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h  # top-down : mêmes lignes, dans le même ordre, que QImage
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = BI_RGB

    hdc = user32.GetDC(0)
    try:
        p_bits = ctypes.c_void_p()
        hbitmap = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(p_bits), None, 0)
        if not hbitmap or not p_bits.value:
            return 0, 0, 0
        stride = w * 4
        for y in range(h):
            line = img.scanLine(y)
            line.setsize(stride)
            ctypes.memmove(p_bits.value + y * stride, bytes(line), stride)
        return hbitmap, w, h
    finally:
        user32.ReleaseDC(0, hdc)


def build_cursor_hicon(image: QImage) -> int:
    """Icône/curseur avec canal alpha réel depuis une image déjà
    redimensionnée. Retourne 0 en cas d'échec."""
    hbitmap, w, h = _build_premultiplied_dib(image)
    if not hbitmap:
        return 0

    # Masque AND monochrome, entièrement opaque (0) : la transparence vient
    # uniquement de l'alpha du bitmap couleur, jamais de ce masque.
    row_bytes = ((w + 15) // 16) * 2
    mask_buf = ctypes.create_string_buffer(row_bytes * h)
    hmask = gdi32.CreateBitmap(w, h, 1, 1, mask_buf)
    if not hmask:
        gdi32.DeleteObject(hbitmap)
        return 0

    info = _ICONINFO(fIcon=False, xHotspot=w // 2, yHotspot=h // 2, hbmMask=hmask, hbmColor=hbitmap)
    hicon = user32.CreateIconIndirect(ctypes.byref(info))

    gdi32.DeleteObject(hmask)
    gdi32.DeleteObject(hbitmap)
    return hicon or 0


def make_blank_cursor() -> int:
    """Curseur 1x1 entièrement transparent, pour masquer le curseur système
    pendant que l'overlay Roblox est affiché par-dessus."""
    mask_buf = ctypes.create_string_buffer(bytes([0xFF, 0xFF, 0xFF, 0xFF]), 4)
    hmask = gdi32.CreateBitmap(1, 1, 1, 1, mask_buf)
    if not hmask:
        return 0
    info = _ICONINFO(fIcon=False, xHotspot=0, yHotspot=0, hbmMask=hmask, hbmColor=0)
    hcursor = user32.CreateIconIndirect(ctypes.byref(info))
    gdi32.DeleteObject(hmask)
    return hcursor or 0


def apply_system_cursor(hicon: int) -> bool:
    """Remplace le curseur "normal" (flèche) système par hicon. SetSystemCursor
    détruit hicon lui-même en cas de succès (ne pas le libérer après)."""
    if not hicon:
        return False
    ok = bool(user32.SetSystemCursor(hicon, OCR_NORMAL))
    if not ok:
        user32.DestroyIcon(hicon)
    return ok


def reset_system_cursors() -> None:
    """Recharge le schéma de curseurs par défaut de Windows, annulant tout
    SetSystemCursor précédent."""
    user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0)
