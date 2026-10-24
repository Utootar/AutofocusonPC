"""Win32 side via ctypes: monitors, per-monitor MRU, input guards, focus dispatch, cursor restore."""
import ctypes
import logging
import os
import queue
import threading
import time
from ctypes import wintypes as W

log = logging.getLogger("win")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")
dwmapi = ctypes.WinDLL("dwmapi")

ULONG_PTR = ctypes.c_size_t
LONG_PTR = ctypes.c_ssize_t


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT),
                ("dwFlags", W.DWORD), ("szDevice", W.WCHAR * 32)]


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.UINT), ("dwTime", W.DWORD)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", W.DWORD), ("flags", W.DWORD), ("hwndActive", W.HWND),
                ("hwndFocus", W.HWND), ("hwndCapture", W.HWND), ("hwndMenuOwner", W.HWND),
                ("hwndMoveSize", W.HWND), ("hwndCaret", W.HWND), ("rcCaret", W.RECT)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD), ("time", W.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", ULONG_PTR)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", W.DWORD), ("u", _U)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HMONITOR, W.HDC, ctypes.POINTER(W.RECT), W.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, W.HANDLE, W.DWORD, W.HWND, W.LONG, W.LONG, W.DWORD, W.DWORD)


def _sig(dll, name, res, *args):
    f = getattr(dll, name)
    f.restype, f.argtypes = res, list(args)
    return f


