#!/usr/bin/env python3
"""mc-perf-mods - add the usual "make it smooth" mods (+ Essential for playing with friends)
to any Minecraft instance, picking the right files for its loader and version from Modrinth.

    python perf.py plan    --instance <dir> [--no-shaders] [--no-essential]
    python perf.py install --instance <dir> [--no-shaders] [--no-essential]
    python perf.py restore --instance <dir> [--install <name>]     (removes what an install added)
    python perf.py list    --instance <dir>                          (installs made by this tool)

Python 3.8+, standard library only. Only adds files to mods/ - never replaces or deletes a mod
it did not add itself.
"""
import argparse
import datetime
import glob
import hashlib
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API = "https://api.modrinth.com/v2"
HEADERS = {"User-Agent": "NoNgNoN777/mc-perf-mods/1.0"}
STATE_DIR = ".mc-perf-mods"

# slug -> (role, mod ids that mean "already have this or an equivalent")
# Picked from Modrinth's most-downloaded optimization / utility mods (Nov 2026) that do not change gameplay.
MODS = {
    "fabric-api":            ("library",  ["fabric-api", "fabric"]),
    "sodium":                ("render",   ["sodium", "embeddium", "rubidium"]),
    "embeddium":             ("render",   ["embeddium", "rubidium", "sodium"]),
    "indium":                ("library",  ["indium"]),
    "lithium":               ("logic",    ["lithium", "canary", "radium"]),
    "iris":                  ("shaders",  ["iris", "oculus", "irisshaders"]),
    "oculus":                ("shaders",  ["oculus", "iris"]),
    "ferrite-core":          ("memory",   ["ferritecore"]),
    "modernfix":             ("memory",   ["modernfix"]),
    "memoryleakfix":         ("memory",   ["memoryleakfix"]),
    "immediatelyfast":       ("render",   ["immediatelyfast"]),
    "entityculling":         ("render",   ["entityculling"]),
    "moreculling":           ("render",   ["moreculling"]),
    "modelfix":              ("fix",      ["modelfix"]),
    "dynamic-fps":           ("idle",     ["dynamic_fps", "dynamicfps"]),
    "badoptimizations":      ("logic",    ["badoptimizations"]),
    "krypton":               ("network",  ["krypton"]),
    "fast-ip-ping":          ("network",  ["fastipping", "fast_ip_ping"]),
    "sodium-extra":          ("settings", ["sodium-extra", "sodiumextra", "embeddium_extra", "rubidium_extra"]),
    "reeses-sodium-options": ("settings", ["reeses-sodium-options", "reeses_sodium_options"]),
    "essential":             ("social",   ["essential", "essential-loader"]),
    # common quality-of-life mods: offered, never ticked
    "jei":                   ("qol",      ["jei", "roughlyenoughitems", "emi"]),
    "jade":                  ("qol",      ["jade", "waila", "wthit", "hwyla"]),
    "appleskin":             ("qol",      ["appleskin"]),
    "enchantment-descriptions": ("qol",   ["enchdesc", "enchantment_descriptions"]),
    "shulkerboxtooltip":     ("qol",      ["shulkerboxtooltip"]),
    "mouse-tweaks":          ("qol",      ["mousetweaks"]),
    "crafting-tweaks":       ("qol",      ["craftingtweaks"]),
    "xaeros-minimap":        ("qol",      ["xaerominimap", "xaerominimapfair", "journeymap", "voxelmap"]),
    "xaeros-world-map":      ("qol",      ["xaeroworldmap", "journeymap", "antiqueatlas", "antique_atlas"]),
    "continuity":            ("qol",      ["continuity"]),
    "lambdynamiclights":     ("qol",      ["lambdynlights", "sodiumdynamiclights", "dynamiclightsreforged", "ryoamiclights"]),
    "sodium-dynamic-lights": ("qol",      ["sodiumdynamiclights", "lambdynlights", "dynamiclightsreforged", "ryoamiclights"]),
    "entitytexturefeatures": ("qol",      ["entity_texture_features"]),
    "entity-model-features": ("qol",      ["entity_model_features"]),
    "sound-physics-remastered": ("qol",   ["sound_physics_remastered"]),
    "zoomify":               ("qol",      ["zoomify", "okzoomer", "ok_zoomer", "wi_zoom"]),
    "simple-voice-chat":     ("qol",      ["voicechat", "plasmovoice"]),
    "ping-wheel":            ("qol",      ["pingwheel", "ping-wheel"]),
    "no-chat-reports":       ("qol",      ["nochatreports"]),
    "modmenu":               ("qol",      ["modmenu", "catalogue"]),
    "controlling":           ("qol",      ["controlling"]),
    "betterf3":              ("qol",      ["betterf3"]),
    "better-third-person":   ("qol",      ["betterthirdperson"]),
    "clumps":                ("qol",      ["clumps"]),
}
_PERF_COMMON = ["ferrite-core", "modernfix", "memoryleakfix", "immediatelyfast", "entityculling", "moreculling",
                "modelfix", "dynamic-fps", "badoptimizations", "fast-ip-ping"]
