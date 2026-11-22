"""Tests of runtime verification, with a tiny stand-in app and a scripted verifier. Human-owned.

Run: python -m unittest discover -s harness/runtime -v
"""
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import verify as v

APP = '''
import os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        links = os.path.join(os.environ["APP_DATA_DIR"], "links")
        body = {"/actuator/health": lambda: '{"status":"UP"}',
                "/build-id": lambda: os.environ.get("FACTORY_RUNTIME_CANDIDATE", ""),
                "/links": lambda: open(links, "a+").read() or "[]"}.get(self.path, lambda: None)()
        if os.environ.get("APP_LIES") and self.path == "/build-id":
            body = "something-else"
        self.send_response(200 if body is not None else 404)
        self.end_headers()
        self.wfile.write((body or "").encode())
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
'''

SCENARIO = {"assertions": [{"id": "AC1", "description": "GET /links on a fresh app returns []"},
                           {"id": "AC2", "description": "GET /actuator/health returns UP"}]}


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        origin, seed = self.tmp / "origin.git", self.tmp / "seed"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "init", "-q", "-b", "main", str(seed))
        (seed / "docs/runtime").mkdir(parents=True)
        (seed / "docs/runtime/1.2.json").write_text(json.dumps(SCENARIO, indent=2))
        (seed / "backend").mkdir()
        (seed / "backend/pom.xml").write_text("<project/>")
        (seed / ".gitignore").write_text(".lap/\nbackend/target/\n")
        git(seed, "add", "-A")
        git(seed, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")
        git(seed, "remote", "add", "origin", str(origin))
        git(seed, "push", "-q", "origin", "main")
        self.root = self.tmp / "lap"
        git(self.tmp, "clone", "-q", str(origin), str(self.root))
        (self.root / "backend/target").mkdir()
        (self.root / "backend/target/app.jar").write_text("jar")
        app = self.tmp / "app.py"
        app.write_text(APP)
        self.saved = v.app_command
        v.app_command = lambda jar, port: [sys.executable, str(app), str(port)]
        self.v = v.Verify(self.root, "1.2", free_port())

    def tearDown(self):
        self.v.stop()
        v.app_command = self.saved

    def verifier(self, entries=None, candidate=None):
        """What a well-behaved verifier does: real evidence from the running app, then the report."""
        s = self.v.state()
        d = Path(s["dir"])
        status, body = self.v.get("/links")
        (d / "links.txt").write_text(f"{status}\n{body}\n")
        (d / "health.txt").write_text(" ".join(map(str, self.v.get("/actuator/health"))))
        entries = entries if entries is not None else [
            {"id": "AC1", "outcome": "passed", "expected": "[]", "observed": body, "reason": "same", "evidence_path": "links.txt"},
            {"id": "AC2", "outcome": "passed", "expected": "UP", "observed": "UP", "reason": "same", "evidence_path": "health.txt"}]
        report = {"candidate": candidate if candidate is not None else self.v.get("/build-id")[1] + "\n",
                  "assertions": entries}
        Path(s["report"]).write_text(json.dumps(report))


class RuntimeTests(Base):
    def test_a_good_report_is_verified(self):
        word, prompt = self.v.start()
        self.assertEqual(word, "started")
        text = Path(prompt).read_text()
        self.assertIn("GET /links on a fresh app returns []", text)
        self.assertIn(self.v.state()["dir"], text)
        self.assertNotIn("{attempt_dir}", text)
        self.verifier()
        word, why = self.v.check()
        self.assertEqual(word, "verified", why)
        self.assertIsNone(self.v.state()["pid"])
        self.assertIsNone(self.v.get("/actuator/health")[0])  # the app is stopped
        self.assertIn("Runtime verification: verified", self.v.summary())
        self.assertIn("`AC1` passed", self.v.summary())

    def test_each_attempt_starts_fresh(self):
        self.v.start()
        first = Path(self.v.state()["dir"])
        self.verifier()
        self.v.check()
        self.v.start()
        self.assertNotEqual(Path(self.v.state()["dir"]), first)
        self.assertEqual(self.v.state()["attempt"], 1)
        self.assertEqual(list((Path(self.v.state()["dir"]) / "data").iterdir()), [])

    def test_a_failed_assertion_is_failed(self):
        self.v.start()
        self.verifier()
        r = json.loads(Path(self.v.state()["report"]).read_text())
        r["assertions"][0].update(outcome="failed", observed="[1]")
        Path(self.v.state()["report"]).write_text(json.dumps(r))
        word, why = self.v.check()
        self.assertEqual(word, "failed")
        self.assertIn("AC1", why)

    def test_an_inconclusive_assertion_is_inconclusive(self):
        self.v.start()
        self.verifier()
        r = json.loads(Path(self.v.state()["report"]).read_text())
        r["assertions"][1]["outcome"] = "inconclusive"
        Path(self.v.state()["report"]).write_text(json.dumps(r))
        self.assertEqual(self.v.check()[0], "inconclusive")

    def test_a_malformed_report_gets_one_more_attempt_with_the_reason(self):
        self.v.start()
        self.verifier(entries=[{"id": "AC1", "outcome": "passed", "expected": 1, "observed": 1, "reason": "x",
                                "evidence_path": "links.txt, health.txt"}])
        word, why = self.v.check()
        self.assertEqual(word, "malformed")
        self.assertIn("missing assertions: AC2", why)
        self.assertIn("exactly one file", why)
        self.v.start()
        self.assertEqual(self.v.state()["attempt"], 2)
        self.assertIn("missing assertions: AC2", (Path(self.v.state()["dir"]) / "prompt.md").read_text())
        self.verifier(entries=[])
        word, why = self.v.check()
        self.assertEqual(word, "inconclusive")
        self.assertIn("malformed 2 times", why)

    def test_evidence_must_be_one_real_file_inside_the_attempt(self):
        self.v.start()
        outside = self.tmp / "outside.txt"
        outside.write_text("x")
        d = Path(self.v.state()["dir"])
        (d / "empty.txt").write_text("")
        self.verifier(entries=[
            {"id": "AC1", "outcome": "passed", "expected": 1, "observed": 1, "reason": "x", "evidence_path": str(outside)},
            {"id": "AC2", "outcome": "passed", "expected": 1, "observed": 1, "reason": "x", "evidence_path": "empty.txt"}])
        word, why = self.v.check()
        self.assertEqual(word, "malformed")
        self.assertIn("outside this attempt", why)
        self.assertIn("does not exist or is empty", why)

    def test_the_build_identity_must_agree(self):
        self.v.start()
        self.verifier(candidate="not-the-build")
        word, why = self.v.check()
        self.assertEqual(word, "inconclusive")
        self.assertIn("build identity disagrees", why)

    def test_writing_in_the_checkout_is_inconclusive(self):
        self.v.start()
        self.verifier()
        (self.root / "stray.txt").write_text("oops")
        word, why = self.v.check()
        self.assertEqual(word, "inconclusive")
        self.assertIn("stray.txt", why)


class ScenarioTests(Base):
    def test_the_scenario_comes_from_main_and_may_not_change(self):
        (self.root / "docs/runtime/1.2.json").write_text(json.dumps({"assertions": [{"id": "AC1", "description": "x"}]}))
        with self.assertRaises(ValueError) as e:
            self.v.start()
        self.assertIn("differs from origin/main", str(e.exception))

    def test_a_scenario_only_on_the_branch_is_refused(self):
        w = v.Verify(self.root, "1.3", free_port())
        (self.root / "docs/runtime/1.3.json").write_text(json.dumps(SCENARIO))
        with self.assertRaises(ValueError) as e:
            w.start()
        self.assertIn("not on origin/main", str(e.exception))

    def test_no_scenario_is_skipped(self):
        w = v.Verify(self.root, "1.9", free_port())
        self.assertEqual(w.start()[0], "skipped")
        self.assertEqual(w.check()[0], "skipped")

    def test_no_backend_is_skipped(self):
        (self.root / "backend/pom.xml").unlink()
        git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "no backend")
        self.assertEqual(self.v.start(), ("skipped", "no backend yet"))

    def test_an_app_that_does_not_start_is_inconclusive(self):
        v.app_command = lambda jar, port: [sys.executable, "-c", "import sys; sys.exit(1)"]
        word, why = self.v.start()
        self.assertEqual(word, "inconclusive")
        self.assertIn("did not become healthy", why)

    def test_an_app_that_reports_another_build_is_inconclusive(self):
        import os
        os.environ["APP_LIES"] = "1"
        try:
            word, why = self.v.start()
        finally:
            del os.environ["APP_LIES"]
        self.assertEqual(word, "inconclusive")
        self.assertIn("build identity mismatch", why)

    def test_bad_refs_are_refused(self):
        with self.assertRaises(ValueError):
            v.Verify(self.root, "../x")


if __name__ == "__main__":
    unittest.main()
