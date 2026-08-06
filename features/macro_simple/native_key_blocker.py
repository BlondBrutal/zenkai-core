"""
Blocage SÉLECTIF d'une touche clavier ou d'un bouton de souris précis, au
niveau du système (Windows), pendant qu'une macro Simple est active : la
touche de déclenchement ("Activer") ne doit plus atteindre le jeu/l'OS tant
que la macro tourne, mais TOUT le reste du clavier/de la souris doit rester
parfaitement normal. `pynput` (déjà utilisé partout ailleurs dans l'app,
voir hotkey_listener.py avant ce module) ne sait supprimer que la TOTALITÉ
du clavier ou de la souris à la fois (`suppress=True` sur tout le Listener,
aucune option "cette touche seulement") — inutilisable ici, ça bloquerait
aussi la saisie/les clics normaux de l'utilisateur pendant toute la durée où
la macro est armée.

Implémenté via un hook Windows bas niveau (SetWindowsHookEx WH_KEYBOARD_LL /
WH_MOUSE_LL, ctypes) : le callback compare chaque évènement reçu à la touche
configurée — s'il correspond, il n'appelle PAS CallNextHookEx (l'évènement
s'arrête donc là, jamais transmis au jeu/à l'OS) ; sinon, il appelle
CallNextHookEx normalement (transmission inchangée, latence ajoutée
négligeable). Windows exige que le thread qui installe un hook bas niveau
fasse tourner une boucle de messages native pour recevoir les appels du
hook — d'où le thread dédié ci-dessous (GetMessage/DispatchMessage), séparé
du thread Qt.

Note de robustesse : Windows retire automatiquement un hook bas niveau dont
le callback ne répond pas assez vite (LowLevelHooksTimeout, ~300ms par
défaut) — un bug dans ce module ne peut donc pas bloquer durablement le
clavier/la souris de l'utilisateur : au pire ce hook précis est débranché
par l'OS (la touche redevient alors libre, mais la détection du
déclencheur s'arrête aussi avec).
"""
import ctypes
import ctypes.wintypes as wintypes
import threading

from features.macro_pixel.key_names import is_mouse_button_name

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
_KEY_DOWN_MESSAGES = (WM_KEYDOWN, WM_SYSKEYDOWN)
_KEY_UP_MESSAGES = (WM_KEYUP, WM_SYSKEYUP)

# Marque un évènement clavier/souris comme SYNTHÉTISÉ (injecté via SendInput
# — c'est exactement comme ça que pydirectinput/pynput envoient les touches
# rejouées par MacroPlayerThread, voir player.py) plutôt qu'une vraie touche
# physique. Sans cette distinction, ce hook bloquait AUSSI les propres
# touches simulées de la macro dès qu'elles correspondaient à la touche de
# déclenchement (ex : la touche de déclenchement réutilisée comme première
# action de la séquence ne partait jamais) — un évènement injecté doit
# toujours passer inchangé (jamais traité comme un appui du déclencheur,
# jamais supprimé), seul un VRAI appui physique doit être intercepté ici.
LLKHF_LOWER_IL_INJECTED = 0x00000002
LLKHF_INJECTED = 0x00000010
LLMHF_LOWER_IL_INJECTED = 0x00000002
LLMHF_INJECTED = 0x00000001

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

WM_QUIT = 0x0012

_MOUSE_DOWN_TO_NAME = {
    WM_LBUTTONDOWN: "mouse_left",
    WM_RBUTTONDOWN: "mouse_right",
    WM_MBUTTONDOWN: "mouse_middle",
}
_MOUSE_UP_TO_NAME = {
    WM_LBUTTONUP: "mouse_left",
    WM_RBUTTONUP: "mouse_right",
    WM_MBUTTONUP: "mouse_middle",
}

# Table VK Windows pour le même vocabulaire de noms de touches que
# features/macro_pixel/key_names.py (utilisé partout ailleurs dans l'app pour
# capturer/afficher une touche de macro) : lettres/chiffres via leur code
# ASCII majuscule (les VK Windows de 'A'-'Z'/'0'-'9' sont, par conception
# Microsoft, identiques à l'ASCII majuscule correspondant), le reste listé
# explicitement ci-dessous.
_NAMED_VK = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "backspace": 0x08,
    "delete": 0x2E, "esc": 0x1B, "up": 0x26, "down": 0x28, "left": 0x25,
    "right": 0x27, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
    "pause": 0x13, "printscreen": 0x2C, "shift": 0x10, "ctrl": 0x11,
    "alt": 0x12, "win": 0x5B, "apps": 0x5D,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},  # VK_F1=0x70 .. VK_F12=0x7B
}


def key_name_to_vk(name: str) -> int | None:
    if name in _NAMED_VK:
        return _NAMED_VK[name]
    if len(name) == 1:
        ch = name.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)
    return None


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_LowLevelProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