SETS = {
    "fabric":   ["fabric-api", "sodium", "indium", "lithium"] + _PERF_COMMON +
                ["krypton", "sodium-extra", "reeses-sodium-options", "iris", "essential"],
    "quilt":    ["fabric-api", "sodium", "indium", "lithium"] + _PERF_COMMON +
                ["krypton", "sodium-extra", "reeses-sodium-options", "iris", "essential"],
    "neoforge": ["sodium", "lithium"] + _PERF_COMMON + ["sodium-extra", "reeses-sodium-options", "iris", "essential"],
    "forge":    ["embeddium"] + _PERF_COMMON + ["oculus", "essential"],
}
# Indium adds the Fabric Rendering API to Sodium 0.5 (Minecraft 1.20.x and older). Sodium 0.6+ (1.21+)
# has it built in and Indium breaks it - only offer Indium below this game version.
INDIUM_BELOW = (1, 21)
# on (Neo)Forge, a mod that needs these is a Fabric mod run through Sinytra Connector - skipped
CONNECTOR_DEPS = {"connector", "forgified-fabric-api", "sinytra-connector"}

# offered, not ticked; (group title, [slugs]) - a slug missing for the loader/version is simply skipped
QOL_GROUPS = [
    ("ข้อมูลไอเทมและสูตร", ["jei", "jade", "appleskin", "enchantment-descriptions", "shulkerboxtooltip"]),
    ("ช่องเก็บของ", ["mouse-tweaks", "crafting-tweaks", "clumps"]),
    ("แผนที่", ["xaeros-minimap", "xaeros-world-map"]),
    ("ภาพและเสียง", ["continuity", "lambdynamiclights", "sodium-dynamic-lights", "entitytexturefeatures",
                     "entity-model-features", "sound-physics-remastered", "zoomify"]),
    ("เล่นกับเพื่อน", ["simple-voice-chat", "ping-wheel", "no-chat-reports"]),
    ("หน้าจอและการตั้งค่า", ["modmenu", "controlling", "betterf3", "better-third-person"]),
]
QOL = [s for _, group in QOL_GROUPS for s in group]
# loader-specific choice between two mods doing the same job (never both)
PREFER = {"fabric": {"sodium-dynamic-lights"}, "quilt": {"sodium-dynamic-lights"},
          "forge": {"lambdynamiclights", "modmenu"}, "neoforge": {"lambdynamiclights", "modmenu"}}

