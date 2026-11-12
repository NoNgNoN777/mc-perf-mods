#!/usr/bin/env python3
"""Window for mc-perf-mods: pick an instance folder, tick the mods you want, install.
Run: python perf_gui.py   (or double-click "เปิดโปรแกรม.bat" in the skill folder)"""
import base64
import ctypes
import io
import json
import os
import queue
import sys
import threading
import tkinter as tk
import urllib.request
import webbrowser
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf  # noqa: E402

try:                                   # optional: decodes the WebP icons Modrinth serves
    from PIL import Image, ImageTk
except Exception:
    Image = ImageTk = None

FONT = "Leelawadee UI"
INSTANCE_ROOTS = [
    r"D:\game2\Instances",
    os.path.expanduser(r"~\curseforge\minecraft\Instances"),
    os.path.join(os.environ.get("APPDATA", ""), "PrismLauncher", "instances"),
]
DEFAULT_ROOT = next((d for d in INSTANCE_ROOTS if os.path.isdir(d)), os.path.expanduser("~"))
# dark launcher style (Modrinth App-like): near-black background, raised cards, green accent
C = {
    "bg": "#16181c", "panel": "#1c1f24", "card": "#23262c", "hover": "#2b2f36", "line": "#30343c",
    "field": "#2b2f36", "text": "#e8eaed", "muted": "#9aa1ab", "dim": "#6b727c",
    "accent": "#1bd96a", "accent_hover": "#3fe486", "on_accent": "#0d1410",
    "link": "#5aa9ff", "warn": "#ffb547", "danger": "#ff6b6b",
    "pill": "#30353d", "pill_warn": "#4a3a1c", "pill_ok": "#173a26",
}
# who needs the mod when friends join through Essential (same labels as the main window)
SIDE_PILL = {
    "both": ("ทุกคนต้องลง", "#4a1f36", "#ff9fd0"),
    "server": ("เฉพาะคนเปิดโลก", "#4a3a1c", "#ffb547"),
    "client": ("เฉพาะเครื่องตัวเอง", "#173a26", "#8ee6b8"),
    "either": ("ลงฝั่งเดียวก็ได้", "#173a26", "#8ee6b8"),
    "unknown": ("ไม่ระบุฝั่ง", "#30353d", "#9aa1ab"),
}
CHECK = 24                             # checkbox size in px


