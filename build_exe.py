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
"""


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
           "--distpath", DIST, "--workpath", os.path.join(WORK, "work"), "--specpath", WORK,
           os.path.join(SCRIPTS, "perf_web.py")]
    subprocess.run(cmd, check=True)
    out = os.path.join(DIST, NAME)
    with open(os.path.join(out, "อ่านก่อน.txt"), "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(README_TXT)
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