DESC = {
    "badoptimizations": "ลดงานเบื้องหลังที่ไม่จำเป็น ให้ FPS ลื่นขึ้น", "moreculling": "ไม่วาดบล็อกที่มองไม่เห็น ช่วยให้ FPS สูงขึ้น",
    "memoryleakfix": "แก้ปัญหาแรมรั่วเมื่อเล่นนานๆ", "modelfix": "แก้รอยต่อโมเดลไอเทมและบล็อกที่แสดงผิดเพี้ยน",
    "krypton": "ลดภาระเครือข่าย เล่นออนไลน์ลื่นขึ้น", "fast-ip-ping": "หน้ารายชื่อเซิร์ฟเวอร์โหลดค่า ping เร็วขึ้น",
    "indium": "ช่วยให้ Sodium รุ่นนี้ใช้กับม็อดที่ต้องการ Fabric Rendering API ได้",
    "jei": "ดูสูตรคราฟต์และค้นหาไอเทม", "jade": "เล็งบล็อกหรือม็อบแล้วบอกชื่อ พร้อมบอกว่ามาจากม็อดไหน",
    "appleskin": "แสดงค่าความอิ่มที่อาหารแต่ละอย่างให้", "enchantment-descriptions": "อธิบายความสามารถของเอนชานต์แต่ละแบบ",
    "shulkerboxtooltip": "ชี้เมาส์ที่ Shulker Box แล้วเห็นของข้างในโดยไม่ต้องเปิด", "mouse-tweaks": "ลากเมาส์เพื่อย้ายหรือแจกของในช่องเก็บของได้รวดเร็ว",
    "crafting-tweaks": "เพิ่มปุ่มหมุน ล้าง และกระจายของในโต๊ะคราฟต์", "clumps": "รวมลูก XP เป็นก้อนเดียว ช่วยลดอาการแลค",
    "xaeros-minimap": "แผนที่ขนาดเล็กที่มุมจอ", "xaeros-world-map": "แผนที่โลกแบบเต็มจอ (กด M)",
    "continuity": "ทำให้กระจกและบล็อกต่อกันเป็นผืนเดียว (Connected Textures)", "lambdynamiclights": "ถือคบเพลิงหรือแหล่งแสงแล้วรอบตัวสว่างตาม",
    "sodium-dynamic-lights": "ถือคบเพลิงหรือแหล่งแสงแล้วรอบตัวสว่างตาม", "entitytexturefeatures": "ให้รีซอร์สแพ็กเปลี่ยนลายม็อบได้หลากหลาย",
    "entity-model-features": "ให้รีซอร์สแพ็กเปลี่ยนโมเดลม็อบได้ (เช่น Fresh Animations)",
    "sound-physics-remastered": "เสียงก้องและสะท้อนตามสภาพแวดล้อม สมจริงขึ้น", "zoomify": "ซูมภาพได้เหมือนกล้องส่องทางไกล",
    "simple-voice-chat": "คุยด้วยเสียงในเกม (เพื่อนและเซิร์ฟเวอร์ต้องลงด้วย)", "ping-wheel": "ปักหมุดบอกตำแหน่งให้เพื่อนเห็น",
    "no-chat-reports": "ปิดระบบรายงานแชทของ Mojang", "modmenu": "เมนูดูรายชื่อและตั้งค่าม็อด (Fabric)",
    "controlling": "ค้นหาปุ่มลัดในหน้าตั้งค่าปุ่มได้ง่าย", "betterf3": "จัดหน้าข้อมูล F3 ใหม่ให้อ่านง่าย", "better-third-person": "หมุนกล้องรอบตัวละครได้อิสระในมุมบุคคลที่ 3",
}
WHAT = {
    "render": "เรนเดอร์เร็วขึ้น ให้ FPS สูงขึ้น", "logic": "ลดภาระการประมวลผลของโลก", "memory": "ใช้แรมน้อยลงและโหลดเกมเร็วขึ้น",
    "idle": "ลด FPS อัตโนมัติเมื่อสลับไปหน้าต่างอื่น", "settings": "เพิ่มตัวเลือกตั้งค่ากราฟิก", "shaders": "รองรับการใช้ shader",
    "social": "เล่นกับเพื่อนผ่านระบบเชิญ พร้อมสกินและของตกแต่ง", "library": "ไลบรารีที่ม็อดอื่นต้องใช้",
    "network": "ปรับปรุงการเชื่อมต่อเครือข่าย", "fix": "แก้บั๊กของเกม", "qol": "ม็อดสามัญประจำบ้าน",
}


# ---------------------------------------------------------------- instance

def detect(inst):
    """-> dict(mc, loader, mods_dir)"""
    info = {"mc": None, "loader": None, "mods_dir": None}
    p = os.path.join(inst, "minecraftinstance.json")                     # CurseForge
    if os.path.exists(p):
        d = json.load(open(p, encoding="utf-8-sig"))
        info["mc"] = d.get("gameVersion")
        name = ((d.get("baseModLoader") or {}).get("name") or "").lower()
        info["loader"] = next((l for l in ("neoforge", "forge", "fabric", "quilt") if name.startswith(l)), None)
        info["mods_dir"] = os.path.join(inst, "mods")
    p = os.path.join(inst, "mmc-pack.json")                              # Prism / MultiMC
    if os.path.exists(p) and not info["mc"]:
        for c in json.load(open(p, encoding="utf-8-sig")).get("components", []):
            uid = c.get("uid", "")
            if uid == "net.minecraft":
                info["mc"] = c.get("version")
            for key, l in (("net.neoforged", "neoforge"), ("net.minecraftforge", "forge"),
                           ("net.fabricmc.fabric-loader", "fabric"), ("org.quiltmc.quilt-loader", "quilt")):
                if uid == key:
                    info["loader"] = l
        for sub in (".minecraft", "minecraft"):
            if os.path.isdir(os.path.join(inst, sub)):
                info["mods_dir"] = os.path.join(inst, sub, "mods")
    if info["mods_dir"] is None and os.path.isdir(os.path.join(inst, "mods")):
        info["mods_dir"] = os.path.join(inst, "mods")
    return info


