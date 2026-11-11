#!/usr/bin/env python3
"""Build the no-install Windows version for friends: dist/MC-Perf-Mods.zip
(a folder with MC-Perf-Mods.exe; Python, pywebview and the window are inside).

Needs on THIS machine only: pip install pyinstaller pywebview pillow
Run:  python build_exe.py"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(ROOT, "scripts")
WORK = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
NAME = "MC-Perf-Mods"
ICON = os.path.join(ROOT, "assets", "icon.ico")
NOTICES = os.path.join(ROOT, "THIRD-PARTY-NOTICES.txt")

# Python packages that end up inside the exe (checked against PyInstaller's PYZ-00.toc after the build)
BUNDLED = [
    ("pywebview", "webview", "the window, drawn with HTML/CSS - BSD-3-Clause"),
    ("pythonnet", "clr", ".NET bridge used by pywebview on Windows - MIT"),
    ("clr_loader", "clr_loader", ".NET runtime loader - MIT"),
    ("bottle", "bottle", "imported by pywebview - MIT"),
    ("proxy_tools", "proxy_tools", "imported by pywebview - MIT"),
    ("cffi", "cffi", "used by clr_loader - MIT"),
    ("pycparser", "pycparser", "used by cffi - BSD-3-Clause"),
    ("typing_extensions", "typing_extensions", "used by pywebview - PSF-2.0"),
]
# license texts that do not come with an installed package (saved in licenses/)
EXTRA = [
    ("Microsoft Edge WebView2 SDK (Microsoft.Web.WebView2.Core.dll, Microsoft.Web.WebView2.WinForms.dll)",
     "microsoft-webview2.txt"),
    ("Lucide icons (the line icons drawn in the window)", "lucide.txt"),
]
PROXY_TOOLS_MIT = """MIT License (stated in the package metadata; the package ships no license file)

Copyright (c) Jonathan Tushman - https://github.com/jtushman/proxy_tools

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
USE OR OTHER DEALINGS IN THE SOFTWARE.
"""


def make_notices(toc_text):
    """THIRD-PARTY-NOTICES.txt for everything inside the exe. Fails if a bundled package has no license."""
    import importlib.metadata as md
    bar = "=" * 78
    out = ["THIRD-PARTY NOTICES - MC-Perf-Mods (Windows build)", "",
           "MC-Perf-Mods itself is MIT licensed (see LICENSE). The Windows build bundles the software below;",
           "each part keeps its own license, reproduced here as those licenses require.", "",
           "Not bundled: Minecraft mods are downloaded by the user's computer straight from Modrinth and stay",
           "under their authors' licenses. Fonts (Noto Sans Thai, Inter; SIL Open Font License) load from",
           "Google Fonts at run time.", ""]
    sections = []
    py_lic = os.path.join(sys.base_prefix, "LICENSE.txt")
    with open(py_lic, encoding="utf-8") as fh:
        sections.append(("Python %d.%d.%d (python3*.dll, standard library, and the libraries the Windows build "
                         "of Python ships: OpenSSL, libffi, Tcl/Tk, zlib, bzip2, xz, zstd, mpdecimal, expat, "
                         "Microsoft Visual C++ runtime)" % sys.version_info[:3], fh.read()))
    for dist_name, module, what in BUNDLED:
        if "('%s'" % module not in toc_text and "('%s." % module not in toc_text:
            continue                                  # not in this build
        dist = md.distribution(dist_name)
        texts = []
        for f in dist.files or []:
            if any(k in f.name.upper() for k in ("LICENSE", "COPYING", "NOTICE")):
                texts.append(f.read_text(encoding="utf-8"))
        if not texts and dist_name == "proxy_tools":
            texts = [PROXY_TOOLS_MIT]
        if not texts:
            raise SystemExit("no license text found for bundled package %s" % dist_name)
        sections.append(("%s %s - %s" % (dist_name, dist.version, what), "\n\n".join(texts)))
    for title, fn in EXTRA:
        with open(os.path.join(ROOT, "licenses", fn), encoding="utf-8") as fh:
            sections.append((title, fh.read()))
    sections.append(("PyInstaller bootloader (MC-Perf-Mods.exe launcher)",
                     "GPL-2.0-or-later with the PyInstaller bootloader exception, which allows distributing the\n"
                     "bootloader combined with any program under any license. https://pyinstaller.org/en/stable/license.html"))
    out.append("Contents:")
    out += ["  %d. %s" % (i + 1, t.split(" (")[0]) for i, (t, _) in enumerate(sections)]
    for i, (t, body) in enumerate(sections):
        out += ["", bar, "%d. %s" % (i + 1, t), bar, "", body.replace("\r\n", "\n").strip()]
    return "\n".join(out) + "\n"

README_TXT = """MC-Perf-Mods · ลงม็อดเพิ่มความลื่นให้ Minecraft
=================================================

วิธีใช้
1. ปิดเกมก่อน
2. ดับเบิลคลิก MC-Perf-Mods.exe
   (หรือลากโฟลเดอร์ม็อดแพ็กมาวางบน MC-Perf-Mods.exe โปรแกรมจะตรวจให้ทันที)
3. กด "เลือกโฟลเดอร์" แล้วเลือกโฟลเดอร์ม็อดแพ็ก จากนั้นกด "ตรวจม็อดแพ็ก"
4. เลือกม็อดที่ต้องการ แล้วกด "ติดตั้งที่เลือกไว้"

