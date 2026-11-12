#!/usr/bin/env python3
"""Window for mc-perf-mods drawn with HTML/CSS (pywebview + Edge WebView2, no local server).
Run: pythonw perf_web.py   (or double-click "เปิดโปรแกรม.bat")
Falls back to the plain Tk window (perf_gui.py) when pywebview is not installed.

Background: put bg.gif / bg.webp / bg.png / bg.jpg / bg.mp4 / bg.webm in the mc-perf-mods folder to use
your own (animated) picture; without one the window draws its own moving purple-pink background."""
import base64
import ctypes
import json
import mimetypes
import os
import sys
import threading
import webbrowser

FROZEN = getattr(sys, "frozen", False)            # running as the PyInstaller exe
HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(getattr(sys, "_MEIPASS", HERE), "ui")
# bg.* sits next to the exe, or next to เปิดโปรแกรม.bat when run from source
ROOT = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(HERE)
sys.path.insert(0, HERE)
import perf  # noqa: E402

# where launchers keep instances; the first one that exists opens in the folder picker
INSTANCE_ROOTS = [
    r"D:\game2\Instances",
    os.path.expanduser(r"~\curseforge\minecraft\Instances"),
    os.path.join(os.environ.get("APPDATA", ""), "PrismLauncher", "instances"),
    os.path.join(os.environ.get("APPDATA", ""), ".minecraft"),
]
DEFAULT_ROOT = next((d for d in INSTANCE_ROOTS if os.path.isdir(d)), os.path.expanduser("~"))
BG_EXTS = (".gif", ".webp", ".png", ".jpg", ".jpeg", ".mp4", ".webm")
BG_NAMES = tuple("bg" + e for e in BG_EXTS)
BG_MAX = 40 * 1024 * 1024
# background chosen inside the app + its settings live here (writable even when the exe folder is not)
CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "mc-perf-mods")
CONFIG_FILE = os.path.join(CONFIG_DIR, "settings.json")


def load_settings():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def find_background():
    """Picked in the app (CONFIG_DIR) first, then a bg.* placed next to the exe / bat."""
    for folder in (CONFIG_DIR, ROOT):
        for name in BG_NAMES:
            f = os.path.join(folder, name)
            if os.path.isfile(f) and os.path.getsize(f) <= BG_MAX:
                return f
    return None


def background_payload(f):
    if not f:
        return None
    mime = mimetypes.guess_type(f)[0] or "image/gif"
    name = os.path.basename(f)
    if os.path.dirname(f) == CONFIG_DIR:            # copy made by the picker: show the file the user chose
        name = load_settings().get("bg_name") or name
    with open(f, "rb") as fh:
        return {"kind": "video" if mime.startswith("video") else "image", "name": name,
                "src": "data:%s;base64,%s" % (mime, base64.b64encode(fh.read()).decode())}