def installed_mod_ids(mods_dir):
    """mod ids of every jar in mods/ (fabric.mod.json, quilt.mod.json, mods.toml, neoforge.mods.toml)"""
    ids, optifine = {}, False
    for jar in glob.glob(os.path.join(mods_dir, "*.jar")):
        if "optifine" in os.path.basename(jar).lower():
            optifine = True
        try:
            z = zipfile.ZipFile(jar)
        except Exception:
            continue
        names = set(z.namelist())
        found = []
        try:
            if "fabric.mod.json" in names:
                found.append(json.loads(z.read("fabric.mod.json").decode("utf-8-sig"), strict=False).get("id"))
            if "quilt.mod.json" in names:
                found.append(json.loads(z.read("quilt.mod.json").decode("utf-8-sig"))["quilt_loader"]["id"])
        except Exception:
            pass
        for toml in ("META-INF/mods.toml", "META-INF/neoforge.mods.toml"):
            if toml in names:
                found += re.findall(r'modId\s*=\s*"([^"]+)"', z.read(toml).decode("utf-8", "replace"))
        if "optifine" in [f.lower() for f in found if f]:
            optifine = True
        for f in found:
            if f:
                ids[f.lower()] = os.path.basename(jar)
    return ids, optifine


# ---------------------------------------------------------------- modrinth