หาโฟลเดอร์ม็อดแพ็ก
- CurseForge: คลิกขวาที่ม็อดแพ็ก แล้วเลือก Open Folder
- Prism Launcher: คลิกขวาที่ม็อดแพ็ก แล้วเลือก Folder
โฟลเดอร์ที่ถูกต้องคือโฟลเดอร์ที่มีโฟลเดอร์ mods อยู่ข้างใน

เปิดครั้งแรกแล้ว Windows ขึ้นว่า "Windows protected your PC"
เป็นเพราะโปรแกรมไม่มีลายเซ็นดิจิทัล ไม่ใช่ไวรัส
ให้กด "More info" แล้วกด "Run anyway" (ทำครั้งเดียว)

ลงแล้วเกมมีปัญหา
เปิดโปรแกรม กด "ย้อนการติดตั้ง" แล้วเลือกรายการล่าสุด

ห้ามย้าย MC-Perf-Mods.exe ออกจากโฟลเดอร์นี้ เพราะต้องใช้ไฟล์ในโฟลเดอร์ _internal
อยากเปลี่ยนพื้นหลัง กดปุ่ม "พื้นหลัง" มุมขวาบนของโปรแกรม แล้วเลือกรูปหรือวิดีโอได้เลย

ลิขสิทธิ์
- MC-Perf-Mods ใช้สัญญาอนุญาต MIT (ไฟล์ LICENSE.txt) ใช้ฟรี แจกต่อได้ ไม่มีการรับประกันใดๆ
- โปรแกรมนี้รวมซอฟต์แวร์ของผู้อื่นไว้ด้วย รายละเอียดสัญญาอยู่ในไฟล์ THIRD-PARTY-NOTICES.txt
- โปรแกรมไม่ได้แจกไฟล์ม็อด ม็อดทุกตัวโหลดตรงจาก Modrinth และเป็นลิขสิทธิ์ของผู้ทำม็อดแต่ละคน
- NOT AN OFFICIAL MINECRAFT PRODUCT. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT.
  ไม่ใช่โปรแกรมทางการของ Minecraft ไม่ได้รับการรับรองหรือเกี่ยวข้องกับ Mojang หรือ Microsoft

เวอร์ชัน %s · https://github.com/NoNgNoN777/mc-perf-mods
"""


def version():
    sys.path.insert(0, SCRIPTS)
    import perf
    return perf.VERSION


def make_icon():
    """Purple-pink rounded square with a white lightning bolt, like the window logo."""
    if os.path.exists(ICON):
        return
    from PIL import Image, ImageDraw
    n = 256
    grad = Image.new("RGBA", (n, n))
    px = grad.load()
    a, b, c = (255, 95, 168), (196, 91, 255), (124, 77, 255)
    for y in range(n):
        for x in range(n):
            t = (x + y) / (2 * (n - 1))
            lo, hi, u = (a, b, t / .55) if t < .55 else (b, c, (t - .55) / .45)
            px[x, y] = tuple(int(lo[i] + (hi[i] - lo[i]) * u) for i in range(3)) + (255,)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((8, 8, n - 9, n - 9), radius=64, fill=255)
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    bolt = [(141, 34), (62, 146), (120, 146), (106, 222), (194, 104), (134, 104), (152, 34)]
    ImageDraw.Draw(img).polygon(bolt, fill=(255, 255, 255, 255))
    os.makedirs(os.path.dirname(ICON), exist_ok=True)
    img.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    make_icon()
    shutil.rmtree(os.path.join(DIST, NAME), ignore_errors=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", NAME, "--icon", ICON,
           "--add-data", os.path.join(SCRIPTS, "ui") + os.pathsep + "ui",
           "--paths", SCRIPTS, "--hidden-import", "perf", "--hidden-import", "perf_gui",
           # not used by the program, only pulled in because they are installed here (-50 MB)
           "--exclude-module", "numpy", "--exclude-module", "PIL", "--exclude-module", "cryptography",
           "--exclude-module", "setuptools", "--exclude-module", "pkg_resources",
           "--distpath", DIST, "--workpath", os.path.join(WORK, "work"), "--specpath", WORK,
           os.path.join(SCRIPTS, "perf_web.py")]
    subprocess.run(cmd, check=True)
    out = os.path.join(DIST, NAME)
    with open(os.path.join(WORK, "work", NAME, "PYZ-00.toc"), encoding="utf-8") as fh:
        notices = make_notices(fh.read())
    with open(NOTICES, "w", encoding="utf-8", newline="\n") as f:      # copy kept in the repo
        f.write(notices)
    with open(os.path.join(out, "THIRD-PARTY-NOTICES.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(notices)
    with open(os.path.join(ROOT, "LICENSE"), encoding="utf-8") as fh, \
            open(os.path.join(out, "LICENSE.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(fh.read())
    with open(os.path.join(out, "อ่านก่อน.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(README_TXT % version())
    zpath = os.path.join(DIST, NAME + ".zip")
    if os.path.exists(zpath):
        os.remove(zpath)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, _dirs, files in os.walk(out):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, DIST))
    size = os.path.getsize(zpath) / 1024 / 1024
    print("\nเสร็จ: %s (%.1f MB)" % (zpath, size))


if __name__ == "__main__":
    main()