def fmt_downloads(n):
    if not n:
        return ""
    if n >= 1_000_000:
        return "%dM" % (n // 1_000_000)
    if n >= 1_000:
        return "%dK" % (n // 1_000)
    return str(n)


def rounded(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class CheckBox(tk.Canvas):
    """Large drawn checkbox: green filled when on; 'auto' rows are drawn dimmed (follow other mods)."""

    def __init__(self, parent, var, bg, auto=False):
        super().__init__(parent, width=CHECK + 4, height=CHECK + 4, bg=bg, highlightthickness=0, bd=0,
                         cursor="arrow" if auto else "hand2")
        self.var, self.auto = var, auto
        var.trace_add("write", lambda *_a: self.draw())
        self.draw()

    def draw(self):
        self.delete("all")
        on, s = self.var.get(), CHECK
        if on:
            fill = C["accent"] if not self.auto else "#1f7a47"
            rounded(self, 2, 2, s + 2, s + 2, 7, fill=fill, outline=fill)
            self.create_line(7, s / 2 + 2, s / 2, s - 3, s - 3, 8, fill=C["on_accent"], width=3,
                             capstyle="round", joinstyle="round")
        else:
            rounded(self, 2, 2, s + 2, s + 2, 7, fill=C["field"], outline=C["dim"], width=2)


class Section:
    """Collapsible block: clickable header with a tick counter, and a body frame for rows."""

    def __init__(self, app, parent, title, open_=True, level=0, hint=""):
        self.app, self.title, self.rows, self.children, self.level = app, title, [], [], level
        self.frame = tk.Frame(parent, bg=C["bg"])
        self.pack_opts = {"pady": (14 if level == 0 else 6, 0), "padx": (0 if level == 0 else 18, 0)}
        self.frame.pack(fill="x", **self.pack_opts)
        self.head = tk.Frame(self.frame, bg=C["bg"], cursor="hand2")
        self.head.pack(fill="x")
        size = 13 if level == 0 else 11
        self.arrow = tk.Label(self.head, bg=C["bg"], fg=C["muted"], font=(FONT, size - 1), width=2)
        self.arrow.pack(side="left")
        self.label = tk.Label(self.head, text=title, bg=C["bg"], fg=C["text"], font=(FONT, size, "bold"))
        self.label.pack(side="left")
        self.count = tk.Label(self.head, bg=C["pill"], fg=C["muted"], font=(FONT, 9), padx=8)
        self.count.pack(side="left", padx=10)
        if hint:
            tk.Label(self.head, text=hint, bg=C["bg"], fg=C["dim"], font=(FONT, 9)).pack(side="left")
        self.tools = tk.Frame(self.head, bg=C["bg"])
        self.tools.pack(side="right", padx=8)
        self.body = tk.Frame(self.frame, bg=C["bg"])
        for w in (self.head, self.arrow, self.label, self.count):
            w.bind("<Button-1>", lambda _e: self.toggle())
        self.open = not open_
        self.toggle()

    def add_tick_buttons(self):
        for text, val in (("เลือกทั้งหมด", True), ("ไม่เลือกทั้งหมด", False)):
            b = tk.Label(self.tools, text=text, bg=C["bg"], fg=C["link"], cursor="hand2", font=(FONT, 9))
            b.pack(side="left", padx=6)
            b.bind("<Button-1>", lambda _e, v=val: self.app.tick_section(self, v))

    def all_rows(self):
        out = list(self.rows)
        for child in self.children:
            out += child.all_rows()
        return out

    def toggle(self):
        self.open = not self.open
        self.arrow.configure(text="▾" if self.open else "▸")
        if self.open:
            self.body.pack(fill="x", pady=(6, 0))
        else:
            self.body.pack_forget()

    def refresh_count(self):
        rows = [r for r in self.all_rows()]
        if not rows:
            self.count.configure(text="")
            return
        tickable = [r for r in rows if r.var is not None]
        if tickable:
            n = sum(1 for r in tickable if r.var.get())
            self.count.configure(text="%d / %d" % (n, len(tickable)),
                                 bg=C["pill_ok"] if n else C["pill"], fg=C["accent"] if n else C["muted"])
        else:
            self.count.configure(text="%d รายการ" % len(rows))


class Row:
    def __init__(self, app, section, p=None, ticked=False, auto=False, note=None, slug=None):
        self.app, self.p, self.var, self.auto, self.section = app, p, None, auto, section
        self.slug = p["slug"] if p else slug
        self.search_text = " ".join(filter(None, [self.slug, p and p.get("title"), p and perf.DESC.get(self.slug), note])).lower()
        self.frame = tk.Frame(section.body, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        self.pack_opts = {"fill": "x", "padx": (22, 6), "pady": 3}
        self.frame.pack(**self.pack_opts)
        self.links = []
        if p:
            self.var = tk.BooleanVar(value=ticked)
            self.check = CheckBox(self.frame, self.var, C["card"], auto=auto)
            self.check.pack(side="left", padx=(12, 4), pady=12)
        self.icon = tk.Label(self.frame, text=((p.get("title") if p else slug) or "?")[:2].upper(), width=4, height=2,
                             bg=C["field"], fg=C["muted"], font=(FONT, 9, "bold"))
        self.icon.pack(side="left", padx=(8, 10), pady=10)
        mid = tk.Frame(self.frame, bg=C["card"])
        mid.pack(side="left", fill="x", expand=True, pady=8)
        top = tk.Frame(mid, bg=C["card"])
        top.pack(fill="x")
        title = (p.get("title") if p else slug) or "?"
        tk.Label(top, text=title, bg=C["card"], fg=C["text"], font=(FONT, 11, "bold")).pack(side="left")
        if p:
            tk.Label(top, text="  " + p["version"], bg=C["card"], fg=C["dim"], font=(FONT, 9)).pack(side="left")
            if p["type"] != "release":
                self.pill(top, p["type"], C["pill_warn"], C["warn"])
            if auto:
                self.pill(top, "เลือกให้อัตโนมัติ", C["pill"], C["muted"])
            label, bg, fg = SIDE_PILL.get(p.get("side"), SIDE_PILL["unknown"])
            self.pill(top, label, bg, fg)
            desc = perf.DESC.get(self.slug) or perf.WHAT.get(p["role"], "ม็อดเสริมที่ม็อดอื่นต้องใช้")
        else:
            desc = note
        tk.Label(mid, text=desc, bg=C["card"], fg=C["muted"], font=(FONT, 9), anchor="w").pack(fill="x")
        self.rel = tk.Label(mid, text="", bg=C["card"], fg=C["dim"], font=(FONT, 9), anchor="w", justify="left")
        if p:
            right = tk.Frame(self.frame, bg=C["card"])
            right.pack(side="right", padx=12)
            dl = fmt_downloads(p.get("downloads"))
            if dl:
                tk.Label(right, text="⬇ " + dl, bg=C["card"], fg=C["dim"], font=(FONT, 9)).pack(side="left", padx=8)
            for label, url in (("Modrinth", p.get("page")), ("CurseForge", p.get("curseforge"))):
                if url:
                    link = tk.Label(right, text=label, bg=C["card"], fg=C["link"], cursor="hand2", font=(FONT, 9))
                    link.pack(side="left", padx=5)
                    link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
                    link.bind("<Enter>", lambda _e, w=link: w.configure(font=(FONT, 9, "underline")))
                    link.bind("<Leave>", lambda _e, w=link: w.configure(font=(FONT, 9)))
                    self.links.append(link)
            # whole card is the click target (big and easy), except the links
            for w in self.clickables(self.frame):
                w.bind("<Button-1>", lambda _e: app.toggle(self), add="+")
                if not auto:
                    w.configure(cursor="hand2")
        for w in self.clickables(self.frame) + self.links:
            w.bind("<Enter>", lambda _e: self.hover(True), add="+")
            w.bind("<Leave>", lambda _e: self.hover(False), add="+")
        section.rows.append(self)

    def pill(self, parent, text, bg, fg):
        tk.Label(parent, text=text, bg=bg, fg=fg, font=(FONT, 8, "bold"), padx=7).pack(side="left", padx=(8, 0))

    def clickables(self, w):
        out = [] if w in self.links else [w]
        for ch in w.winfo_children():
            out += self.clickables(ch)
        return out

    def hover(self, on):
        bg = C["hover"] if on else C["card"]
        for w in self.clickables(self.frame) + self.links:
            if w is self.icon and self.icon.cget("image"):
                continue
            try:
                if w.cget("bg") in (C["card"], C["hover"]):
                    w.configure(bg=bg)
            except tk.TclError:
                pass
        self.frame.configure(highlightbackground=C["dim"] if on else C["line"])

    def set_relation(self, text, colour):
        self.rel.configure(text=text, fg=colour)
        if text and not self.rel.winfo_manager():
            self.rel.pack(fill="x")
        elif not text and self.rel.winfo_manager():
            self.rel.pack_forget()

    def show(self, visible):
        if visible:
            self.frame.pack(**self.pack_opts)
        else:
            self.frame.pack_forget()


class App(tk.Tk):
    PLACEHOLDER = "🔍  ค้นหาม็อด เช่น แผนที่ หรือ jei"

    def __init__(self):
        super().__init__()
        self.title("ลงม็อดเพิ่มความลื่น + ม็อดสามัญประจำบ้าน")
        self.geometry("1040x760")
        self.minsize(860, 580)
        self.configure(bg=C["bg"])
        self.dark_titlebar()
        self.info, self.plan, self.rows, self.sections = None, [], [], []
        self.icon_imgs = []
        self.q = queue.Queue()          # worker threads never touch Tk: they queue callables
        self.after(100, self._poll)

        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure("Dark.Vertical.TScrollbar", background=C["line"], troughcolor=C["bg"], bordercolor=C["bg"],
                     arrowcolor=C["muted"], lightcolor=C["line"], darkcolor=C["line"], gripcount=0)
        st.map("Dark.Vertical.TScrollbar", background=[("active", C["dim"])])

        head = tk.Frame(self, bg=C["panel"])
        head.pack(fill="x")
        row1 = tk.Frame(head, bg=C["panel"])
        row1.pack(fill="x", padx=20, pady=(14, 4))
        tk.Label(row1, text="●", bg=C["panel"], fg=C["accent"], font=(FONT, 14)).pack(side="left")
        tk.Label(row1, text=" ลงม็อดเพิ่มความลื่น", bg=C["panel"], fg=C["text"], font=(FONT, 16, "bold")).pack(side="left")
        tk.Label(row1, text="   เลือกไฟล์ที่ตรงกับเวอร์ชันเกมให้อัตโนมัติ · ไม่ใช่โปรแกรมทางการของ Minecraft (not an official Minecraft product)", bg=C["panel"],
                 fg=C["dim"], font=(FONT, 9)).pack(side="left", pady=(6, 0))
        row2 = tk.Frame(head, bg=C["panel"])
        row2.pack(fill="x", padx=20, pady=(6, 14))
        start = os.path.join(DEFAULT_ROOT, "__")
        given = next((x for x in sys.argv[1:] if not x.startswith("--") and os.path.isdir(x)), None)
        self.path = tk.StringVar(value=given or (start if os.path.isdir(start) else ""))
        e = self.entry(row2, self.path)
        e.pack(side="left", fill="x", expand=True, ipady=7)
        e.bind("<Return>", lambda _: self.check())
        self.btn_browse = self.button(row2, "เลือกโฟลเดอร์", self.browse, secondary=True)
        self.btn_browse.pack(side="left", padx=8)
        self.btn_check = self.button(row2, "ตรวจม็อดแพ็ก", self.check)
        self.btn_check.pack(side="left")
        tk.Frame(self, bg=C["line"], height=1).pack(fill="x")

        info = tk.Frame(self, bg=C["bg"])
        info.pack(fill="x", padx=20, pady=(12, 0))
        self.status = tk.StringVar(value="เลือกโฟลเดอร์ม็อดแพ็ก (โฟลเดอร์ที่มี mods อยู่ข้างใน) แล้วกด ตรวจม็อดแพ็ก")
        tk.Label(info, textvariable=self.status, bg=C["bg"], fg=C["text"], font=(FONT, 10), anchor="w").pack(side="left", fill="x", expand=True)
        self.search = tk.StringVar()
        se = self.entry(info, self.search, width=26, placeholder=self.PLACEHOLDER)
        se.pack(side="right", ipady=5)
        self.search.trace_add("write", lambda *_a: self.apply_filter())

        mid = tk.Frame(self, bg=C["bg"])
        mid.pack(fill="both", expand=True, padx=(14, 6), pady=(4, 8))
        self.canvas = tk.Canvas(mid, highlightthickness=0, bg=C["bg"])
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview, style="Dark.Vertical.TScrollbar")
        self.listbox = tk.Frame(self.canvas, bg=C["bg"])
        self.listbox.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.listbox, anchor="nw")
        self.canvas.bind("<Configure>", lambda ev: self.canvas.itemconfigure(self._win, width=ev.width - 8))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", lambda ev: self.canvas.yview_scroll(int(-ev.delta / 120), "units"))

        self.foot = tk.Frame(self, bg=C["panel"])
        self.foot.pack(fill="x", side="bottom")
        tk.Frame(self, bg=C["line"], height=1).pack(fill="x", side="bottom")
        self.log = tk.Text(self, height=7, state="disabled", bg="#0e1013", fg="#c4cad3", font=("Consolas", 9),
                           relief="flat", padx=10, pady=6)
        self.btn_restore = self.button(self.foot, "ย้อนการติดตั้ง", self.restore, secondary=True)
        self.btn_restore.pack(side="left", padx=(20, 8), pady=12)
        self.btn_log = self.button(self.foot, "ดูบันทึก", self.toggle_log, secondary=True)
        self.btn_log.pack(side="left", pady=12)
        self.notice = tk.Label(self.foot, text="", bg=C["panel"], fg=C["muted"], font=(FONT, 9), anchor="w",
                               justify="left", wraplength=420)
        self.notice.pack(side="left", padx=16, fill="x", expand=True)
        self.btn_install = self.button(self.foot, "ติดตั้งที่เลือกไว้", self.install, big=True)
        self.btn_install.pack(side="right", padx=20, pady=12)
        self.summary = tk.Label(self.foot, text="", bg=C["panel"], fg=C["text"], font=(FONT, 10, "bold"))
        self.summary.pack(side="right")
        self.btn_install.configure(state="disabled")

    # ------------------------------------------------------------ widgets
    def dark_titlebar(self):
        try:                            # Windows 10 1809+/11: dark title bar to match the window
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            val = ctypes.c_int(1)
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                    break
        except Exception:
            pass

    def entry(self, parent, var, width=None, placeholder=None):
        e = tk.Entry(parent, textvariable=var, font=(FONT, 10), relief="flat", bg=C["field"], fg=C["text"],
                     insertbackground=C["text"], highlightthickness=1, highlightbackground=C["line"],
                     highlightcolor=C["accent"], **({"width": width} if width else {}))
        if placeholder:
            def show_ph(_e=None):
                if not var.get():
                    e.ph = True                 # set first: insert() fires the search trace
                    e.configure(fg=C["dim"])
                    e.insert(0, placeholder)

            def hide_ph(_e=None):
                if getattr(e, "ph", False):
                    e.ph = False
                    e.delete(0, "end")
                    e.configure(fg=C["text"])
            e.ph = False
            e.bind("<FocusIn>", hide_ph)
            e.bind("<FocusOut>", show_ph)
            show_ph()
            self.search_entry = e
        return e

    def button(self, parent, text, cmd, secondary=False, big=False):
        if secondary:
            bg, fg, act = C["field"], C["text"], C["hover"]
        else:
            bg, fg, act = C["accent"], C["on_accent"], C["accent_hover"]
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, activebackground=act, activeforeground=fg,
                      disabledforeground=C["dim"], relief="flat", bd=0, padx=22 if big else 16, pady=8 if big else 6,
                      cursor="hand2", font=(FONT, 11 if big else 10, "normal" if secondary else "bold"))
        b.bind("<Enter>", lambda _e: b.configure(bg=act) if str(b["state"]) != "disabled" else None)
        b.bind("<Leave>", lambda _e: b.configure(bg=bg))
        return b

    def ui(self, fn):
        self.q.put(fn)

    def _poll(self):
        try:
            while True:
                self.q.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def write(self, msg):
        def do():
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.ui(do)

    def toggle_log(self):
        if self.log.winfo_ismapped():
            self.log.pack_forget()
        else:
            self.log.pack(fill="x", side="bottom", before=self.foot)

    def say(self, text, colour=None):
        """Short message in the footer about what the last click did."""
        self.notice.configure(text=text, fg=colour or C["muted"])

    def busy(self, on, msg=None):
        for b in (self.btn_check, self.btn_browse, self.btn_restore):
            b.configure(state="disabled" if on else "normal")
        self.btn_install.configure(state="disabled" if on or not self.plan else "normal")
        if msg:
            self.status.set(msg)

    def browse(self):
        d = filedialog.askdirectory(initialdir=DEFAULT_ROOT if os.path.isdir(DEFAULT_ROOT) else None, title="เลือกโฟลเดอร์ม็อดแพ็ก")
        if d:
            self.path.set(os.path.normpath(d))
            self.check()

    def title_of(self, slug):
        r = self.by_slug.get(slug)
        return (r.p.get("title") if r and r.p else None) or slug

    # ------------------------------------------------------------ check
    def check(self):
        inst = self.path.get().strip().strip('"')
        if not os.path.isdir(inst):
            messagebox.showerror("ไม่พบโฟลเดอร์", "ไม่พบโฟลเดอร์นี้:\n%s" % inst)
            return
        info = perf.detect(inst)
        if not info["mc"] or not info["loader"]:
            messagebox.showerror("ตรวจไม่สำเร็จ", "ไม่พบไฟล์ข้อมูลม็อดแพ็ก (minecraftinstance.json ของ CurseForge หรือ mmc-pack.json ของ Prism)\n"
                                                      "กรุณาเลือกโฟลเดอร์ม็อดแพ็กที่มีโฟลเดอร์ mods อยู่ข้างใน")
            return
        if info["loader"] not in perf.SETS:
            messagebox.showerror("ยังไม่รองรับ", "ยังไม่รองรับ loader %s" % info["loader"])
            return
        self.info, self.plan = info, []
        self.busy(True, "กำลังค้นหาไฟล์สำหรับ Minecraft %s (%s) จาก Modrinth..." % (info["mc"], info["loader"]))
        self.say("")
        for w in self.listbox.winfo_children():
            w.destroy()

        def work():
            try:
                plan, skipped = perf.resolve(info, True, True)
                self.ui(lambda: self.show(plan, skipped))
            except Exception as ex:
                err = str(ex)
                self.ui(lambda: (self.busy(False, "ตรวจไม่สำเร็จ: %s" % err), messagebox.showerror("ตรวจไม่สำเร็จ", err)))
        threading.Thread(target=work, daemon=True).start()

    def show(self, plan, skipped):
        self.plan, self.rows, self.sections = plan, [], []
        by = {p["slug"]: p for p in plan}
        main = [p for p in plan if not p.get("optional")]
        qol_libs = [p for p in plan if p.get("optional") and p["slug"] not in perf.QOL]

        s1 = Section(self, self.listbox, "ชุดเพิ่มความลื่น + Essential", hint="เลือกไว้ให้แล้ว")
        s1.add_tick_buttons()
        for p in main:
            self.rows.append(Row(self, s1, p, ticked=True))
        s2 = Section(self, self.listbox, "ม็อดสามัญประจำบ้าน", hint="ยังไม่ได้เลือก เพิ่มได้ตามชอบ")
        s2.add_tick_buttons()
        for title, slugs in perf.QOL_GROUPS:
            items = [by[s] for s in slugs if s in by]
            if not items:
                continue
            sub = Section(self, s2.body, title, open_=True, level=1)
            s2.children.append(sub)
            for p in items:
                self.rows.append(Row(self, sub, p, ticked=False))
        self.sections = [s1, s2] + s2.children
        if qol_libs:
            s3 = Section(self, self.listbox, "ไลบรารีเสริม", open_=False, hint="เลือกให้อัตโนมัติเมื่อม็อดที่ต้องใช้ถูกเลือก")
            for p in qol_libs:
                self.rows.append(Row(self, s3, p, ticked=False, auto=True))
            self.sections.append(s3)
        if skipped:
            s4 = Section(self, self.listbox, "รายการที่ข้ามไป", open_=False, hint="มีอยู่แล้ว หรือใช้กับม็อดแพ็กนี้ไม่ได้")
            for slug, why in skipped:
                self.rows.append(Row(self, s4, None, slug=slug, note=why))
            self.sections.append(s4)
        self.by_slug = {r.slug: r for r in self.rows if r.p}
        self.needed_by = {r.slug: [] for r in self.rows if r.p}
        for r in self.rows:
            if r.p:
                for need in r.p["requires"]:
                    if need in self.needed_by:
                        self.needed_by[need].append(r.slug)
        self.refresh()
        self.load_icons(plan)
        self.busy(False, ("Minecraft %s · %s  —  พบ %d ม็อดที่ติดตั้งได้" % (self.info["mc"], self.info["loader"], len(plan)))
                  if plan else "ม็อดแพ็กนี้มีม็อดในชุดครบแล้ว ไม่ต้องติดตั้งเพิ่ม")
        self.apply_filter()

    # ------------------------------------------------------------ ticking
    def ticked(self):
        return {r.slug for r in self.rows if r.var is not None and r.var.get()}

    def requires_all(self, slug):
        """Every mod in the list that `slug` needs, directly or through another mod."""
        out, todo = set(), [slug]
        while todo:
            r = self.by_slug.get(todo.pop())
            for need in (r.p["requires"] if r else []):
                if need in self.by_slug and need not in out:
                    out.add(need)
                    todo.append(need)
        return out

    def dependents_all(self, slug, among):
        """Ticked mods (in `among`) that stop working without `slug`."""
        out, todo = set(), [slug]
        while todo:
            for user in self.needed_by.get(todo.pop(), []):
                if user in among and user not in out:
                    out.add(user)
                    todo.append(user)
        return out

    def toggle(self, row):
        if row.auto:
            users = [self.title_of(u) for u in self.needed_by.get(row.slug, []) if u in self.ticked()]
            self.say("%s %s" % (row.p["title"], ("ถูกเลือกให้อัตโนมัติ เพราะ " + ", ".join(users) + " ต้องใช้") if users else
                                                  "จะถูกเลือกให้เองเมื่อเลือกม็อดที่ต้องใช้"))
            return
        if not row.var.get():
            added = [s for s in self.requires_all(row.slug) if s not in self.ticked()]
            row.var.set(True)
            for s in added:
                self.by_slug[s].var.set(True)
            self.refresh()
            if added:
                self.say("✓ เลือก %s แล้ว พร้อมเลือก %s ที่ต้องใช้คู่กันให้ด้วย" % (row.p["title"], ", ".join(self.title_of(s) for s in added)),
                         C["accent"])
            else:
                self.say("✓ เลือก %s แล้ว" % row.p["title"], C["accent"])
            return
        ticked = self.ticked()
        users = self.dependents_all(row.slug, ticked)
        users = {u for u in users if not self.by_slug[u].auto}
        if users:
            names = "\n".join("• " + self.title_of(u) for u in sorted(users))
            if not messagebox.askyesno("%s จำเป็นต่อม็อดอื่น" % row.p["title"],
                                       "ถ้าเอา %s ออก ม็อดต่อไปนี้จะทำงานไม่ได้ และอาจทำให้เกมเปิดไม่ขึ้น:\n\n%s\n\n"
                                       "ต้องการเอาออกทั้งหมดไหม?\n(ใช่/Yes = เอาออกทั้งหมด · ไม่ใช่/No = เก็บ %s ไว้เหมือนเดิม)"
                                       % (row.p["title"], names, row.p["title"])):
                self.say("ยังเก็บ %s ไว้ เพราะ %s ต้องใช้" % (row.p["title"], ", ".join(self.title_of(u) for u in sorted(users))),
                         C["warn"])
                return
            for u in users:
                self.by_slug[u].var.set(False)
        row.var.set(False)
        self.refresh()
        self.say("เอา %s ออกแล้ว%s" % (row.p["title"], (" พร้อมกับ " + ", ".join(self.title_of(u) for u in sorted(users))) if users else ""),
                 C["warn"] if users else None)

    def tick_section(self, section, value):
        rows = [r for r in section.all_rows() if r.var is not None and not r.auto]
        if value:
            for r in rows:
                r.var.set(True)
                for s in self.requires_all(r.slug):
                    self.by_slug[s].var.set(True)
            self.refresh()
            self.say("✓ เลือกทั้งหมดในหมวด %s แล้ว (รวมม็อดที่ต้องใช้คู่กัน)" % section.title, C["accent"])
            return
        slugs = {r.slug for r in rows}
        outside = self.ticked() - slugs
        keep = {s for s in slugs if self.dependents_all(s, outside) - slugs}   # still needed by a ticked mod elsewhere
        for r in rows:
            if r.slug not in keep:
                r.var.set(False)
        self.refresh()
        if keep:
            self.say("ยังเก็บ %s ไว้ เพราะม็อดที่เลือกในหมวดอื่นต้องใช้" % ", ".join(self.title_of(s) for s in sorted(keep)), C["warn"])
        else:
            self.say("ยกเลิกการเลือกทั้งหมดในหมวด %s แล้ว" % section.title)

    def refresh(self):
        """Libraries follow the mods that need them; update relation lines, counters, summary."""
        ticked = {r.slug for r in self.rows if r.var is not None and r.var.get() and not r.auto}
        for s in list(ticked):
            ticked |= self.requires_all(s)
        for r in self.rows:
            if r.auto and r.var.get() != (r.slug in ticked):
                r.var.set(r.slug in ticked)
        on = self.ticked()
        for r in self.rows:
            if not r.p:
                continue
            parts, colour = [], C["dim"]
            missing = [s for s in r.p["requires"] if s in self.by_slug and s not in on]
            if r.var.get() and missing:
                parts.append("⚠ ยังขาด: " + ", ".join(self.title_of(s) for s in missing))
                colour = C["danger"]
            elif r.p["requires"]:
                parts.append("ต้องใช้คู่กับ: " + ", ".join(self.title_of(s) for s in r.p["requires"]))
            users = [self.title_of(u) for u in self.needed_by.get(r.slug, []) if u in on]
            if users:
                parts.append("จำเป็นสำหรับ: " + ", ".join(users))
            r.set_relation("   ·   ".join(parts), colour)
        for s in self.sections:
            s.refresh_count()
        n = len(on)
        self.summary.configure(text="เลือกไว้ %d ไฟล์" % n if n else "")

    def apply_filter(self):
        """Re-pack rows in their original order (pack_forget + pack would move them to the end);
        while searching, hide sub-groups with no match and open the ones that have one."""
        q = self.search.get().strip().lower()
        if q == self.PLACEHOLDER.strip().lower():
            q = ""
        for s in self.sections:
            for r in s.rows:
                r.show(False)
            for r in s.rows:
                if not q or q in r.search_text:
                    r.show(True)
        for s in self.sections:
            s.frame.pack_forget()
        for s in self.sections:            # self.sections is in display order, parents before children
            hit = any(not q or q in r.search_text for r in s.all_rows())
            if hit:
                s.frame.pack(fill="x", **s.pack_opts)
            if q and hit and not s.open:
                s.toggle()

    def load_icons(self, plan):
        """Fetch icons in the background; without Pillow only PNG/GIF can be shown."""
        def work():
            for p in plan:
                url = p.get("icon_url")
                if not url:
                    continue
                try:
                    with urllib.request.urlopen(urllib.request.Request(url, headers=perf.HEADERS), timeout=15) as r:
                        data = r.read()
                except Exception:
                    continue
                if Image is None and data[:8] != b"\x89PNG\r\n\x1a\n" and data[:4] != b"GIF8":
                    continue
                self.ui(lambda s=p["slug"], d=data: self.set_icon(s, d))
        threading.Thread(target=work, daemon=True).start()

    def set_icon(self, slug, data, size=36):
        for r in self.rows:
            if r.slug != slug or not r.icon.winfo_exists():
                continue
            try:
                if Image is not None:
                    im = Image.open(io.BytesIO(data))
                    im.seek(0)
                    im = im.convert("RGBA")
                    im.thumbnail((size, size), Image.LANCZOS)
                    img = ImageTk.PhotoImage(im)
                else:
                    img = tk.PhotoImage(data=base64.b64encode(data))
                    f = max(1, -(-max(img.width(), img.height()) // size))
                    img = img.subsample(f, f)
            except Exception:
                return
            self.icon_imgs.append(img)          # keep a reference or Tk drops the image
            r.icon.configure(image=img, text="", width=size, height=size, bg=C["card"])

    # ------------------------------------------------------------ install
    def install(self):
        chosen = [r.p for r in self.rows if r.p and r.var.get()]
        if not chosen:
            messagebox.showinfo("ยังไม่ได้เลือก", "ยังไม่ได้เลือกม็อดสักตัว")
            return
        picked = {p["slug"] for p in chosen}
        missing = sorted({"%s (ต้องใช้กับ %s)" % (self.title_of(r), p.get("title") or p["slug"])
                          for p in chosen for r in p["requires"] if r in self.by_slug and r not in picked})
        if missing:
            if not messagebox.askyesno("ยังขาดม็อดที่ต้องใช้", "ม็อดต่อไปนี้ยังไม่ได้เลือก แต่ม็อดที่เลือกไว้ต้องใช้ ถ้าไม่ลงเกมอาจเปิดไม่ขึ้น:\n\n%s\n\n"
                                       "ต้องการให้เลือกให้แล้วติดตั้งต่อเลยไหม?" % "\n".join(missing)):
                return
            for p in chosen:
                for s in self.requires_all(p["slug"]):
                    self.by_slug[s].var.set(True)
            self.refresh()
            return self.install()
        names = "\n".join("• %s" % (p.get("title") or p["slug"]) for p in chosen)
        if not messagebox.askyesno("ยืนยันการติดตั้ง", "ติดตั้ง %d ม็อด\nปลายทาง: %s\n\n%s\n\nปิดเกมแล้วใช่ไหม?"
                                   % (len(chosen), self.info["mods_dir"], names)):
            return
        inst = self.path.get().strip().strip('"')
        self.busy(True, "กำลังดาวน์โหลดและติดตั้ง...")
        if not self.log.winfo_ismapped():
            self.toggle_log()

        def work():
            try:
                tag, added = perf.install_plan(self.info, chosen, inst, self.write)
                self.write("ติดตั้งเสร็จ %d ไฟล์ (รายการ %s)" % (len(added), tag))
                self.ui(lambda: (messagebox.showinfo("ติดตั้งเสร็จแล้ว", "ติดตั้งแล้ว %d ม็อด เปิดเกมได้เลย\n\n"
                                                    "ถ้าเกมมีปัญหา กด 'ย้อนการติดตั้ง' แล้วเลือกรายการ %s" % (len(added), tag)),
                                 self.check()))
            except Exception as ex:
                err = str(ex)
                self.ui(lambda: (self.busy(False, "ติดตั้งไม่สำเร็จ: %s" % err), messagebox.showerror("ติดตั้งไม่สำเร็จ", err)))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ restore
    def restore(self):
        inst = self.path.get().strip().strip('"')
        files = perf.installs(inst)
        if not files:
            messagebox.showinfo("ไม่มีประวัติ", "ยังไม่เคยติดตั้งม็อดด้วยโปรแกรมนี้ในม็อดแพ็กนี้")
            return
        win = tk.Toplevel(self, bg=C["bg"])
        win.title("ย้อนการติดตั้ง")
        win.geometry("700x360")
        tk.Label(win, text="เลือกรายการที่ต้องการย้อนกลับ โปรแกรมจะลบเฉพาะไฟล์ที่ตัวเองติดตั้งไว้ (ปิดเกมก่อน)", bg=C["bg"],
                 fg=C["text"], font=(FONT, 10)).pack(anchor="w", padx=16, pady=12)
        lb = tk.Listbox(win, font=(FONT, 10), relief="flat", bg=C["card"], fg=C["text"], selectbackground=C["accent"],
                        selectforeground=C["on_accent"], highlightthickness=1, highlightbackground=C["line"])
        lb.pack(fill="both", expand=True, padx=16)
        names = []
        for f in reversed(files):
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            name = os.path.basename(f)[:-5]
            names.append(name)
            lb.insert("end", "%s   %d ไฟล์: %s" % (name, len(d["added"]), ", ".join(x["slug"] for x in d["added"])))

        def go():
            sel = lb.curselection()
            if not sel:
                return
            name = names[sel[0]]
            if messagebox.askyesno("ยืนยัน", "ย้อนการติดตั้งรายการ %s ใช่ไหม? (ปิดเกมก่อน)" % name, parent=win):
                kept = perf.restore_install(inst, name, self.write)["kept"]
                if kept:
                    self.write("ย้อนรายการ %s ได้บางส่วน: ไม่ได้ลบ %d ไฟล์ข้างบน (ยังอยู่ในรายการ ย้อนซ้ำได้)"
                               % (name, len(kept)))
                else:
                    self.write("ย้อนการติดตั้งรายการ %s แล้ว" % name)
                win.destroy()
                self.check()
        self.button(win, "ย้อนกลับ", go).pack(pady=12)


if __name__ == "__main__":
    App().mainloop()