# Prototypes explicites (argtypes/restype) : sans ça, ctypes infère parfois
# mal le type d'un argument WINFUNCTYPE passé à une fonction Win32 (constaté
# ici : SetWindowsHookExW refusait le callback avec une ArgumentError malgré
# un type identique, résolu uniquement en déclarant le prototype exact).
#
# `ctypes.WinDLL(...)` (PAS `ctypes.windll.user32`/`ctypes.windll.kernel32`) :
# `ctypes.windll.user32` est un objet mis en cache par ctypes, PARTAGÉ par
# TOUT le processus — y compris par `pynput` lui-même, qui utilise les mêmes
# fonctions (SetWindowsHookExW/CallNextHookEx/GetMessageW/...) en interne
# pour ses propres écouteurs clavier/souris globaux. Régression réelle
# constatée : simplement IMPORTER ce module (donc exécuter les lignes
# .argtypes ci-dessous sur l'objet PARTAGÉ) écrasait le prototype que pynput
# avait déjà déclaré pour SetWindowsHookExW avec le NÔTRE (type de callback
# différent : notre _LowLevelProc vs le _HOOKPROC interne de pynput) — tout
# Listener pynput créé APRÈS cet import échouait alors à installer son hook
# (TypeError avalée silencieusement par un `except: pass` interne à pynput,
# voir pynput/_util/win32.py ListenerMixin._run), laissant le Listener
# tourner en apparence ("thread démarré") mais sans jamais rien capturer —
# exactement le symptôme observé : plus aucune capture de clic souris
# (ActionCaptureWidget) nulle part dans l'app dès que cette page était
# ouverte, avec pour conséquence visible que les champs X/Y semblaient
# "bloqués" (une capture qui ne se termine jamais laisse la ligne sur
# action="key", donc X/Y restent désactivés — voir _update_row_enabled_state
# dans macro_simple_tab.py). `ctypes.WinDLL(...)` crée un objet DLL
# indépendant (vérifié : `ctypes.WinDLL('user32') is not ctypes.windll.user32`)
# dont les prototypes de fonctions ne sont donc visibles que par CE module.
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _LowLevelProc, wintypes.HINSTANCE, wintypes.DWORD]
_user32.SetWindowsHookExW.restype = wintypes.HHOOK
_user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
_user32.CallNextHookEx.restype = ctypes.c_long
_user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
_user32.GetMessageW.restype = ctypes.c_int
_user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.TranslateMessage.restype = wintypes.BOOL
_user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
_user32.DispatchMessageW.restype = ctypes.c_long
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
_user32.PostThreadMessageW.restype = wintypes.BOOL
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetCurrentThreadId.argtypes = []
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class NativeKeyBlocker:
    """Un seul point d'entrée : construire avec le nom de touche/bouton (même
    vocabulaire que le reste de l'app — voir key_names.py), `on_press`/
    `on_release` (appelés depuis le thread du hook, JAMAIS le thread GUI —
    à l'appelant de ne faire qu'un `emit()` dedans, jamais toucher un widget
    directement, même principe que les callbacks pynput ailleurs dans
    l'app), puis start()/stop(). N'installe qu'UN hook, du type qui
    correspond réellement à `key_name` (clavier OU souris, jamais les deux)."""

    def __init__(self, key_name: str, on_press, on_release):
        self._key_name = key_name
        self._on_press = on_press
        self._on_release = on_release
        self._is_mouse = is_mouse_button_name(key_name)
        self._vk = None if self._is_mouse else key_name_to_vk(key_name)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook_handle = None
        self._ready = threading.Event()
        # Empêche le garbage collector de libérer le callback ctypes tant
        # que le hook est actif : SetWindowsHookEx ne garde qu'un pointeur
        # C brut vers ce callback, pas de référence Python — sans ça,
        # comportement indéfini (crash probable) au premier évènement une
        # fois l'objet WINFUNCTYPE ramassé par le GC.
        self._callback_ref = None

    def start(self) -> None:
        if self._thread is not None:
            return
        if not self._is_mouse and self._vk is None:
            # Touche non reconnue (ne devrait pas arriver : même vocabulaire
            # que la capture UI) : pas de blocage possible, mais ne doit
            # jamais empêcher le reste de l'app de fonctionner.
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="ZenkaiKeyBlocker", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)

    def stop(self) -> None:
        if self._thread is None:
            return
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0
        self._callback_ref = None

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        h_mod = _kernel32.GetModuleHandleW(None)

        if self._is_mouse:
            proc = _LowLevelProc(self._mouse_proc)
            hook_type = WH_MOUSE_LL
        else:
            proc = _LowLevelProc(self._keyboard_proc)
            hook_type = WH_KEYBOARD_LL
        self._callback_ref = proc  # garde une référence vivante (voir __init__)

        hook = _user32.SetWindowsHookExW(hook_type, proc, h_mod, 0)
        self._hook_handle = hook
        self._ready.set()
        if not hook:
            return
        try:
            msg = wintypes.MSG()
            # GetMessageW bloque jusqu'au prochain message (WM_QUIT posté
            # par stop(), ou tout autre message adressé à ce thread) :
            # boucle native exigée par Windows pour qu'un hook bas niveau
            # reçoive ses appels (voir docstring du module).
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            _user32.UnhookWindowsHookEx(hook)
            self._hook_handle = None

    def _keyboard_proc(self, n_code, w_param, l_param):
        if n_code >= 0:
            info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            is_injected = bool(info.flags & (LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED))
            if not is_injected and info.vkCode == self._vk:
                if w_param in _KEY_DOWN_MESSAGES:
                    self._on_press()
                elif w_param in _KEY_UP_MESSAGES:
                    self._on_release()
                return 1  # supprimé : jamais transmis au reste du système
        return _user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

    def _mouse_proc(self, n_code, w_param, l_param):
        if n_code >= 0:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            is_injected = bool(info.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED))
            name = pressed = None
            if w_param in _MOUSE_DOWN_TO_NAME:
                name, pressed = _MOUSE_DOWN_TO_NAME[w_param], True
            elif w_param in _MOUSE_UP_TO_NAME:
                name, pressed = _MOUSE_UP_TO_NAME[w_param], False
            elif w_param in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                x_button = (info.mouseData >> 16) & 0xFFFF
                name = "mouse_x1" if x_button == XBUTTON1 else "mouse_x2"
                pressed = w_param == WM_XBUTTONDOWN
            if not is_injected and name == self._key_name:
                if pressed:
                    self._on_press()
                else:
                    self._on_release()
                return 1  # supprimé : jamais transmis au reste du système
        return _user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)