SetProcessDpiAwarenessContext = _sig(user32, "SetProcessDpiAwarenessContext", W.BOOL, W.HANDLE)
EnumDisplayMonitors = _sig(user32, "EnumDisplayMonitors", W.BOOL, W.HDC, ctypes.c_void_p, MONITORENUMPROC, W.LPARAM)
GetMonitorInfoW = _sig(user32, "GetMonitorInfoW", W.BOOL, W.HMONITOR, ctypes.POINTER(MONITORINFOEXW))
MonitorFromWindow = _sig(user32, "MonitorFromWindow", W.HMONITOR, W.HWND, W.DWORD)
MonitorFromPoint = _sig(user32, "MonitorFromPoint", W.HMONITOR, W.POINT, W.DWORD)
WindowFromPoint = _sig(user32, "WindowFromPoint", W.HWND, W.POINT)
GetForegroundWindow = _sig(user32, "GetForegroundWindow", W.HWND)
SetForegroundWindow = _sig(user32, "SetForegroundWindow", W.BOOL, W.HWND)
BringWindowToTop = _sig(user32, "BringWindowToTop", W.BOOL, W.HWND)
GetAncestor = _sig(user32, "GetAncestor", W.HWND, W.HWND, W.UINT)
GetWindowThreadProcessId = _sig(user32, "GetWindowThreadProcessId", W.DWORD, W.HWND, ctypes.POINTER(W.DWORD))
AttachThreadInput = _sig(user32, "AttachThreadInput", W.BOOL, W.DWORD, W.DWORD, W.BOOL)
IsWindow = _sig(user32, "IsWindow", W.BOOL, W.HWND)
IsWindowVisible = _sig(user32, "IsWindowVisible", W.BOOL, W.HWND)
IsIconic = _sig(user32, "IsIconic", W.BOOL, W.HWND)
IsHungAppWindow = _sig(user32, "IsHungAppWindow", W.BOOL, W.HWND)
GetWindowLongPtrW = _sig(user32, "GetWindowLongPtrW", LONG_PTR, W.HWND, ctypes.c_int)
GetClassNameW = _sig(user32, "GetClassNameW", ctypes.c_int, W.HWND, W.LPWSTR, ctypes.c_int)
GetWindowRect = _sig(user32, "GetWindowRect", W.BOOL, W.HWND, ctypes.POINTER(W.RECT))
EnumWindows = _sig(user32, "EnumWindows", W.BOOL, WNDENUMPROC, W.LPARAM)
GetLastInputInfo = _sig(user32, "GetLastInputInfo", W.BOOL, ctypes.POINTER(LASTINPUTINFO))
GetAsyncKeyState = _sig(user32, "GetAsyncKeyState", W.SHORT, ctypes.c_int)
GetGUIThreadInfo = _sig(user32, "GetGUIThreadInfo", W.BOOL, W.DWORD, ctypes.POINTER(GUITHREADINFO))
SendInput = _sig(user32, "SendInput", W.UINT, W.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
GetCursorPos = _sig(user32, "GetCursorPos", W.BOOL, ctypes.POINTER(W.POINT))
SetCursorPos = _sig(user32, "SetCursorPos", W.BOOL, ctypes.c_int, ctypes.c_int)
OpenInputDesktop = _sig(user32, "OpenInputDesktop", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
SwitchDesktop = _sig(user32, "SwitchDesktop", W.BOOL, W.HANDLE)
CloseDesktop = _sig(user32, "CloseDesktop", W.BOOL, W.HANDLE)
SetWinEventHook = _sig(user32, "SetWinEventHook", W.HANDLE, W.DWORD, W.DWORD, W.HMODULE, WINEVENTPROC, W.DWORD, W.DWORD, W.DWORD)
UnhookWinEvent = _sig(user32, "UnhookWinEvent", W.BOOL, W.HANDLE)
GetMessageW = _sig(user32, "GetMessageW", W.BOOL, ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT)
PeekMessageW = _sig(user32, "PeekMessageW", W.BOOL, ctypes.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT)
PostThreadMessageW = _sig(user32, "PostThreadMessageW", W.BOOL, W.DWORD, W.UINT, W.WPARAM, W.LPARAM)
GetTickCount = _sig(kernel32, "GetTickCount", W.DWORD)
GetCurrentThreadId = _sig(kernel32, "GetCurrentThreadId", W.DWORD)
GetCurrentProcess = _sig(kernel32, "GetCurrentProcess", W.HANDLE)
SetPriorityClass = _sig(kernel32, "SetPriorityClass", W.BOOL, W.HANDLE, W.DWORD)
OpenProcess = _sig(kernel32, "OpenProcess", W.HANDLE, W.DWORD, W.BOOL, W.DWORD)
QueryFullProcessImageNameW = _sig(kernel32, "QueryFullProcessImageNameW", W.BOOL, W.HANDLE, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD))
CloseHandle = _sig(kernel32, "CloseHandle", W.BOOL, W.HANDLE)
SHQueryUserNotificationState = _sig(shell32, "SHQueryUserNotificationState", ctypes.c_long, ctypes.POINTER(ctypes.c_int))
DwmGetWindowAttribute = _sig(dwmapi, "DwmGetWindowAttribute", ctypes.c_long, W.HWND, W.DWORD, ctypes.c_void_p, W.DWORD)

MONITOR_DEFAULTTONULL, MONITOR_DEFAULTTONEAREST = 0, 2
GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
DWMWA_CLOAKED = 14
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS = 0x0, 0x2
WM_QUIT = 0x0012
INPUT_KEYBOARD, KEYEVENTF_KEYUP = 1, 0x2
VK_MENU, VK_MASK = 0x12, 0xE8  # 0xE8 is unassigned: masks Alt-up so the target's menu bar stays closed
GUARD_KEYS = (0x01, 0x02, 0x04, 0x05, 0x06,  # mouse L/R/M/X1/X2 (drag in progress)
              0x10, 0x11, 0x12, 0x5B, 0x5C)  # Shift/Ctrl/Alt/LWin/RWin (chords, Alt-Tab)
GUI_BLOCK = 0x02 | 0x04 | 0x08 | 0x10  # INMOVESIZE | INMENUMODE | SYSTEMMENUMODE | POPUPMENUMODE
QUNS_BLOCK = {1, 2, 3, 4}  # NOT_PRESENT, BUSY, RUNNING_D3D_FULL_SCREEN, PRESENTATION_MODE
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_SWITCHDESKTOP = 0x0100
BELOW_NORMAL_PRIORITY_CLASS = 0x4000
SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}
BLOCKED_PROCESSES = {"startmenuexperiencehost.exe", "searchhost.exe"}
QUIET_MS = 800       # a click this recent blocks a switch; mouse input this recent keeps the cursor put
VOTE_R = 250         # px, about the measured gaze error; spacing of the window-vote grid
TYPING_HOLD_S = 3.0  # no switch this long after the last keystroke: typing pins focus to its window
# keys that count as typing: everything except mouse buttons, modifiers and our own Alt/mask injection
TYPING_VKS = [vk for vk in range(0x08, 0xFF)
              if vk not in (0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xE8)]


