---
name: mc-perf-mods
description: Add the standard performance and visual mods (Sodium/Embeddium, Lithium, FerriteCore, ModernFix, ImmediatelyFast, Entity Culling, Dynamic FPS, Iris/Oculus) plus Essential for playing with friends to a Minecraft instance, choosing the right files for its loader (Forge, NeoForge, Fabric, Quilt) and game version from Modrinth. Use when the user plays a single mod or a small custom instance and wants it to run smoother or look better, asks which performance mods to add, or wants a ready mod set for a chosen game version.
---

# Minecraft performance mods

Tool: `scripts/perf.py` (Python 3.8+, standard library only, uses the public Modrinth API - no key).
It only ADDS jars to `mods/`; it never replaces or deletes a mod it did not add. Every install is
recorded in `<instance>/.mc-perf-mods/<time>.json`, and `restore` removes exactly those files.

Talk to the user in Thai.

## Steps

The user can also do everything in a window: double-click `เปิดโปรแกรม.bat` (installs pywebview on first run,
then runs `scripts/perf_web.py`, an HTML window in `scripts/ui/index.html`; without pywebview it falls back to
the Tk window `scripts/perf_gui.py`). A `bg.gif`/`bg.webp`/`bg.png`/`bg.jpg`/`bg.mp4`/`bg.webm` next to the bat
becomes the window background. Both windows offer:
folder box + browse, check, collapsible sections (performance set ticked, QoL groups unticked, libraries
ticked automatically, skipped list), search box, tick/untick mods, install, restore. Icons need Pillow
(`pip install pillow`); without it rows show letters. Suggest the window when the user prefers clicking.


1. Find the instance folder (CurseForge: `...\Instances\<name>`, the folder with `minecraftinstance.json`;
   Prism/MultiMC: the folder with `mmc-pack.json`). Ask the user which instance if it is not clear.
2. `python scripts/perf.py plan --instance <dir>` - shows game version and loader read from the instance,
   the files it would add and the ones it skips (already present, no file for this version, OptiFine
   conflict). Options: `--no-shaders` (skip Iris/Oculus), `--no-essential`.
3. Show the user the plan and ask before installing. The game must be closed.
4. `python scripts/perf.py install --instance <dir>` (same options). Tell the user the install name it
   prints; `restore --instance <dir> --install <name>` undoes it.
5. Tell the user what to check in game: the mod list loads, Video Settings show the Sodium/Embeddium
   menu, and (if shaders were added) Video Settings → Shader Packs exists. Essential shows its own
   sign-in screen the first time; friends need Essential too to join through invites.

Done when install printed its files and the user knows the restore command.

## Choosing a game version

- `python scripts/perf.py versions --loader forge` lists game versions by how many mods of the set exist
  for them - use it when the user is choosing which version to play.
- `plan`/`install` take `--mc <version> --loader <loader>` to override what the instance says. A mismatch
  with the instance is refused (mods for another version stop the game) unless `--force`.
- `--out <folder> --mc <version> --loader <loader>` downloads the set into `<folder>/mods` without an
  instance, for preparing a set before creating the instance.

## The sets (edit `SETS` / `MODS` in perf.py to change them)

| loader | mods |
|---|---|
Every loader: FerriteCore, ModernFix, Memory Leak Fix, ImmediatelyFast, Entity Culling, More Culling,
Model Gap Fix, Dynamic FPS, BadOptimizations, Fast IP Ping, Essential. Plus:

| loader | mods |
|---|---|
| Fabric / Quilt | Fabric API, Sodium, Indium (game below 1.21 only), Lithium, Krypton, Sodium Extra, Reese's Sodium Options, Iris |
| NeoForge | Sodium, Lithium, Sodium Extra, Reese's Sodium Options, Iris |
| Forge | Embeddium, Oculus |

Required dependencies of each file are added automatically. A mod with no file for the version is skipped
and reported.

## Quality-of-life mods (offered, never ticked by default)

Grouped in `QOL_GROUPS` (the window shows each group as a collapsible sub-section): item info (JEI, Jade,
AppleSkin, Enchantment Descriptions, Shulker Box Tooltip), inventory (Mouse Tweaks, Crafting Tweaks, Clumps),
maps (Xaero's Minimap and World Map), visuals and sound (Continuity, LambDynamicLights on Fabric / Sodium
Dynamic Lights on Forge+NeoForge, ETF, EMF, Sound Physics Remastered, Zoomify), friends (Simple Voice Chat,
Ping Wheel, No Chat Reports), screens (Mod Menu on Fabric, Controlling, BetterF3, Better Third Person).
`plan` lists them separately; `install` adds them only with `--with jei,appleskin` or `--with-qol`, plus
whatever they require. Ask the user which ones they want; Simple Voice Chat also needs the server and
friends to have it.

## Conflict rules (in `resolve()`)

- Equivalents count as present (second field of `MODS`): Sodium/Embeddium/Rubidium, Iris/Oculus,
  Lithium/Canary/Radium, JEI/REI/EMI, Jade/WTHIT/HWYLA, Xaero/JourneyMap/VoxelMap, the dynamic-lights forks,
  Zoomify/Ok Zoomer, Simple Voice Chat/Plasmo Voice, Mod Menu/Catalogue. `PREFER` picks one of two
  same-job mods per loader.
- Installed jars are identified on Modrinth by sha1; each version's declared `incompatible` dependencies
  are checked both ways (new vs installed, new vs new). Conflicting mods are skipped with the reason.
- Indium only below 1.21 (`INDIUM_BELOW`): it breaks Sodium 0.6+.
- On Forge/NeoForge, a mod requiring Sinytra Connector / Forgified Fabric API is skipped (beta, risky).
- A mod whose requirement was skipped is skipped too; dependencies left without a user are dropped.
- C2ME and Distant Horizons are deliberately left out: they often conflict in large modpacks.

## Things to know

- CurseForge lists these jars as manually added and will not update them; run `plan` again later to see
  newer files (delete the old jar first, or `restore` then `install`).
- OptiFine conflicts with Sodium/Embeddium/Iris/Oculus: the tool skips the render, settings and shader
  mods when it finds OptiFine and says so.
- A file marked `[beta]` in the plan is the newest available for that version (no release exists).
- Each plan entry has `side` (`set_sides` in perf.py): `both` (every player needs it), `server` (world host only),
  `client` / `either` (friends need not install it). It comes from Modrinth's `client_side`/`server_side`,
  with `SIDE_OVERRIDE` for Essential and Simple Voice Chat; a library takes the strongest side of the mods
  that need it. When the user plays with friends through Essential, tell them which ticked mods are `both`.
- No-install build for people without Python: `python build_exe.py` (needs pyinstaller, pywebview, pillow on the
  build machine) makes `dist/MC-Perf-Mods.zip` - a folder with `MC-Perf-Mods.exe` (PyInstaller onedir; numpy, PIL
  and cryptography excluded). Dropping a modpack folder on the exe checks it right away. `build/` and `dist/` are
  git-ignored; share the zip (e.g. a GitHub Release), not the folder in git.
- Background: the window's "พื้นหลัง" button picks a picture/video (copied to `%APPDATA%\mc-perf-mods\bg.<ext>`,
  darkness saved in `settings.json` there); a `bg.*` next to the exe/bat still works as a fallback.