class Api:
    """Methods JavaScript calls as window.pywebview.api.<name>(...). Each returns JSON-able data.
    Attributes start with _ so pywebview does not expose them."""

    def __init__(self):
        self._window = None
        self._info = None
        self._plan = []
        self._inst = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- helpers
    def _log(self, msg):
        if self._window:
            self._window.evaluate_js("window.onLog && window.onLog(%s)" % json.dumps(msg))

    @staticmethod
    def _clean(path):
        return (path or "").strip().strip('"')

    # ---------------------------------------------------------------- calls
    def init(self):
        bg = background_payload(find_background())
        dim = load_settings().get("dim", 0.6)
        # a folder dropped on the exe (or given on the command line) is checked right away
        given = next((a for a in sys.argv[1:] if not a.startswith("--") and os.path.isdir(a)), None)
        base = {"bg": bg, "dim": dim, "version": perf.VERSION}
        if given:
            return dict(base, path=os.path.normpath(given), auto=True)
        default = os.path.join(DEFAULT_ROOT, "__")
        return dict(base, path=default if os.path.isdir(default) else "", auto=False)

    # ---------------------------------------------------------------- background
    def pick_background(self):
        """Open a file picker; copy the chosen picture/video into CONFIG_DIR as bg.<ext>."""
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
        if kind is None:
            kind = webview.OPEN_DIALOG
        # pywebview only accepts [\w ] in the label - Thai vowel/tone marks are not \w, so keep it English
        types = ("Images and videos (%s)" % ";".join("*" + e for e in BG_EXTS),)
        try:
            res = self._window.create_file_dialog(kind, file_types=types)
        except Exception as ex:
            return {"error": "เปิดหน้าต่างเลือกไฟล์ไม่ได้: %s" % ex}
        if not res:
            return None
        src = res[0] if isinstance(res, (list, tuple)) else res
        ext = os.path.splitext(src)[1].lower()
        if ext not in BG_EXTS:
            return {"error": "ใช้ได้เฉพาะไฟล์ " + " ".join(BG_EXTS)}
        if os.path.getsize(src) > BG_MAX:
            return {"error": "ไฟล์ใหญ่เกิน 40 MB ลองใช้ไฟล์ที่เล็กลง"}
        os.makedirs(CONFIG_DIR, exist_ok=True)
        dst = os.path.join(CONFIG_DIR, "bg" + ext)
        tmp = dst + ".tmp"
        with open(src, "rb") as a, open(tmp, "wb") as b:
            b.write(a.read())
        for name in BG_NAMES:                       # keep only the new one
            old = os.path.join(CONFIG_DIR, name)
            if old != dst and os.path.exists(old):
                os.remove(old)
        os.replace(tmp, dst)
        data = load_settings()
        data["bg_name"] = os.path.basename(src)
        save_settings(data)
        return {"bg": background_payload(dst)}

    def reset_background(self):
        """Forget the picture chosen in the app (a bg.* next to the exe, if any, shows again)."""
        for name in BG_NAMES:
            f = os.path.join(CONFIG_DIR, name)
            if os.path.exists(f):
                os.remove(f)
        return {"bg": background_payload(find_background())}

    def set_dim(self, value):
        try:
            value = min(0.9, max(0.0, float(value)))
        except (TypeError, ValueError):
            return
        data = load_settings()
        data["dim"] = round(value, 2)
        save_settings(data)

    def browse(self):
        kind = getattr(getattr(__import__("webview"), "FileDialog", None), "FOLDER", None)
        if kind is None:
            kind = __import__("webview").FOLDER_DIALOG
        res = self._window.create_file_dialog(kind, directory=DEFAULT_ROOT if os.path.isdir(DEFAULT_ROOT) else "")
        return os.path.normpath(res[0]) if res else None

    def check(self, path):
        inst = self._clean(path)
        if not os.path.isdir(inst):
            return {"error": "ไม่พบโฟลเดอร์นี้:\n%s" % inst}
        info = perf.detect(inst)
        if not info["mc"] or not info["loader"]:
            return {"error": "ไม่พบไฟล์ข้อมูลม็อดแพ็ก (minecraftinstance.json ของ CurseForge หรือ mmc-pack.json ของ Prism)\n"
                             "กรุณาเลือกโฟลเดอร์ม็อดแพ็กที่มีโฟลเดอร์ mods อยู่ข้างใน"}
        if info["loader"] not in perf.SETS:
            return {"error": "ยังไม่รองรับ loader %s" % info["loader"]}
        try:
            plan, skipped = perf.resolve(info, True, True)
        except Exception as ex:
            return {"error": "เชื่อมต่อ Modrinth ไม่ได้: %s" % ex}
        with self._lock:
            self._info, self._plan, self._inst = info, plan, os.path.normcase(os.path.abspath(inst))
        return {"info": {"mc": info["mc"], "loader": info["loader"], "mods_dir": info["mods_dir"]},
                "plan": plan, "skipped": skipped, "groups": perf.QOL_GROUPS, "qol": perf.QOL,
                "desc": perf.DESC, "what": perf.WHAT}

    def install(self, path, slugs):
        inst = self._clean(path)
        with self._lock:
            info, plan, checked = self._info, self._plan, self._inst
        chosen = [p for p in plan if p["slug"] in set(slugs or [])]
        if not info or not chosen:
            return {"error": "ยังไม่ได้เลือกม็อด"}
        if os.path.normcase(os.path.abspath(inst)) != checked:   # path edited after the check
            return {"error": "ที่อยู่ม็อดแพ็กถูกแก้หลังจากกดตรวจ\nกรุณากด ตรวจม็อดแพ็ก อีกครั้งก่อนติดตั้ง"}
        try:
            tag, added = perf.install_plan(info, chosen, inst, self._log)
        except Exception as ex:
            return {"error": str(ex)}
        return {"tag": tag, "added": len(added)}

    def installs(self, path):
        out = []
        for f in reversed(perf.installs(self._clean(path))):
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            out.append({"name": os.path.basename(f)[:-5], "mc": d.get("mc"), "loader": d.get("loader"),
                        "files": [x.get("title") or x["slug"] for x in d.get("added", [])]})
        return out

    def restore(self, path, name):
        try:
            r = perf.restore_install(self._clean(path), name, self._log)
        except Exception as ex:
            return {"error": str(ex)}
        return {"ok": not r["kept"], "kept": r["kept"], "removed": len(r["removed"])}

    def open_url(self, url):
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)


def dark_titlebar(window):
    try:                                # Windows 10 1809+/11
        hwnd = window.native.Handle.ToInt32()
        val = ctypes.c_int(1)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def has_webview2():
    """Edge WebView2 Runtime is on every Windows 11 and on updated Windows 10; very old Windows 10 may lack it."""
    import winreg
    key = r"SOFTWARE\{}Microsoft\EdgeUpdate\Clients\{{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}}"
    for hive, wow in ((winreg.HKEY_LOCAL_MACHINE, "WOW6432Node\\"), (winreg.HKEY_LOCAL_MACHINE, ""),
                      (winreg.HKEY_CURRENT_USER, "")):
        try:
            with winreg.OpenKey(hive, key.format(wow)) as k:
                if winreg.QueryValueEx(k, "pv")[0] not in ("", "0.0.0.0"):
                    return True
        except OSError:
            pass
    return False


def plain_window():
    import perf_gui                     # Tk window: works everywhere, no extra install
    perf_gui.App().mainloop()


def main():
    try:
        import webview
    except ImportError:
        return plain_window()
    if not has_webview2():
        return plain_window()
    with open(os.path.join(UI_DIR, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    api = Api()
    api._window = webview.create_window("ลงม็อดเพิ่มความลื่น", html=html, js_api=api, width=1180, height=820,
                                        min_size=(900, 620), background_color="#120a1f")
    webview.start(dark_titlebar, api._window, gui="edgechromium", debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