def init_process():
    SetProcessDpiAwarenessContext(W.HANDLE(-4))  # PER_MONITOR_AWARE_V2: physical pixels everywhere
    SetPriorityClass(GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)


def _monitor_info(hmon):
    mi = MONITORINFOEXW(cbSize=ctypes.sizeof(MONITORINFOEXW))
    if not hmon or not GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    r = mi.rcMonitor
    return mi.szDevice, (r.left, r.top, r.right, r.bottom)


def layout():
    """Sorted [[device, [l, t, r, b]], ...] for every attached monitor."""
    found = []

    def cb(hmon, _hdc, _rc, _lp):
        info = _monitor_info(hmon)
        if info:
            found.append([info[0], list(info[1])])
        return True

    EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    return sorted(found)


def cursor_pos():
    pt = W.POINT()
    GetCursorPos(ctypes.byref(pt))
    return pt


def cursor_device():
    info = _monitor_info(MonitorFromPoint(cursor_pos(), MONITOR_DEFAULTTONEAREST))
    return info[0] if info else None


def is_locked():
    h = OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not h:
        return True
    try:
        return not SwitchDesktop(h)  # fails while the secure desktop (lock/UAC) owns input
    finally:
        CloseDesktop(h)


def _process_name(hwnd):
    pid = W.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(512), W.DWORD(512)
        return os.path.basename(buf.value).lower() if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        CloseHandle(h)


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def _cloaked(hwnd):
    v = W.DWORD()
    return DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(v), ctypes.sizeof(v)) == 0 and v.value != 0


def _key_events(*keys):
    """keys: (vk, up) pairs."""
    arr = (INPUT * len(keys))()
    for i, (vk, up) in enumerate(keys):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki = KEYBDINPUT(wVk=vk, dwFlags=KEYEVENTF_KEYUP if up else 0)
    SendInput(len(keys), arr, ctypes.sizeof(INPUT))


