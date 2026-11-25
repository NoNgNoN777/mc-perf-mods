"""Regression tests for restore safety in scripts/perf.py (standard library only, no network).

    python -m unittest discover -s tests -v

Set PERF_SCRIPT=<path to perf.py> to run the same tests against another copy (e.g. an older one).
Everything runs in temp folders - no real Minecraft instance is touched.
"""
import datetime
import hashlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.environ.get("PERF_SCRIPT") or os.path.join(HERE, "..", "scripts", "perf.py")


def load_perf():
    spec = importlib.util.spec_from_file_location("perf_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha1(b):
    return hashlib.sha1(b).hexdigest()


class RestoreSafety(unittest.TestCase):
    def setUp(self):
        self.perf = load_perf()
        self.tmp = tempfile.mkdtemp()
        self.inst = os.path.join(self.tmp, "instance [forge]")
        self.mods = os.path.join(self.inst, "mods")
        os.makedirs(self.mods)
        self.sd = os.path.join(self.inst, self.perf.STATE_DIR)
        os.makedirs(self.sd)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def jar(self, name, data):
        p = os.path.join(self.mods, name)
        with open(p, "wb") as f:
            f.write(data)
        return p

    def record(self, entries, name="20260101-000000"):
        with open(os.path.join(self.sd, name + ".json"), "w", encoding="utf-8") as f:
            json.dump({"time": name, "mc": "1.20.1", "loader": "fabric", "added": entries}, f)
        return name

    def entry(self, file, digest):
        return {"slug": file[:-4], "file": file, "path": os.path.join("mods", file), "sha1": digest}

    def restore(self, name):
        with mock.patch("sys.stdout"):
            self.perf.restore_install(self.inst, name, lambda *a: None)

    def cli_restore(self, name=None):
        with mock.patch("sys.stdout"):
            try:
                self.perf.cmd_restore(types.SimpleNamespace(instance=self.inst, install=name))
                return True
            except SystemExit:
                return False

    def records(self):
        return sorted(f for f in os.listdir(self.sd) if f != ".lock")

    def test_hash_catalog_and_mod_ids_in_bracketed_instance(self):
        import zipfile
        with zipfile.ZipFile(os.path.join(self.mods, "user.jar"), "w") as z:
            z.writestr("fabric.mod.json", '{"id":"local_mod"}')
        self.assertEqual(self.perf.installed_mod_ids(self.mods)[0], {"local_mod": "user.jar"})
        with mock.patch.object(self.perf, "api_post", return_value={}) as lookup:
            self.perf.installed_projects(self.mods)
        self.assertEqual(len(lookup.call_args[0][1]["hashes"]), 1)

    def test_history_failure_leaves_no_unrecorded_jar(self):
        info = {"mc": "1.20.1", "loader": "fabric", "mods_dir": self.mods}
        plan = [{"slug": "a", "file": "a.jar", "url": "https://example.invalid/a", "sha1": None}]
        with mock.patch.object(self.perf, "_write_state", side_effect=OSError("disk full")), \
                mock.patch.object(self.perf.urllib.request, "urlopen", return_value=io.BytesIO(b"A")):
            with self.assertRaises(OSError):
                self.perf.install_plan(info, plan, self.inst)
        self.assertEqual(os.listdir(self.mods), [])

    def test_concurrent_writer_is_excluded_and_lock_releases(self):
        with self.perf._lock_history(self.sd):
            with self.assertRaises(RuntimeError):
                self.perf.install_plan({"mods_dir": self.mods}, [], self.inst)
        with self.perf._lock_history(self.sd):
            self.assertEqual(self.perf.installs(self.inst), [])

    def test_unchanged_file_is_removed(self):
        p = self.jar("a.jar", b"AAA")
        self.restore(self.record([self.entry("a.jar", sha1(b"AAA"))]))
        self.assertFalse(os.path.exists(p))
        self.assertEqual(self.records(), ["20260101-000000.json.restored"])

    def test_replaced_file_is_kept_and_record_stays(self):
        p = self.jar("same.jar", b"user replaced this")
        q = self.jar("b.jar", b"BBB")
        name = self.record([self.entry("same.jar", sha1(b"original")), self.entry("b.jar", sha1(b"BBB"))])
        self.restore(name)
        self.assertTrue(os.path.exists(p))
        self.assertFalse(os.path.exists(q))
        with open(os.path.join(self.sd, name + ".json"), encoding="utf-8") as f:
            left = json.load(f)["added"]
        self.assertEqual([x["file"] for x in left], ["same.jar"])   # still there for a retry

    def test_missing_file_is_fine(self):
        self.restore(self.record([self.entry("gone.jar", sha1(b"x"))]))
        self.assertEqual(self.records(), ["20260101-000000.json.restored"])

    def test_record_without_hash_is_not_deleted(self):
        p = self.jar("c.jar", b"CCC")
        self.restore(self.record([self.entry("c.jar", None)]))
        self.assertTrue(os.path.exists(p))

    def test_path_outside_instance_is_not_deleted(self):
        outside = os.path.join(self.tmp, "victim.jar")
        with open(outside, "wb") as f:
            f.write(b"VVV")
        e = self.entry("victim.jar", sha1(b"VVV"))
        e["path"] = os.path.join("..", "victim.jar")
        self.restore(self.record([e]))
        self.assertTrue(os.path.exists(outside))

    def test_cli_uses_same_rule(self):
        p = self.jar("same.jar", b"user replaced this")
        self.record([self.entry("same.jar", sha1(b"original"))])
        self.assertFalse(self.cli_restore())                       # reports partial restore
        self.assertTrue(os.path.exists(p))

    def test_install_records_written_hash_and_unique_tag(self):
        info = {"mc": "1.20.1", "loader": "fabric", "mods_dir": self.mods}
        fixed = datetime.datetime(2026, 1, 1, 0, 0, 0)
        fake_dt = types.SimpleNamespace(datetime=types.SimpleNamespace(now=lambda: fixed))

        def urlopen(req, timeout=None):
            return io.BytesIO(b"JAR-" + req.full_url.encode())

        tags = []
        with mock.patch.object(self.perf, "datetime", fake_dt), \
                mock.patch.object(self.perf.urllib.request, "urlopen", urlopen):
            for f in ("x.jar", "y.jar"):
                plan = [{"slug": f[:-4], "file": f, "url": "https://example.invalid/" + f, "sha1": None}]
                tags.append(self.perf.install_plan(info, plan, self.inst, lambda *a: None)[0])
        self.assertEqual(len(set(tags)), 2)
        self.restore(tags[0])
        self.assertFalse(os.path.exists(os.path.join(self.mods, "x.jar")))
        self.assertTrue(os.path.exists(os.path.join(self.mods, "y.jar")))


if __name__ == "__main__":
    unittest.main()
