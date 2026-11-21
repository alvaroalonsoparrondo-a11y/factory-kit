#!/usr/bin/env python3
"""Runtime verification: an agent exercises the running app, a script judges its evidence. Human-owned.

Part of the judge. Standard library only (Python 3.11+). Adapted from Archon's `archon-verify-runtime`:
deterministic steps around one agent step, and the agent's report is checked, never trusted.

  python harness/runtime/verify.py <ref> start [--port 8080]   # fresh app, attempt folder, the verifier's prompt
  (the lap launches a context-free subagent: "Read <prompt> and follow it exactly")
  python harness/runtime/verify.py <ref> check                 # stop the app, judge the report
  python harness/runtime/verify.py <ref> summary               # the result, as Markdown for the pull request
  python harness/runtime/verify.py <ref> stop                  # stop the app (after a cancelled attempt)

The scenario is `docs/runtime/<ref>.json`, written by the product owner when the ticket is planned:
`{"assertions": [{"id": "AC1", "description": "what to do against the running app, and what to see"}]}`.
It is always read from `origin/main`. A lap whose copy differs is refused: the builder may not change
the test it is judged by. No scenario, or no backend yet: `skipped`.

`check` prints one word first and exits with its code:
- `verified` (0): every assertion passed, on the build under test.
- `failed` (1): a well-formed report shows an assertion failing. It takes a `runtime` round.
- `inconclusive` (3): something could not be judged (an assertion, the app, the build identity, or the
  verifier wrote in the checkout). No round: a human looks.
- `malformed` (4): the report broke the rules (coverage, fields, evidence). Run `start` again once,
  with the reason in the new prompt; a second malformed report is `inconclusive`.

The checker validates coverage, fields, evidence files inside the attempt folder, and the build
identity. It does not read the observations' prose: the verifier owns the comparison. Everything
stays in `.lap/runtime/<ref>/` (ignored by Git).
"""
import argparse
import datetime
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTCOMES = ("passed", "failed", "inconclusive")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
ATTEMPTS = 2  # a malformed report gets one fresh attempt, as in Archon
HEALTH_SECONDS = 120
CODES = {"verified": 0, "failed": 1, "skipped": 0, "inconclusive": 3, "malformed": 4}


def app_command(jar, port):
    """The runtime contract's start command (harness/README.md). Tests replace it."""
    return ["java", "-jar", str(jar), f"--server.port={port}"]


