import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import perf
import perf_gui


def project(slug):
    return {"slug": slug, "id": slug + "-project"}


def version(slug, pin=None):
    deps = []
    if slug == "indium":
        deps.append({"project_id": "sodium-project", "version_id": pin, "dependency_type": "required"})
    return {"id": slug + "-new", "version_number": "new", "files": [
        {"filename": slug + ".jar", "url": "unused", "hashes": {}}], "dependencies": deps}


class Resolution(unittest.TestCase):
    def test_candidate_jar_can_be_stricter_than_modrinth(self):
        import io

        def jar_bytes(metadata):
            raw = io.BytesIO()
            with zipfile.ZipFile(raw, "w") as archive:
                archive.writestr("fabric.mod.json", json.dumps(metadata))
            return raw.getvalue()

        sodium = self.mods / "sodium.jar"
        sodium.write_bytes(jar_bytes({"id": "sodium", "version": "0.5.3"}))
        ranges = {"iris": ["0.5.10", "0.5.11"], "sodium-extra": ">=0.5.6", "indium": "0.5.3"}
        plan = [{"slug": slug, "requires": ["sodium"], "url": "https://example.invalid/" + slug,
                 "sha1": None} for slug in ranges]

        def fetch(request, timeout):
            slug = request.full_url.rsplit("/", 1)[1]
            return io.BytesIO(jar_bytes({"depends": {"sodium": ranges[slug]}}))

        skipped = []
        with mock.patch.object(perf.urllib.request, "urlopen", fetch):
            allowed = perf._check_installed_sodium(sodium, plan, skipped)
        self.assertEqual([p["slug"] for p in allowed], ["indium"])
        self.assertEqual(set(dict(skipped)), {"iris", "sodium-extra"})

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.mods = Path(tmp.name)
        self.info = {"loader": "fabric", "mc": "1.20.1", "mods_dir": str(self.mods)}

    def resolve(self, wanted, installed=None, pin=None):
        def projects(keys):
            return {key: project(key.split("-project")[0]) for key in keys}

        with mock.patch.dict(perf.SETS, fabric=wanted), mock.patch.object(perf, "projects", projects), \
                mock.patch.object(perf, "installed_projects", return_value=installed or {}), \
                mock.patch.object(perf, "best_version", side_effect=lambda s, *_: version(s, pin)), \
                mock.patch.object(perf, "api", return_value=dict(version("sodium"), id=pin,
                                                                 loaders=["fabric"], game_versions=["1.20.1"])):
            plan, skipped = perf.resolve(self.info, want_qol=False)
        return [p["slug"] for p in plan], dict(skipped)

    def test_optifine_also_blocks_sodium_pulled_by_indium(self):
        (self.mods / "OptiFine.jar").touch()
        plan, skipped = self.resolve(["indium"])
        self.assertEqual(plan, [])
        self.assertIn("OptiFine", skipped["sodium"])
        self.assertIn("sodium", skipped["indium"])

    def test_required_version_of_installed_or_planned_sodium(self):
        for selected, expected in [("sodium-old", []), ("sodium-new", ["indium"])]:
            installed = {"sodium-project": {"version_id": selected, "file": "installed.jar", "incompatible": []}}
            self.assertEqual(self.resolve(["indium"], installed, pin="sodium-new")[0], expected)
        self.assertCountEqual(self.resolve(["sodium", "indium"], pin="sodium-old")[0], ["sodium", "indium"])
        self.assertEqual(self.resolve(["indium"], pin="sodium-old")[0], ["indium", "sodium"])
        self.assertEqual(self.resolve(["sodium", "indium"])[0], ["sodium", "indium"])

    def test_conflicting_pin_falls_back_to_older_release_without_pin(self):
        # Fabric 1.20.1: Indium pins Sodium 0.5.11, Iris 1.7.6 pins 0.5.12-beta.2, Iris 1.7.5 pins nothing
        def ver(slug, vid, pin=None, date="2024"):
            deps = [{"project_id": "sodium-project", "version_id": pin, "dependency_type": "required"}]
            return {"id": vid, "version_number": vid, "version_type": "release", "date_published": date,
                    "files": [{"filename": vid + ".jar", "url": "u", "hashes": {}}], "dependencies": deps}
        sodium = {"id": "sodium-11", "version_number": "0.5.11", "version_type": "release", "date_published": "2024",
                  "files": [{"filename": "s.jar", "url": "u", "hashes": {}}], "dependencies": [],
                  "loaders": ["fabric"], "game_versions": ["1.20.1"]}
        latest = {"indium": ver("indium", "indium-36", "sodium-11"), "iris": ver("iris", "iris-176", "sodium-12", "2025"),
                  "sodium": sodium}
        history = {"iris": [latest["iris"], ver("iris", "iris-175", None, "2024")]}

        def api(path, **_):
            if path.startswith("/project/"):
                return history.get(path.split("/")[2], [])
            return sodium if path.endswith("sodium-11") else dict(sodium, id="sodium-12")
        with mock.patch.dict(perf.SETS, fabric=["indium", "iris"]),                 mock.patch.object(perf, "projects", lambda keys: {k: project(k.split("-project")[0]) for k in keys}),                 mock.patch.object(perf, "installed_projects", return_value={}),                 mock.patch.object(perf, "best_version", side_effect=lambda s, *_: latest[s]),                 mock.patch.object(perf, "api", side_effect=api):
            plan, skipped = perf.resolve(self.info, want_qol=False)
        got = {p["slug"]: p["version"] for p in plan}
        self.assertEqual(got.get("iris"), "iris-175", (got, skipped))
        self.assertEqual(got.get("sodium"), "0.5.11")
        self.assertIn("indium", got)

    def test_unknown_installed_version_does_not_satisfy_pin(self):
        with zipfile.ZipFile(self.mods / "local.jar", "w") as archive:
            archive.writestr("fabric.mod.json", '{"id":"sodium"}')
        self.assertEqual(self.resolve(["indium"], pin="sodium-new")[0], [])

    def test_fallback_respects_installed_and_transitive_pins(self):
        def release(slug, vid, dep=None, pin=None):
            v = dict(version(slug), id=vid, project_id=slug + "-project", version_number=vid,
                     version_type="release", date_published="2025" if vid.endswith("new") else "2024",
                     loaders=["fabric"], game_versions=["1.20.1"])
            if dep:
                v["dependencies"] = [{"dependency_type": "required", "project_id": dep + "-project",
                                      "version_id": pin}]
            return v

        catalog = {
            "engine": [release("engine", "engine-new", "base", "base-old"), release("engine", "engine-old")],
            "addon": [release("addon", "addon-new", "base", "base-old"),
                      release("addon", "addon-old", "engine", "engine-new")],
            "ui": [release("ui", "ui-new", "addon")],
        }
        by_version = {v["id"]: v for versions in catalog.values() for v in versions}
        base = {"file": "base.jar", "version_id": "base-new", "incompatible": []}
        pinned = {"file": "existing.jar", "version_id": "existing-id", "incompatible": [],
                  "pins": {"engine-project": "engine-new"}}
        cases = [
            (["engine"], {"base-project": base, "existing-project": pinned}, set()),
            (["ui", "addon", "engine"], {"base-project": base}, {"engine-old"}),
            (["engine", "addon", "ui"], {"base-project": base}, {"engine-old"}),
        ]
        for wanted, installed, expected in cases:
            with self.subTest(wanted=wanted), mock.patch.dict(perf.SETS, fabric=wanted), \
                    mock.patch.object(perf, "installed_projects", return_value=installed), \
                    mock.patch.object(perf, "projects", side_effect=lambda keys: {
                        k: project(k.split("-project")[0]) for k in keys}), \
                    mock.patch.object(perf, "_safe_version", side_effect=lambda s, l, m, pin:
                                      by_version.get(pin) if pin else catalog[s][0]), \
                    mock.patch.object(perf, "api", side_effect=lambda path, **kw: catalog[path.split("/")[2]]):
                plan, _ = perf.resolve(self.info, want_qol=False)
                self.assertEqual({p["version_id"] for p in plan}, expected)

    def test_unavailable_optional_candidate_pin_keeps_the_shared_dependency(self):
        def release(slug, loader, mc, pin):
            if pin == "wrong-game":
                return None
            return version(slug, "wrong-game")

        with mock.patch.dict(perf.SETS, fabric=["indium", "sodium"]), \
                mock.patch.object(perf, "projects", side_effect=lambda keys: {
                    k: project(k.split("-project")[0]) for k in keys}), \
                mock.patch.object(perf, "_safe_version", side_effect=release):
            plan, skipped = perf.resolve(self.info, want_qol=False)
        self.assertEqual([p["slug"] for p in plan], ["sodium"])
        self.assertIn("wrong-game", dict(skipped)["indium"])

    def test_version_only_requirement_resolves_the_dependency_project(self):
        addon = version("indium", "sodium-old")
        addon["dependencies"][0]["project_id"] = None
        sodium = dict(version("sodium"), id="sodium-old", project_id="sodium-project",
                      loaders=["fabric"], game_versions=["1.20.1"])
        with mock.patch.dict(perf.SETS, fabric=["indium"]), \
                mock.patch.object(perf, "projects", side_effect=lambda keys: {
                    k: project(k.split("-project")[0]) for k in keys}), \
                mock.patch.object(perf, "best_version", return_value=addon), \
                mock.patch.object(perf, "api", return_value=sodium):
            plan, skipped = perf.resolve(self.info, want_qol=False)
        self.assertEqual(skipped, [])
        self.assertEqual({p["version_id"] for p in plan}, {"indium-new", "sodium-old"})

    def test_fresh_and_existing_prism_game_folders(self):
        (self.mods / "mmc-pack.json").write_text(json.dumps({"components": [
            {"uid": "net.minecraft", "version": "1.20.1"}, {"uid": "net.fabricmc.fabric-loader"}]}))
        for directory, expected in [(None, "minecraft"), (".minecraft", ".minecraft"), ("minecraft", "minecraft")]:
            if directory:
                (self.mods / directory).mkdir()
            self.assertEqual(perf.detect(str(self.mods))["mods_dir"], str(self.mods / expected / "mods"))

    def test_versions_counts_distinct_game_versions_for_requested_loader(self):
        files = [{"files": [{}], "game_versions": ["1.21.1"]}] * 2
        with mock.patch.dict(perf.SETS, neoforge=["sodium", "iris"]), \
                mock.patch.object(perf, "api", side_effect=[files, []]) as api, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            perf.cmd_versions(SimpleNamespace(loader="neoforge", top=10))
        self.assertEqual(api.call_args_list, [
            mock.call("/project/sodium/version", loaders=["neoforge"]),
            mock.call("/project/iris/version", loaders=["neoforge"])])
        self.assertRegex(output.getvalue(), r"1\.21\.1\s+1/2\s+ขาด: iris")

    def test_reselected_version_replaces_its_own_requirements(self):
        def release(slug, pin=None):
            value = version(slug)
            value["id"] = pin or slug + "-new"
            requirements = {"addon": ("engine", "engine-old"),
                            "engine": ("library", "library-old" if pin else "library-new")}
            if slug in requirements:
                dep, required_version = requirements[slug]
                value["dependencies"] = [{"dependency_type": "required", "project_id": dep + "-project",
                                          "version_id": required_version}]
            return value

        with mock.patch.dict(perf.SETS, fabric=["engine", "library", "addon"]), \
                mock.patch.object(perf, "projects", side_effect=lambda keys: {
                    k: project(k.split("-project")[0]) for k in keys}), \
                mock.patch.object(perf, "_safe_version", side_effect=lambda s, loader, mc, pin: release(s, pin)):
            plan, _ = perf.resolve(self.info, want_qol=False)
        self.assertEqual({p["version_id"] for p in plan}, {"engine-old", "library-old", "addon-new"})

    def test_installed_pins_select_version_or_reject_conflict(self):
        installed = {"indium-project": {"file": "indium.jar", "version_id": "indium-old",
                                        "pins": {"sodium-project": "sodium-old"}, "incompatible": []}}
        with mock.patch.object(perf, "_safe_version", wraps=perf._safe_version) as lookup:
            self.assertEqual(self.resolve(["sodium"], installed, pin="sodium-old")[0], ["sodium"])
            lookup.assert_called_once_with("sodium", "fabric", "1.20.1", "sodium-old")
        installed["iris-project"] = dict(installed["indium-project"], pins={"sodium-project": "other"})
        self.assertEqual(self.resolve(["sodium"], installed)[0], [])

    def test_only_mods_tables_supply_installed_ids(self):
        for filename in ["mods.toml", "neoforge.mods.toml"]:
            with zipfile.ZipFile(self.mods / "modernfix.jar", "w") as z:
                z.writestr("META-INF/" + filename, "[[mods]]\nmodId = 'modernfix'\n"
                           "[[dependencies.modernfix]]\nmodId = 'jei'\nmandatory = false\n"
                           "[[mods]]\nmodId = 'second_mod'\n")
            ids, _ = perf.installed_mod_ids(str(self.mods))
            self.assertEqual(set(ids), {"modernfix", "second_mod"})

    def test_tk_refuses_to_install_after_path_edit(self):
        app = mock.Mock(checked_instance=os.path.abspath("pack-a"))
        app.path.get.return_value = os.path.abspath("pack-b")
        with mock.patch.object(perf_gui.messagebox, "showerror") as error, \
                mock.patch.object(perf, "install_plan") as install:
            perf_gui.App.install(app)
        error.assert_called_once()
        install.assert_not_called()