class Win:
    """devices: [device of monitor 0, device of monitor 1], in calibration order."""

    def __init__(self, devices):
        self.devices = list(devices)
        self.mru = {}         # monitor index -> last foreground hwnd on it
        self.last_pos = {}    # monitor index -> last cursor (x, y) on it
        self.labels = queue.SimpleQueue()  # (monitor, t) of user-initiated foreground changes
        self._dispatched_at = -1e9
        self.typed_at = self.clicked_at = -1e9
        self.placed_at = None  # cursor position we set on the last switch
        self._ldown = False
        # AttachThreadInput needs a message queue on this thread; PeekMessage creates one
        PeekMessageW(ctypes.byref(W.MSG()), None, 0, 0, 0)
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        self._ready.wait(2)
        fg = GetForegroundWindow()
        if self.monitor_of(fg) is not None:
            self.mru[self.monitor_of(fg)] = fg

    def monitor_of(self, hwnd):
        if not hwnd:
            return None
        info = _monitor_info(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))
        return self.devices.index(info[0]) if info and info[0] in self.devices else None

    def fg_monitor(self):
        return self.monitor_of(GetForegroundWindow())

    def monitor_at(self, pt):
        info = _monitor_info(MonitorFromPoint(W.POINT(*pt), MONITOR_DEFAULTTONULL))
        return self.devices.index(info[0]) if info and info[0] in self.devices else None

    def poll_input(self):
        """Call every tick (polling, no input hook). Records typing; returns the cursor (x, y) if the
        left button went down since the last call, else None."""
        # GetAsyncKeyState bit 0 = pressed since the last call, so keys tapped between ticks still count
        if any(GetAsyncKeyState(vk) & 0x8001 for vk in TYPING_VKS):
            self.typed_at = time.monotonic()
        state = GetAsyncKeyState(0x01)
        down = bool(state & 0x8000)
        clicked = (down and not self._ldown) or (state & 1 and not down)
        self._ldown = down
        if not clicked:
            return None
        self.clicked_at = time.monotonic()
        pt = cursor_pos()
        return pt.x, pt.y

    # --- foreground tracking (out-of-context WinEvent: no input hook, no timeout removal) ---

    def _event_loop(self):
        def on_foreground(_hook, _event, hwnd, _obj, _child, _tid, _ms):
            hwnd = GetAncestor(hwnd, GA_ROOT) or hwnd
            mon = self.monitor_of(hwnd)
            if mon is None:
                return
            self.mru[mon] = hwnd
            if time.monotonic() - self._dispatched_at > 0.3:  # ignore changes we caused
                self.labels.put((mon, time.monotonic()))

        self._proc = WINEVENTPROC(on_foreground)  # keep a reference: ctypes callbacks must outlive the hook
        self._tid = GetCurrentThreadId()
        hook = SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None, self._proc,
                               0, 0, WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        self._ready.set()
        msg = W.MSG()
        while GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        UnhookWinEvent(hook)

    def close(self):
        PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        self._thread.join(timeout=2)

    # --- guards: polled only when a switch is about to fire ---

    def guard_block(self):
        """None if a switch may fire now, else a short reason it may not. Plain mouse movement does
        not block (the switch then leaves the cursor alone, see switch_to); clicks and typing do."""
        if time.monotonic() - self.clicked_at < QUIET_MS / 1000:
            return "click"
        if time.monotonic() - self.typed_at < TYPING_HOLD_S:
            return "typing"
        if any(GetAsyncKeyState(vk) & 0x8000 for vk in GUARD_KEYS):
            return "key-held"
        state = ctypes.c_int()
        if SHQueryUserNotificationState(ctypes.byref(state)) == 0 and state.value in QUNS_BLOCK:
            return "fullscreen"
        fg = GetForegroundWindow()
        if fg:
            gti = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
            if GetGUIThreadInfo(GetWindowThreadProcessId(fg, None), ctypes.byref(gti)) and gti.flags & GUI_BLOCK:
                return "menu-or-drag"
            if _process_name(fg) in BLOCKED_PROCESSES:
                return "start-or-search"
        return None

    # --- target selection ---

    def _activatable(self, hwnd, mon):
        return (IsWindow(hwnd) and IsWindowVisible(hwnd) and not IsIconic(hwnd)
                and not GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
                and _class_name(hwnd) not in SHELL_CLASSES
                and not _cloaked(hwnd) and not IsHungAppWindow(hwnd)
                and self.monitor_of(hwnd) == mon)

    def pick_target(self, mon):
        hwnd = self.mru.get(mon)
        if hwnd and self._activatable(hwnd, mon):
            return hwnd
        found = []

        def cb(h, _lp):  # EnumWindows walks top-level windows in z-order
            if self._activatable(h, mon):
                found.append(h)
                return False
            return True

        EnumWindows(WNDENUMPROC(cb), 0)
        return found[0] if found else None

    # --- dispatch ---

    def _activate(self, hwnd):
        # Alt press re-enables SetForegroundWindow (documented under LockSetForegroundWindow)
        _key_events((VK_MENU, False))
        SetForegroundWindow(hwnd)
        _key_events((VK_MASK, False), (VK_MASK, True), (VK_MENU, True))
        time.sleep(0.05)
        if GetForegroundWindow() == hwnd:
            return True
        fg = GetForegroundWindow()
        if not fg or IsHungAppWindow(fg):
            return False  # attaching to a hung thread would hang us too
        fg_tid, me = GetWindowThreadProcessId(fg, None), GetCurrentThreadId()
        if not AttachThreadInput(me, fg_tid, True):
            return False
        try:
            BringWindowToTop(hwnd)
            SetForegroundWindow(hwnd)
        finally:
            AttachThreadInput(me, fg_tid, False)
        time.sleep(0.05)
        return GetForegroundWindow() == hwnd

    def track_cursor(self):
        pt = cursor_pos()
        info = _monitor_info(MonitorFromPoint(pt, MONITOR_DEFAULTTONULL))
        if info and info[0] in self.devices:
            self.last_pos[self.devices.index(info[0])] = (pt.x, pt.y)

    def _rect(self, mon):
        return next((r for d, r in layout() if d == self.devices[mon]), None)

    def _root_at(self, pt):
        h = WindowFromPoint(W.POINT(*pt))
        return GetAncestor(h, GA_ROOT) if h else None

    def _window_near(self, mon, pt):
        """The window the user most likely looks at, and a cursor spot on it. The gaze estimate is
        ~VOTE_R px off, so a 3x3 grid around it votes (center counts most); WindowFromPoint already
        accounts for windows covering each other. Returns (hwnd, (x, y)) or (None, None)."""
        votes = {}
        for dx in (-VOTE_R, 0, VOTE_R):
            for dy in (-VOTE_R, 0, VOTE_R):
                q = (pt[0] + dx, pt[1] + dy)
                h = self._root_at(q) if self.monitor_at(q) == mon else None
                if h and self._activatable(h, mon):
                    votes.setdefault(h, []).append((q, 4 >> (bool(dx) + bool(dy))))  # 4 center, 2 edge, 1 corner
        if not votes:
            return None, None
        h = max(votes, key=lambda k: sum(w for _, w in votes[k]))
        hits = votes[h]
        tot = sum(w for _, w in hits)
        spot = (sum(q[0] * w for q, w in hits) // tot, sum(q[1] * w for q, w in hits) // tot)
        if self._root_at(spot) != h:  # weighted mean fell on another window: use the hit nearest the gaze
            spot = min((q for q, _ in hits), key=lambda q: (q[0] - pt[0]) ** 2 + (q[1] - pt[1]) ** 2)
        return h, spot

    def _restore_cursor(self, mon, hwnd, gaze=None):
        pt = cursor_pos()
        info = _monitor_info(MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST))
        if info and info[0] == self.devices[mon]:
            return  # cursor already on the target monitor
        if gaze:
            SetCursorPos(*gaze)
            self.placed_at = gaze
            return
        rect = self._rect(mon)
        pos = self.last_pos.get(mon)
        if pos is None or rect is None or not (rect[0] <= pos[0] < rect[2] and rect[1] <= pos[1] < rect[3]):
            r = W.RECT()
            GetWindowRect(hwnd, ctypes.byref(r))
            pos = ((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        SetCursorPos(*pos)

    def switch_to(self, mon, gaze=None):
        """gaze: estimated (x, y) the user looks at; picks the window there and puts the cursor on it."""
        rect = self._rect(mon) if gaze is not None else None
        gaze = (int(min(max(gaze[0], rect[0]), rect[2] - 1)),
                int(min(max(gaze[1], rect[1]), rect[3] - 1))) if rect else None
        hwnd, gaze = self._window_near(mon, gaze) if gaze else (None, None)
        hwnd = hwnd or self.pick_target(mon)
        if hwnd is None:
            log.info("no activatable window on monitor %d", mon)
            return False
        self._dispatched_at = time.monotonic()
        # read before _activate: its injected Alt resets the idle clock
        lii = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
        mouse_busy = GetLastInputInfo(ctypes.byref(lii)) and (GetTickCount() - lii.dwTime) & 0xFFFFFFFF < QUIET_MS
        if not self._activate(hwnd):
            # expected when the foreground is elevated (UIPI drops our SendInput) or hung
            log.warning("focus switch to %s (%s) failed", _class_name(hwnd), _process_name(hwnd))
            return False
        if not mouse_busy:  # the user is moving the mouse: leave it in their hand
            self._restore_cursor(mon, hwnd, gaze)
        return True