class Verify:
    def __init__(self, root, ref, port=8080):
        if not REF.fullmatch(ref or "") or ".." in ref:
            raise ValueError(f"not a ticket ref: {ref!r}")
        self.root, self.ref, self.port = Path(root), ref, port
        self.folder = self.root / ".lap" / "runtime" / ref
        self.state_path = self.folder / "state.json"

    # -- state ---------------------------------------------------------------------------

    def state(self):
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, state):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                              encoding="utf-8", check=check)

    def porcelain(self):
        """The checkout's state, apart from `.lap/` (ignored) and the verifier's own folder."""
        return self.git("status", "--porcelain", "--untracked-files=all").stdout

    # -- the scenario --------------------------------------------------------------------

    def scenario(self):
        """(assertions, None), or (None, why skipped), or raises ValueError when the lap may not use it."""
        rel = f"docs/runtime/{self.ref}.json"
        on_main = self.git("show", f"origin/main:{rel}", check=False)
        here = self.root / rel
        if on_main.returncode != 0:
            if here.exists():
                raise ValueError(f"{rel} is not on origin/main. The product owner commits the scenario to main "
                                 "before the lap; the lap may not write it.")
            return None, f"no scenario for {self.ref} ({rel} is not on main)"
        if here.exists() and here.read_text(encoding="utf-8") != on_main.stdout:
            raise ValueError(f"{rel} differs from origin/main. The lap may not change the scenario it is judged by; "
                             "restore it with `git checkout origin/main -- " + rel + "`.")
        try:
            data = json.loads(on_main.stdout)
        except ValueError as e:
            raise ValueError(f"{rel} on main is not JSON: {e}") from e
        assertions = data.get("assertions") if isinstance(data, dict) else None
        if not isinstance(assertions, list) or not assertions:
            raise ValueError(f"{rel} needs a non-empty `assertions` list")
        ids = []
        for a in assertions:
            if not isinstance(a, dict) or not ID.fullmatch(str(a.get("id", ""))) or not str(a.get("description", "")).strip():
                raise ValueError(f"{rel}: each assertion needs an `id` (letters, digits, . _ -) and a `description`")
            ids.append(a["id"])
        if len(set(ids)) != len(ids):
            raise ValueError(f"{rel}: assertion ids must be unique")
        return [{"id": a["id"], "description": a["description"]} for a in assertions], None

    def jar(self):
        if not (self.root / "backend" / "pom.xml").exists():
            return None
        jars = [p for p in sorted((self.root / "backend" / "target").glob("*.jar"))
                if not re.search(r"-(plain|sources|javadoc)\.jar$", p.name)]
        if not jars:
            raise ValueError("no runnable jar in backend/target/: run the gates first")
        return jars[0]

    # -- the app -------------------------------------------------------------------------

    def url(self, port=None):
        return f"http://localhost:{port or self.port}"

    def get(self, path, port=None, timeout=5):
        try:
            with urllib.request.urlopen(self.url(port) + path, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError):
            return None, ""

    @staticmethod
    def kill(pid):
        if not pid:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
            else:
                os.killpg(int(pid), signal.SIGTERM)
                for _ in range(50):
                    try:  # reap it when it is our own child, so a zombie does not look alive
                        if os.waitpid(int(pid), os.WNOHANG)[0]:
                            return
                    except ChildProcessError:
                        pass
                    os.killpg(int(pid), 0)
                    time.sleep(0.1)
                os.killpg(int(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def stop(self):
        s = self.state()
        self.kill(s.get("pid"))
        if s.get("pid"):
            s["pid"] = None
            self.save(s)

    # -- start ---------------------------------------------------------------------------

    def start(self):
        """(word, message). On `started`, the message names the verifier's prompt."""
        self.stop()
        prev = self.state()
        assertions, skipped = self.scenario()
        if skipped is None:
            jar = self.jar()
            if jar is None:
                skipped = "no backend yet"
        if skipped:
            self.save({"result": "skipped", "reason": skipped})
            return "skipped", skipped
        attempt = prev.get("attempt", 0) + 1 if prev.get("result") == "malformed" else 1
        feedback = prev.get("feedback", "") if attempt > 1 else ""
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.folder.mkdir(parents=True, exist_ok=True)  # a new, unique folder for every attempt, never reused
        attempt_dir = Path(tempfile.mkdtemp(prefix=f"attempt-{attempt}-{stamp}-", dir=self.folder)).resolve()
        (attempt_dir / "data").mkdir()
        head = self.git("rev-parse", "HEAD").stdout.strip()
        candidate = f"{head}-runtime-{stamp}"
        env = {k: v for k, v in os.environ.items() if not k.endswith("_TOKEN")}
        env.update({"APP_DATA_DIR": str(attempt_dir / "data"), "FACTORY_RUNTIME_CANDIDATE": candidate})
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        with open(attempt_dir / "app.log", "w", encoding="utf-8") as log:
            proc = subprocess.Popen(app_command(jar, self.port), cwd=self.root, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, **group)
        state = {"attempt": attempt, "pid": proc.pid, "port": self.port, "candidate": candidate, "dir": str(attempt_dir),
                 "report": str(attempt_dir / "report.json"), "porcelain": self.porcelain(), "result": "started",
                 "assertions": assertions}
        self.save(state)
        deadline = time.monotonic() + HEALTH_SECONDS
        while time.monotonic() < deadline and proc.poll() is None:
            if self.get("/actuator/health")[0] == 200:
                break
            time.sleep(0.5)
        if self.get("/actuator/health")[0] != 200:
            return self._end(state, "inconclusive", "the application did not become healthy; see " + str(attempt_dir / "app.log"))
        seen = self.get("/build-id")[1].strip()
        if seen != candidate:
            return self._end(state, "inconclusive", f"build identity mismatch: expected {candidate}, seen {seen!r}")
        prompt = (HERE / "verifier.md").read_text(encoding="utf-8").format(
            base_url=self.url(), candidate_command=f"curl -sS {self.url()}/build-id",
            assertions=json.dumps(assertions, indent=2, ensure_ascii=False), attempt_dir=attempt_dir,
            report_path=attempt_dir / "report.json",
            feedback=(f"## Your last report was rejected\n\nThe checker rejected the previous attempt's report: "
                      f"{feedback}\n\nCorrect that, and collect fresh evidence against this newly started "
                      "application. Do not reuse earlier files." if feedback else ""))
        (attempt_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        return "started", str(attempt_dir / "prompt.md")

    def _end(self, state, result, reason):
        self.kill(state.get("pid"))
        state.update(pid=None, result=result, reason=reason)
        self.save(state)
        with open(self.folder / "verdicts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({k: state.get(k) for k in ("attempt", "candidate", "result", "reason", "dir")}) + "\n")
        return result, reason

    # -- check ---------------------------------------------------------------------------

    def report_errors(self, report, ids, attempt_dir):
        """What makes a report malformed; empty when it keeps every rule."""
        if not isinstance(report, dict):
            return ["the report is not a JSON object"]
        errors = []
        if not isinstance(report.get("candidate"), str):
            errors.append("`candidate` must be a string")
        entries = report.get("assertions")
        if not isinstance(entries, list):
            return errors + ["`assertions` must be a list"]
        seen = [e.get("id") for e in entries if isinstance(e, dict)]
        missing = [i for i in ids if i not in seen]
        extra = sorted({str(i) for i in seen if i not in ids})
        twice = sorted({str(i) for i in seen if seen.count(i) > 1})
        if missing:
            errors.append("missing assertions: " + ", ".join(missing))
        if extra:
            errors.append("unknown assertions: " + ", ".join(extra))
        if twice:
            errors.append("assertions reported more than once: " + ", ".join(twice))
        for e in entries:
            if not isinstance(e, dict):
                errors.append("every assertion entry must be an object")
                continue
            who = e.get("id", "?")
            if e.get("outcome") not in OUTCOMES:
                errors.append(f"{who}: `outcome` must be one of {', '.join(OUTCOMES)}")
            for key in ("expected", "observed"):
                if key not in e:
                    errors.append(f"{who}: `{key}` is missing (use null when unavailable)")
            if not isinstance(e.get("reason"), str) or not e["reason"].strip():
                errors.append(f"{who}: `reason` must say what was compared, or why it could not be")
            ev = e.get("evidence_path")
            if not isinstance(ev, str) or not ev.strip() or "," in ev:
                errors.append(f"{who}: `evidence_path` must name exactly one file")
                continue
            path = Path(ev) if Path(ev).is_absolute() else attempt_dir / ev
            try:
                inside = path.resolve().is_relative_to(attempt_dir.resolve())
            except OSError:
                inside = False
            if not inside:
                errors.append(f"{who}: evidence `{ev}` is outside this attempt's folder")
            elif not path.is_file() or path.stat().st_size == 0:
                errors.append(f"{who}: evidence `{ev}` does not exist or is empty")
        return errors

    def check(self):
        state = self.state()
        if state.get("result") == "skipped":
            return "skipped", state.get("reason", "")
        if state.get("result") != "started":
            return "inconclusive", "no attempt is running: run `start` first"
        probe = self.get("/build-id", state.get("port"))[1].strip()
        self.kill(state.get("pid"))
        state["pid"] = None
        attempt_dir = Path(state["dir"])
        now = self.porcelain()
        if now != state.get("porcelain"):
            changed = sorted(set(now.splitlines()) ^ set((state.get("porcelain") or "").splitlines()))
            return self._end(state, "inconclusive", "the verifier wrote in the checkout: " + "; ".join(changed)[:500])
        try:
            report = json.loads(Path(state["report"]).read_text(encoding="utf-8"))
        except FileNotFoundError:
            report, errors = None, ["no report was written at " + state["report"]]
        except ValueError as e:
            report, errors = None, [f"the report is not valid JSON: {e}"]
        else:
            errors = self.report_errors(report, [a["id"] for a in state["assertions"]], attempt_dir)
        if errors:
            reason = "; ".join(errors)[:1500]
            if state["attempt"] < ATTEMPTS:
                state["feedback"] = reason
                return self._end(state, "malformed", reason)
            return self._end(state, "inconclusive", f"the report was malformed {ATTEMPTS} times: {reason}")
        expected = state["candidate"]
        if report["candidate"].strip() != expected or probe != expected:
            return self._end(state, "inconclusive", f"build identity disagrees: expected {expected}, probe "
                                                    f"{probe!r}, report {report['candidate'].strip()!r}")
        state["outcomes"] = [{k: e.get(k) for k in ("id", "outcome", "expected", "observed", "reason", "evidence_path")}
                             for e in report["assertions"]]
        outcomes = {e["outcome"] for e in report["assertions"]}
        if "inconclusive" in outcomes:
            bad = [e["id"] for e in report["assertions"] if e["outcome"] == "inconclusive"]
            return self._end(state, "inconclusive", "could not be judged: " + ", ".join(bad))
        if "failed" in outcomes:
            bad = [f"{e['id']} (observed {json.dumps(e.get('observed'))[:120]})" for e in report["assertions"]
                   if e["outcome"] == "failed"]
            return self._end(state, "failed", "failed: " + "; ".join(bad))
        return self._end(state, "verified", f"{len(report['assertions'])} assertion(s) passed on {expected}")

    # -- summary -------------------------------------------------------------------------

    def summary(self):
        s = self.state()
        result = s.get("result", "not run")
        out = [f"**Runtime verification: {result}**" + (f" ({s.get('reason')})" if s.get("reason") else "")]
        if s.get("candidate"):
            out.append(f"Candidate `{s['candidate']}`, attempt {s.get('attempt')}, evidence in `{s.get('dir')}`.")
        for e in s.get("outcomes") or []:
            out.append(f"- `{e['id']}` {e['outcome']}: {e.get('reason', '')}")
        return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ref")
    p.add_argument("cmd", choices=("start", "check", "summary", "stop"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    a = p.parse_args(argv)
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                              check=True).stdout.strip()
        v = Verify(root, a.ref, a.port)
        if a.cmd == "stop":
            v.stop()
            print(f"runtime {a.ref}: stopped")
            return 0
        if a.cmd == "summary":
            print(v.summary())
            return 0
        word, message = v.start() if a.cmd == "start" else v.check()
    except subprocess.CalledProcessError as e:
        print(f"verify: {e.stderr or e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"verify: {e}", file=sys.stderr)
        return 2
    print(word)
    print(message)
    return 0 if word == "started" else CODES[word]


if __name__ == "__main__":
    sys.exit(main())
