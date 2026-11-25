import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
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
        self.assertEqual(self.resolve(["sodium", "indium"], pin="sodium-old")[0], ["sodium"])
        self.assertEqual(self.resolve(["indium"], pin="sodium-old")[0], ["indium", "sodium"])
        self.assertEqual(self.resolve(["sodium", "indium"])[0], ["sodium", "indium"])

    def test_unknown_installed_version_does_not_satisfy_pin(self):
        with zipfile.ZipFile(self.mods / "local.jar", "w") as archive:
            archive.writestr("fabric.mod.json", '{"id":"sodium"}')
        self.assertEqual(self.resolve(["indium"], pin="sodium-new")[0], [])

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