def api(path, **params):
    q = urllib.parse.urlencode({k: json.dumps(v) if isinstance(v, list) else v for k, v in params.items()})
    url = "%s%s%s" % (API, path, "?" + q if q else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as r:
        return json.load(r)


def best_version(project, loader, mc):
    vs = api("/project/%s/version" % project, loaders=[loader], game_versions=[mc])
    if not vs:
        return None
    rel = [v for v in vs if v.get("version_type") == "release"]
    pick = sorted(rel or vs, key=lambda v: v["date_published"], reverse=True)[0]
    return pick


def api_post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers=dict(HEADERS, **{"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def projects(keys):
    """Bulk project lookup by slug or id -> {key: project}"""
    out, keys = {}, list(dict.fromkeys(k for k in keys if k))
    for i in range(0, len(keys), 80):
        chunk = keys[i:i + 80]
        for pj in api("/projects", ids=chunk):
            for k in chunk:
                if k in (pj["id"], pj["slug"]):
                    out[k] = pj
    return out


def installed_projects(mods_dir):
    """Ask Modrinth which projects the jars in mods/ are (by sha1).
    -> {project_id: {"file": jar, "incompatible": [project ids its version declares]}}"""
    hashes = {}
    for jar in glob.glob(os.path.join(mods_dir, "*.jar")):
        try:
            hashes[hashlib.sha1(open(jar, "rb").read()).hexdigest()] = os.path.basename(jar)
        except OSError:
            pass
    if not hashes:
        return {}
    try:
        found = api_post("/version_files", {"hashes": list(hashes), "algorithm": "sha1"})
    except Exception:
        return {}
    out = {}
    for h, v in found.items():
        out[v["project_id"]] = {"file": hashes.get(h, "?"),
                                "incompatible": [d["project_id"] for d in v.get("dependencies", [])
                                                 if d.get("dependency_type") == "incompatible" and d.get("project_id")]}
    return out


def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


def resolve(info, want_shaders=True, want_essential=True, want_qol=True):
    """-> (plan, skipped). plan entries: slug, title, version, file, url, sha1, role, requires, optional ...
    skipped: (slug, reason)."""
    loader, mc = info["loader"], info["mc"]
    mods_dir = info["mods_dir"] or ""
    have, optifine = installed_mod_ids(mods_dir) if os.path.isdir(mods_dir) else ({}, False)
    have_proj = installed_projects(mods_dir) if os.path.isdir(mods_dir) else {}
    plan, skipped = [], []

    want = [s for s in SETS[loader] if (want_shaders or MODS[s][0] != "shaders") and (want_essential or s != "essential")]
    if "indium" in want and vtuple(mc) >= INDIUM_BELOW:
        want.remove("indium")
    if want_qol:
        want += [s for s in QOL if s not in want and s not in PREFER.get(loader, set())]
    if optifine:
        skipped.append(("render/shaders mods", "พบ OptiFine ในโฟลเดอร์ mods ซึ่งใช้ร่วมกับ Sodium/Embeddium/Iris/Oculus ไม่ได้"))
        want = [s for s in want if MODS[s][0] not in ("render", "shaders", "settings")]

    info_by = {}
    seen, queue = set(), list(want)
    while queue:
        batch = [s for s in dict.fromkeys(queue) if s not in seen]
        queue = []
        seen.update(batch)
        try:
            info_by.update(projects(batch))
        except Exception as e:
            for s in batch:
                skipped.append((s, "เชื่อมต่อ Modrinth ไม่ได้: %s" % e))
            continue
        todo = []
        for slug in batch:
            pj = info_by.get(slug)
            ids = MODS.get(slug, (None, [slug]))[1]
            already = next((have[i] for i in ids if i in have), None)
            if not already and pj and pj["id"] in have_proj:
                already = have_proj[pj["id"]]["file"]
            if already:
                skipped.append((slug, "มีอยู่แล้ว: %s" % already))
            elif not pj:
                skipped.append((slug, "ไม่พบใน Modrinth"))
            else:
                todo.append(slug)
        with ThreadPoolExecutor(max_workers=8) as ex:
            versions = dict(zip(todo, ex.map(lambda s: _safe_version(s, loader, mc), todo)))
        dep_ids = []
        for slug in todo:
            v = versions[slug]
            if isinstance(v, Exception):
                skipped.append((slug, "เชื่อมต่อ Modrinth ไม่ได้: %s" % v))
                continue
            if not v:
                skipped.append((slug, "ยังไม่มีไฟล์สำหรับ %s %s" % (loader, mc)))
                continue
            pj = info_by[slug]
            f = next((x for x in v["files"] if x.get("primary")), v["files"][0])
            deps = v.get("dependencies", [])
            plan.append({
                "slug": slug, "id": pj["id"], "title": pj.get("title") or slug, "icon_url": pj.get("icon_url"),
                "page": "https://modrinth.com/%s/%s" % (pj.get("project_type") or "mod", pj["slug"]),
                "curseforge": "https://www.curseforge.com/minecraft/search?" + urllib.parse.urlencode(
                    {"page": 1, "pageSize": 20, "sortBy": "relevancy", "class": "mc-mods", "search": pj.get("title") or slug}),
                "downloads": pj.get("downloads", 0),
                "version": v["version_number"], "type": v.get("version_type"),
                "file": f["filename"], "url": f["url"], "sha1": f["hashes"].get("sha1"),
                "role": MODS.get(slug, ("dependency", []))[0],
                "client_side": pj.get("client_side"), "server_side": pj.get("server_side"),
                "incompatible": [d["project_id"] for d in deps if d.get("dependency_type") == "incompatible" and d.get("project_id")],
                "requires_ids": [d["project_id"] for d in deps if d.get("dependency_type") == "required" and d.get("project_id")],
            })
            dep_ids += plan[-1]["requires_ids"]
        if dep_ids:
            try:
                dep_info = projects(dep_ids)
            except Exception:
                dep_info = {}
            for i in dep_ids:
                if i in dep_info:
                    info_by[dep_info[i]["slug"]] = dep_info[i]
                    if dep_info[i]["slug"] not in seen:
                        queue.append(dep_info[i]["slug"])
    id_to_slug = {pj["id"]: s for s, pj in info_by.items()}
    for p in plan:
        p["requires"] = [id_to_slug.get(i, i) for i in p.pop("requires_ids")]

    # optional = quality-of-life mods, and dependencies needed only by optional mods
    for p in plan:
        p["optional"] = p["slug"] in QOL
    for _ in range(3):
        for p in plan:
            if p["slug"] in QOL or p["slug"] in SETS[loader]:
                continue
            needers = [q for q in plan if p["slug"] in q["requires"]]
            if needers and all(q["optional"] for q in needers):
                p["optional"] = True

    # incompatibilities declared on Modrinth: planned vs planned, planned vs installed (both directions)
    final = []
    for p in plan:
        why = []
        why += ["%s ที่ลงอยู่แล้ว (%s)" % (id_to_slug.get(i, i), have_proj[i]["file"]) for i in p["incompatible"] if i in have_proj]
        why += ["%s ที่ลงอยู่แล้ว" % have_proj[i]["file"] for i in have_proj if p["id"] in have_proj[i]["incompatible"]]
        why += [q["slug"] for q in final if q["id"] in p["incompatible"] or p["id"] in q["incompatible"]]
        if why:
            skipped.append((p["slug"], "ใช้ร่วมกับ %s ไม่ได้" % ", ".join(why)))
        else:
            final.append(p)
    # Sinytra Connector runs Fabric mods on (Neo)Forge - still beta and a common crash source
    if loader in ("forge", "neoforge"):
        risky = [p for p in final if p["slug"] in CONNECTOR_DEPS]
        if risky:
            final = [p for p in final if p["slug"] not in CONNECTOR_DEPS]
            for p in list(final):
                if any(r in CONNECTOR_DEPS for r in p["requires"]):
                    final.remove(p)
                    skipped.append((p["slug"], "ต้องใช้ Sinytra Connector (ตัวรันม็อด Fabric บน Forge) ซึ่งยังเป็นรุ่นทดลอง เสี่ยงเกมพัง"))
    # a mod whose requirement was dropped cannot be installed either; repeat until stable
    present = {s for s, why in skipped if why.startswith("มีอยู่แล้ว")}
    while True:
        names = {p["slug"] for p in final}
        bad = [p for p in final if any(r not in names and r not in present for r in p["requires"])]
        if not bad:
            break
        for p in bad:
            final.remove(p)
            skipped.append((p["slug"], "ต้องใช้ %s ซึ่งติดตั้งไม่ได้" % ", ".join(r for r in p["requires"] if r not in names and r not in present)))
    # drop dependencies nobody needs any more (their only user was removed above)
    while True:
        needed = set(want) | {r for p in final for r in p["requires"]}
        orphans = [p for p in final if p["slug"] not in needed]
        if not orphans:
            break
        for p in orphans:
            final.remove(p)
    set_sides(final)
    return final, skipped


# Who needs a mod when friends join your world through Essential (your game is then the server):
#   both   - every player must have it          client - only matters on your own screen
#   either - runs on either side, friends need not have it    server - only the world host needs it
# From Modrinth's client_side/server_side, corrected where that answer misleads for playing together.
SIDE_OVERRIDE = {
    "essential": "both",            # Modrinth says server: unsupported, but invites need Essential on every player
    "simple-voice-chat": "both",    # optional/optional on Modrinth; the host and everyone who wants to talk need it
}
SIDE_RANK = {"both": 4, "server": 3, "either": 2, "client": 1, "unknown": 0}
SIDE_SHORT = {"both": "ทุกคนต้องลง", "server": "เฉพาะคนเปิดโลก", "either": "เพื่อนไม่ต้องลง",
              "client": "เพื่อนไม่ต้องลง", "unknown": "ไม่ระบุ"}


def side_of(slug, client, server):
    if slug in SIDE_OVERRIDE:
        return SIDE_OVERRIDE[slug]
    if client == "required" and server == "required":
        return "both"
    if server == "unsupported":
        return "client"
    if client == "unsupported":
        return "server"
    if client in ("required", "optional") and server in ("required", "optional"):
        return "either"
    return "unknown"


def set_sides(plan):
    """p["side"] for each entry. A library takes the strongest side of the mods that need it
    (Bookshelf is 'both' on Modrinth, but it only has to be where Enchantment Descriptions is)."""
    for p in plan:
        p["side"] = side_of(p["slug"], p.get("client_side"), p.get("server_side"))
    for _ in range(4):                  # libraries of libraries
        for p in plan:
            if p["slug"] in MODS:
                continue
            needers = [q["side"] for q in plan if p["slug"] in q["requires"]]
            if needers:
                p["side"] = max(needers, key=SIDE_RANK.get)


def _safe_version(slug, loader, mc):
    try:
        return best_version(slug, loader, mc)
    except Exception as e:
        return e


# ---------------------------------------------------------------- commands

def print_plan(info, plan, skipped):
    print("instance: Minecraft %s, %s, mods: %s" % (info["mc"], info["loader"], info["mods_dir"]))
    main = [p for p in plan if not p.get("optional")]
    extra = [p for p in plan if p.get("optional")]
    for title, rows, mark in (("จะลง %d ไฟล์:" % len(main), main, "+"),
                              ("ม็อดสามัญประจำบ้าน (เลือกได้ ใส่ --with <ชื่อ> หรือ --with-qol):", extra, "?")):
        if not rows:
            continue
        print("\n" + title)
        for p in rows:
            tag = "" if p["type"] == "release" else " [%s]" % p["type"]
            what = DESC.get(p["slug"]) or WHAT.get(p["role"], "ม็อดที่ต้องลงคู่")
            print("  %s %-22s %-30s [%s] %s%s" % (mark, p["slug"], p["version"], SIDE_SHORT[p["side"]], what, tag))
    shared = ["%s (%s)" % (p["slug"], SIDE_SHORT[p["side"]]) for p in main if p["side"] in ("both", "server")]
    if shared:
        print("\nเล่นกับเพื่อนผ่าน Essential: " + ", ".join(shared) + " · ตัวที่เหลือเพื่อนไม่ต้องลงตาม")
    if skipped:
        print("\nข้าม:")
        for s, why in skipped:
            print("  - %-22s %s" % (s, why))


def need_instance(a):
    """Instance mode reads version/loader from the instance; --mc/--loader override them.
    Folder mode (--out) needs --mc and --loader and downloads into <out>/mods."""
    if getattr(a, "out", None):
        if not (a.mc and a.loader):
            sys.exit("--out ต้องใส่ --mc และ --loader ด้วย เช่น --mc 1.21.1 --loader neoforge")
        a.instance = a.out
        info = {"mc": a.mc, "loader": a.loader, "mods_dir": os.path.join(a.out, "mods")}
    else:
        if not a.instance:
            sys.exit("ต้องใส่ --instance <โฟลเดอร์เกม> หรือ --out <โฟลเดอร์> --mc <เวอร์ชัน> --loader <loader>")
        info = detect(a.instance)
        real = (info["mc"], info["loader"])
        if getattr(a, "mc", None):
            info["mc"] = a.mc
        if getattr(a, "loader", None):
            info["loader"] = a.loader
        if real[0] and (info["mc"], info["loader"]) != real and not getattr(a, "force", False):
            sys.exit("instance นี้เป็น %s %s แต่สั่งให้ใช้ %s %s - ม็อดคนละเวอร์ชันจะทำให้เกมเปิดไม่ขึ้น "
                     "(ถ้าตั้งใจจริง ใส่ --force หรือใช้ --out เพื่อโหลดไปไว้ที่อื่น)" % (real + (info["mc"], info["loader"])))
    if not info["mc"] or not info["loader"]:
        sys.exit("อ่านเวอร์ชัน/loader ของ instance ไม่ได้: %s (ต้องมี minecraftinstance.json หรือ mmc-pack.json) "
                 "- ใส่ --mc และ --loader เองได้" % a.instance)
    if info["loader"] not in SETS:
        sys.exit("ยังไม่รองรับ loader: %s" % info["loader"])
    return info


def cmd_plan(a):
    info = need_instance(a)
    plan, skipped = resolve(info, not a.no_shaders, not a.no_essential)
    print_plan(info, plan, skipped)


def cmd_install(a):
    info = need_instance(a)
    plan, skipped = resolve(info, not a.no_shaders, not a.no_essential)
    print_plan(info, plan, skipped)
    wanted = set(x.strip() for x in (a.with_ or "").split(",") if x.strip())
    pick = {p["slug"] for p in plan if not p.get("optional") or a.with_qol or p["slug"] in wanted}
    changed = True
    while changed:                       # pull in whatever the picked mods require
        changed = False
        for p in plan:
            if p["slug"] in pick:
                for r in p["requires"]:
                    if r not in pick and any(q["slug"] == r for q in plan):
                        pick.add(r)
                        changed = True
    plan = [p for p in plan if p["slug"] in pick]
    if not plan:
        print("\nไม่มีอะไรต้องลง")
        return
    tag, added = install_plan(info, plan, a.instance, print)
    print("\nเสร็จ %d ไฟล์ บันทึกไว้ที่ %s\\%s.json  (ย้อนกลับ: perf.py restore --instance ... --install %s)"
          % (len(added), STATE_DIR, tag, tag))


def install_plan(info, plan, instance, log=print):
    """Download every entry of plan into mods/, verify sha1, record the install. -> (tag, added)"""
    os.makedirs(info["mods_dir"], exist_ok=True)
    tag = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    added = []
    for p in plan:
        dst = os.path.join(info["mods_dir"], p["file"])
        if os.path.exists(dst):
            log("  มีไฟล์ชื่อนี้อยู่แล้ว ข้าม: %s" % p["file"])
            continue
        with urllib.request.urlopen(urllib.request.Request(p["url"], headers=HEADERS), timeout=120) as r:
            data = r.read()
        if p["sha1"] and hashlib.sha1(data).hexdigest() != p["sha1"]:
            raise RuntimeError("ไฟล์ %s เสีย (hash ไม่ตรง) - หยุด ไม่ได้ลงไฟล์นี้" % p["file"])
        with open(dst + ".tmp", "wb") as f:
            f.write(data)
        os.replace(dst + ".tmp", dst)
        added.append(dict(p, path=os.path.relpath(dst, instance)))
        log("  ลงแล้ว: %s" % p["file"])
        # record after every file, so a crash half way still leaves a restorable list
        sd = os.path.join(instance, STATE_DIR)
        os.makedirs(sd, exist_ok=True)
        json.dump({"time": tag, "mc": info["mc"], "loader": info["loader"], "added": added},
                  open(os.path.join(sd, tag + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return tag, added


def restore_install(instance, name, log=print):
    f = os.path.join(instance, STATE_DIR, name + ".json")
    d = json.load(open(f, encoding="utf-8"))
    for x in d["added"]:
        p = os.path.join(instance, x["path"])
        if os.path.exists(p):
            os.remove(p)
            log("ลบ %s" % x["path"])
    os.rename(f, f + ".restored")


def cmd_versions(a):
    """Count, per game version, how many mods of the loader's set have a file for it."""
    count, total = {}, 0
    for slug in SETS[a.loader]:
        try:
            pv = api("/project/%s" % slug)
        except Exception:
            continue
        if a.loader not in pv.get("loaders", []):
            continue
        total += 1
        for gv in pv.get("game_versions", []):
            if re.fullmatch(r"\d+(\.\d+)+", gv):
                count.setdefault(gv, []).append(slug)
    def key(v):
        return tuple(int(x) for x in v.split("."))
    rows = sorted(count.items(), key=lambda x: (len(x[1]), key(x[0])), reverse=True)[:a.top]
    print("%s: เวอร์ชันเกม | มีม็อดในชุดกี่ตัว (จาก %d)" % (a.loader, len(SETS[a.loader])))
    for gv, slugs in rows:
        missing = [s for s in SETS[a.loader] if s not in slugs]
        print("  %-8s %2d/%d  %s" % (gv, len(slugs), len(SETS[a.loader]), ("ขาด: " + ", ".join(missing)) if missing else "ครบ"))
    print("(นับจากรายการเวอร์ชันของแต่ละโปรเจกต์ - ตอนลงจริงยังเช็กไฟล์ทีละตัวอีกรอบ)")


def installs(inst):
    return sorted(glob.glob(os.path.join(inst, STATE_DIR, "*.json")))


def cmd_list(a):
    for f in installs(a.instance):
        d = json.load(open(f, encoding="utf-8"))
        print("%s  %s %s  %d files: %s" % (os.path.basename(f)[:-5], d["loader"], d["mc"], len(d["added"]),
                                           ", ".join(x["slug"] for x in d["added"])))


def cmd_restore(a):
    files = installs(a.instance)
    if a.install:
        files = [f for f in files if os.path.basename(f)[:-5] == a.install]
    if not files:
        sys.exit("ไม่พบประวัติการลงของเครื่องมือนี้")
    for f in reversed(files):
        d = json.load(open(f, encoding="utf-8"))
        for x in d["added"]:
            p = os.path.join(a.instance, x["path"])
            if os.path.exists(p):
                os.remove(p)
                print("ลบ %s" % x["path"])
        os.rename(f, f + ".restored")
    print("ย้อนกลับเรียบร้อย")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("versions", help="which game versions have the set for a loader")
    v.add_argument("--loader", required=True, choices=sorted(SETS))
    v.add_argument("--top", type=int, default=15)
    v.set_defaults(fn=cmd_versions)
    for name, fn in (("plan", cmd_plan), ("install", cmd_install), ("list", cmd_list), ("restore", cmd_restore)):
        p = sub.add_parser(name)
        p.add_argument("--instance", required=name not in ("plan", "install"))
        if name in ("plan", "install"):
            p.add_argument("--out", help="download into <out>/mods instead of an instance (needs --mc and --loader)")
            p.add_argument("--mc", help="game version, e.g. 1.20.1 (default: read from the instance)")
            p.add_argument("--loader", choices=sorted(SETS), help="mod loader (default: read from the instance)")
            p.add_argument("--force", action="store_true", help="allow a version/loader different from the instance")
            p.add_argument("--no-shaders", action="store_true", help="skip Iris/Oculus")
            p.add_argument("--no-essential", action="store_true", help="skip Essential")
            p.add_argument("--with", dest="with_", help="also install these quality-of-life mods, comma list (e.g. jei,appleskin)")
            p.add_argument("--with-qol", action="store_true", help="also install every quality-of-life mod")
        if name == "restore":
            p.add_argument("--install", help="one install name from `list` (default: all)")
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
