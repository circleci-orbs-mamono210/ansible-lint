#!/usr/bin/env python3
"""Run the install script of this commit under a controlled condition (#5539).

CircleCI cannot continue a job after a failed step, so a failing
ansible-lint/install cannot be observed through the public step. For the
conditions in which install must fail, and where its output has to be read,
this file starts the production script itself:

    /bin/bash -eo pipefail <checkout>/src/scripts/install.sh

That is the shell CircleCI uses for a run step. Both pack jobs show that the
packed command equals this file (.circleci/verify-packed-install.sh). The
script and its Python program are not changed, copied or patched. Each
scenario states what it sets up around the script (SCENARIOS below). The
result of such a run is not a result of the public step; the jobs use the
public step wherever install is expected to succeed.

Usage: check-install-script.py SOURCE_DIRECTORY SCENARIO

It uses only the standard library, so it also runs with the Python of an
image that has no verified interpreter.
"""

import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = Path("/tmp/ansible-lint-install-script-evidence")
STATE = Path("/tmp/ansible-lint-install-script-state")
ROOT_NAME = ".orbss-ansible-lint"
SHELL = ["/bin/bash", "-eo", "pipefail"]
FAILED = re.compile(r"^ansible-lint/install failed \[([a-z-]+)\]: (.*)$", re.M)
NOTHING_PUBLISHED = "ansible-lint/install: no command was published by this invocation."
UNUSED_PROXY = "http://127.0.0.1:9"
PROXY_VARIABLES = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")
# Values of the pip settings test. They must never appear in the output.
PIP_SECRET = "orb-test-credential-do-not-print"
PIP_HOSTS = ("pip-environment.invalid", "pip-user-file.invalid", "pip-named-file.invalid")


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def tree(directory, skip=()):
    """Every entry of a directory: kind, link target or content hash, and
    for files the modification time. An unchanged tree was not rewritten."""
    directory = Path(directory)
    if not os.path.lexists(directory):
        return None
    found = {}
    for path in sorted(directory.rglob("*")):
        relative = str(path.relative_to(directory))
        if relative.split(os.sep)[0] in skip:
            continue
        if path.is_symlink():
            found[relative] = ["l", os.readlink(path)]
        elif path.is_dir():
            found[relative] = ["d"]
        else:
            found[relative] = ["f", sha256(path.read_bytes()), path.stat().st_mtime_ns]
    return found


def tree_summary(found):
    if found is None:
        return {"exists": False}
    return {"exists": True, "entries": len(found),
            "sha256": sha256(json.dumps(found, sort_keys=True).encode("utf-8")),
            "has_state_record": "state.json" in found}


def move_directory(source, target):
    """Move a directory to another name in the same parent directory.

    A directory that belongs to an image layer cannot be renamed on the
    overlay file system of a container (EXDEV). It is then copied with its
    modification times, and the original is removed.
    """
    try:
        os.rename(source, target)
        return "renamed"
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
    try:
        shutil.copytree(source, target, symlinks=True)
    except OSError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    shutil.rmtree(source)
    return "copied and removed, because the directory belongs to an image layer"


def which_all(names, path=None):
    return {name: shutil.which(name, path=path) for name in names}


def ansible_on_path(path=None):
    found = []
    for directory in (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep):
        try:
            names = sorted(os.listdir(directory)) if directory else []
        except OSError:
            continue
        found.extend(os.path.join(directory, name) for name in names if name.startswith("ansible"))
    return found


class Run:
    """One run of the production script and the state around it."""

    def __init__(self, source, scenario):
        self.source = Path(source).resolve()
        self.scenario = scenario
        self.lock = load(self.source / "python-install-lock.json")
        self.fixed = self.lock["fixed_information"]
        self.names = self.fixed["exposed_commands"]
        self.home = Path(os.environ["HOME"])
        self.root = self.home / ROOT_NAME
        self.bash_env = os.environ.get("BASH_ENV") or ""
        self.script = self.source / "src/scripts/install.sh"
        self.checks = []
        self.result = None
        self.before = None
        self.after = None

    def observe(self, path=None):
        return {"bash_env_text": read_text(self.bash_env) if self.bash_env else None,
                "commands": which_all(self.names, path),
                "tree": tree(self.root)}

    def start(self, environment=None, remove=(), cwd=None):
        """Run the script. Only the named variables differ from this step."""
        env = dict(os.environ)
        for name in remove:
            env.pop(name, None)
        env.update(environment or {})
        self.before = self.observe(env.get("PATH"))
        started = now()
        result = subprocess.run(SHELL + [str(self.script)], cwd=cwd or os.getcwd(), env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=1200, check=False)
        self.after = self.observe(env.get("PATH"))
        failure = FAILED.findall(result.stderr)
        self.result = {"command": SHELL + [str(self.script)], "cwd": cwd or os.getcwd(),
                       "started_at": started, "finished_at": now(), "exit_code": result.returncode,
                       "stdout": result.stdout, "stderr": result.stderr,
                       "failure_lines": [{"category": category, "reason": reason} for category, reason in failure],
                       "changed_variable_names": sorted(set(environment or {}) | set(remove))}
        sys.stdout.write(result.stdout)
        sys.stdout.flush()
        sys.stderr.write(result.stderr)
        sys.stderr.flush()
        return self.result

    def check(self, identifier, requirement, passed, observed=None):
        self.checks.append({"id": identifier, "requirement": requirement, "passed": bool(passed),
                            "observed": observed})
        print(("PASS " if passed else "FAIL ") + identifier + ": " + requirement, flush=True)

    def expect_failure(self, categories, reason=None):
        """The common requirements of contract section 13 for a failed run."""
        result = self.result
        lines = result["failure_lines"]
        self.check("exit", "install exits with a non-zero status (1)", result["exit_code"] == 1,
                   {"exit_code": result["exit_code"]})
        self.check("category", "install names the failure category: " + " or ".join(categories),
                   len(lines) == 1 and lines[0]["category"] in categories
                   and (reason is None or reason in lines[0]["reason"]),
                   {"failure_lines": lines, "required_text": reason})
        self.check("not-published", "install says that it published no command, and BASH_ENV is unchanged",
                   NOTHING_PUBLISHED in result["stderr"]
                   and self.after["bash_env_text"] == self.before["bash_env_text"],
                   {"bash_env_unchanged": self.after["bash_env_text"] == self.before["bash_env_text"]})
        self.check("no-fallback", "the exposed commands resolve after the run as before it; install "
                   "reported no success through another tool",
                   self.after["commands"] == self.before["commands"]
                   and "managed environment:" not in result["stdout"],
                   {"before": self.before["commands"], "after": self.after["commands"]})

    def expect_tree(self, identifier, requirement, kind):
        before, after = self.before["tree"], self.after["tree"]
        if kind == "absent":
            passed = before is None and after is None
        elif kind == "unchanged":
            passed = before is not None and before == after
        elif kind == "created-without-record":
            passed = before is None and after is not None and "state.json" not in after
        else:
            raise ValueError(kind)
        changed = None
        if before is not None and after is not None and before != after:
            changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))[:20]
        self.check(identifier, requirement, passed,
                   {"managed_environment": str(self.root), "before": tree_summary(before),
                    "after": tree_summary(after), "changed_entries": changed})

    def finish(self, boundary, extra=None):
        evidence = {
            "ticket": 5539, "scenario": self.scenario, "observed_at": now(),
            "commit": os.environ.get("CIRCLE_SHA1"), "job": os.environ.get("CIRCLE_JOB"),
            "job_url": os.environ.get("CIRCLE_BUILD_URL"),
            "checker_interpreter": sys.executable,
            "script": "src/scripts/install.sh", "script_sha256": sha256(self.script.read_bytes()),
            "production_code": "The script of this commit, unchanged, started as CircleCI starts a run step. "
                               "It is not the public step ansible-lint/install.",
            "set_up_by_the_test": boundary,
            "result": "passed" if all(check["passed"] for check in self.checks) else "failed",
            "checks": self.checks, "run": self.result, "observations": extra or {},
        }
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        save(EVIDENCE / (self.scenario + ".json"), evidence)
        failed = [check["id"] for check in self.checks if not check["passed"]]
        if failed:
            print(json.dumps(evidence, indent=2), flush=True)
            print("Failed checks of scenario %s: %s" % (self.scenario, ", ".join(failed)), file=sys.stderr)
            return 1
        print(json.dumps({key: evidence[key] for key in ("scenario", "result", "commit", "job_url",
                                                         "script_sha256", "set_up_by_the_test")}
                         | {"exit_code": (self.result or {}).get("exit_code"),
                            "failure_lines": (self.result or {}).get("failure_lines"),
                            "checks": {check["id"]: check["passed"] for check in self.checks}}, indent=2),
              flush=True)
        return 0


def source_revision(run):
    head = subprocess.run(["git", "-C", str(run.source), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=False)
    run.check("revision", "The checked-out source is this pipeline's revision (CIRCLE_SHA1)",
              head.returncode == 0 and head.stdout.strip() == os.environ.get("CIRCLE_SHA1"),
              {"head": head.stdout.strip(), "circle_sha1": os.environ.get("CIRCLE_SHA1")})


# --- Scenarios of a job that has no managed environment yet ------------------

def clean_start(run):
    """Record the start of a failure job. Nothing is run."""
    STATE.mkdir(parents=True, exist_ok=False)
    source_revision(run)
    existing = ansible_on_path()
    run.check("clean", "The job is clean: no managed environment, no command whose name starts with "
              "'ansible' on PATH, and no publishing token",
              not os.path.lexists(run.root) and not existing and not os.environ.get("CIRCLE_TOKEN"),
              {"managed_environment_exists": os.path.lexists(run.root), "ansible_commands_on_path": existing,
               "publishing_token_present": bool(os.environ.get("CIRCLE_TOKEN"))})
    save(STATE / "start.json", {"bash_env": run.bash_env, "bash_env_text": read_text(run.bash_env),
                                "path": os.environ.get("PATH", ""),
                                "home_top_level": sorted(os.listdir(run.home))})
    return run.finish("Nothing. This step records the state at the start of the job.")


def existing_command(run):
    """E6 and F3: a command of the exposed set already resolves on PATH."""
    with tempfile.TemporaryDirectory(prefix="ansible-lint-orb-existing-") as temporary:
        marker = Path(temporary) / "started"
        fake = Path(temporary) / "bin" / "ansible-lint"
        fake.parent.mkdir()
        fake.write_text("#!/bin/bash\necho started > %s\necho 'ansible-lint 0.0.0 (a tool of the image)'\n"
                        % marker, encoding="utf-8")
        fake.chmod(0o755)
        text = fake.read_text(encoding="utf-8")
        run.start({"PATH": str(fake.parent) + os.pathsep + os.environ.get("PATH", "")})
        run.expect_failure(["existing-command"], reason="ansible-lint (" + str(fake) + ")")
        run.expect_tree("nothing-created", "install created no managed environment", "absent")
        run.check("existing-tool", "the existing tool was neither started nor changed",
                  not marker.exists() and fake.read_text(encoding="utf-8") == text,
                  {"started": marker.exists()})
    return run.finish("A directory with an executable named ansible-lint is put first on PATH for the "
                      "script's process only. Everything else is the environment of the step.")


def not_writable(run):
    """F5: the managed location cannot be written."""
    mode = os.stat(run.home).st_mode & 0o7777
    os.chmod(run.home, 0o555)
    try:
        run.start()
    finally:
        os.chmod(run.home, mode)
    run.expect_failure(["permission"], reason="could not be created")
    run.expect_tree("nothing-created", "install created no managed environment", "absent")
    run.check("restored", "the test restored the mode of the home directory",
              os.stat(run.home).st_mode & 0o7777 == mode, {"mode": oct(mode)})
    return run.finish("The test removes the write permission of the home directory (mode 0555) during the "
                      "run and restores it afterwards. HOME and everything else are unchanged.",
                      {"user_id": os.getuid(), "home_mode_during_run": "0o555"})


def location(run):
    """F14 (structural in the contract; measured here in addition)."""
    run.start(cwd=str(run.home))
    run.expect_failure(["location"], reason="would overlap")
    run.expect_tree("nothing-created", "install created no managed environment", "absent")
    return run.finish("The script is started with the home directory as its current directory.")


def no_bash_env(run):
    """F15 (structural in the contract; measured here in addition)."""
    run.start(remove=["BASH_ENV"])
    run.expect_failure(["publish"], reason="BASH_ENV is not set")
    run.expect_tree("nothing-created", "install created no managed environment", "absent")
    return run.finish("BASH_ENV is removed from the environment of the script's process only.")


def no_venv(run):
    """F4: the interpreter cannot create a virtual environment with pip,
    because its ensurepip module is missing. A run that could not hide the
    module fails; F4 is never reported as measured without a run."""
    interpreter = Path(run.fixed["interpreter"]["path"])
    module = interpreter.parent.parent / "lib" / ("python" + ".".join(
        run.fixed["interpreter"]["version"].split(".")[:2])) / "ensurepip"
    hidden = module.with_name("ensurepip.hidden-by-orb-test")
    listing = tree(module)
    try:
        hidden_how = move_directory(module, hidden)
    except OSError as error:
        run.check("reproduced", "the test hid the ensurepip module of the verified interpreter", False,
                  {"module": str(module), "reason": type(error).__name__ + ": " + str(error)})
        print("The module could not be hidden (%s: %s). F4 was not measured."
              % (type(error).__name__, error), file=sys.stderr, flush=True)
        return run.finish("Nothing. The module directory could not be hidden, so install was not run.")
    try:
        run.start()
    finally:
        restored_how = move_directory(hidden, module)
    run.check("reproduced", "the test hid the ensurepip module of the verified interpreter, and install ran "
              "without it", listing is not None, {"module": str(module), "hidden": hidden_how,
                                                  "put_back": restored_how})
    run.expect_failure(["virtual-environment"])
    run.expect_tree("nothing-created", "install created no managed environment", "absent")
    run.check("restored", "the test put the module back, with the same content and modification times",
              tree(module) == listing and not os.path.lexists(hidden), {"entries": len(listing or {})})
    return run.finish("The test hides the ensurepip module directory of the verified interpreter during "
                      "the run (%s) and puts it back afterwards (%s)." % (hidden_how, restored_how))


def index_unreachable(run):
    """F9: the package index cannot be reached. No pip configuration is used."""
    run.start({name: UNUSED_PROXY for name in PROXY_VARIABLES}, remove=["NO_PROXY", "no_proxy"])
    run.expect_failure(["download-or-install"])
    run.expect_tree("left-without-record", "install left its directory without a state record, so the "
                    "directory is not a complete managed environment", "created-without-record")
    pip_settings = sorted(name for name in os.environ if name.startswith("PIP_"))
    run.check("no-pip-configuration", "the condition uses no pip setting: no PIP_* variable is set",
              not pip_settings, {"pip_variable_names": pip_settings})
    return run.finish("The standard proxy variables (%s) of the script's process point to %s, where "
                      "nothing listens, and NO_PROXY is removed. These are general process variables, "
                      "which install neither sets nor removes; they are not pip configuration. pip, its "
                      "command line and the index URL are those of production."
                      % (", ".join(PROXY_VARIABLES), UNUSED_PROXY))


def foreign(run):
    """F6 (S3): the target path exists without a valid state record. Here it
    is the directory that the failed run of index-unreachable left."""
    run.check("precondition", "the managed location exists and has no state record",
              os.path.isdir(run.root) and not os.path.lexists(run.root / "state.json"),
              {"exists": os.path.isdir(run.root)})
    run.start()
    run.expect_failure(["foreign-environment"], reason="without a valid state record")
    run.expect_tree("unchanged", "install changed and deleted nothing in the existing directory", "unchanged")
    return run.finish("Nothing. The directory is what the failed run of scenario index-unreachable left, "
                      "as contract section 9.3 describes.")


def nothing_published(run):
    """The end of a failure job: no run published anything."""
    start = load(STATE / "start.json")
    existing = ansible_on_path()
    top = sorted(os.listdir(run.home))
    run.check("bash-env", "BASH_ENV is as at the start of the job", read_text(run.bash_env) == start["bash_env_text"])
    run.check("path", "PATH is as at the start of the job, and no command whose name starts with "
              "'ansible' resolves", os.environ.get("PATH", "") == start["path"] and not existing,
              {"ansible_commands_on_path": existing})
    run.check("home", "the only new entry of the home directory is the directory that the failed "
              "installation left",
              sorted(set(top) - set(start["home_top_level"])) == [ROOT_NAME]
              and not set(start["home_top_level"]) - set(top),
              {"added": sorted(set(top) - set(start["home_top_level"]))})
    return run.finish("Nothing. This step compares the end of the job with its start.")


# --- Scenarios of a job with a complete managed environment -----------------

def mark(run):
    """Record the managed environment after the first public install."""
    STATE.mkdir(parents=True, exist_ok=False)
    source_revision(run)
    found = tree(run.root, skip=("check",))
    run.check("complete", "the public install left a complete managed environment",
              found is not None and "state.json" in found
              and load(run.root / "state.json").get("complete") is True,
              tree_summary(found))
    save(STATE / "mark.json", {"tree": found, "bash_env_text": read_text(run.bash_env),
                               "path": os.environ.get("PATH", "")})
    return run.finish("Nothing. This step records the environment after the first public install.")


def reinstalled(run):
    """F8 (S1) through the public step: a second ansible-lint/install ran."""
    marked = load(STATE / "mark.json")
    found = tree(run.root, skip=("check",))
    changed = sorted(name for name in set(marked["tree"]) | set(found or {})
                     if marked["tree"].get(name) != (found or {}).get(name))
    run.check("no-reinstall", "after the second public install every file of the managed environment has "
              "the content and modification time it had before; nothing was downloaded or installed again",
              found == marked["tree"], {"entries": len(found or {}), "changed_entries": changed[:20],
                                         "not_compared": "check/, the working directory of the command check"})
    run.check("resolution", "BASH_ENV and PATH are as after the first install, so commands resolve as before",
              read_text(run.bash_env) == marked["bash_env_text"] and os.environ.get("PATH", "") == marked["path"]
              and all(path == str(run.root / "bin" / name) for name, path in which_all(run.names).items()),
              {"commands": which_all(run.names)})
    return run.finish("Nothing. The previous step was the public ansible-lint/install, for the second time.")


def consistent(run):
    """F8 (S1) through the script, to read what install prints."""
    run.start()
    result = run.result
    run.check("exit", "install succeeds", result["exit_code"] == 0, {"exit_code": result["exit_code"]})
    run.check("reused", "install reports that it reused the environment and downloaded or installed nothing",
              "(reused, nothing downloaded or installed)" in result["stdout"]
              and "installing the fixed set" not in result["stdout"]
              and "creating the virtual environment" not in result["stdout"])
    before = {name: value for name, value in run.before["tree"].items() if name.split(os.sep)[0] != "check"}
    after = {name: value for name, value in run.after["tree"].items() if name.split(os.sep)[0] != "check"}
    run.check("unchanged", "the managed environment is unchanged", before == after,
              {"entries": len(after)})
    run.check("resolution", "BASH_ENV is unchanged and the commands resolve as before",
              run.after["bash_env_text"] == run.before["bash_env_text"]
              and run.after["commands"] == run.before["commands"])
    output = {"selected_interpreter": "Python interpreter: %s (%s)" % (run.fixed["interpreter"]["path"],
                                                                      run.fixed["interpreter"]["version"]),
              "fixed_set": "fixed set: sha256:" + run.lock["fixed_set_sha256"],
              "versions": "versions: ansible-lint %s, Ansible package (ansible) %s, ansible-core %s" % (
                  run.fixed["distributions"]["ansible-lint"], run.fixed["distributions"]["ansible"],
                  run.fixed["distributions"]["ansible-core"]),
              "exposed_commands": "exposed commands in %s: %s" % (run.root / "bin", ", ".join(run.names)),
              "managed_environment": "managed environment: %s" % run.root,
              "ignored_pip_settings": "ignored pip settings"}
    missing = [name for name, text in output.items() if text not in result["stdout"]]
    run.check("output", "install prints the interpreter, the location, the fixed-set identifier, the three "
              "versions, the exposed commands and the ignored pip settings (contract section 9.5)",
              not missing, {"missing": missing})
    return run.finish("Nothing. The environment is the one of the public install.")


def tampered(run, description, change, restore, reason):
    """F7 (S2): an inconsistent environment is rejected and not repaired."""
    change()
    try:
        run.start()
    finally:
        tampered_tree = tree(run.root)
        restore()
    run.expect_failure(["inconsistent-environment"], reason="Reason [" + reason + "]")
    run.expect_tree("unchanged", "install repaired, changed and deleted nothing", "unchanged")
    run.check("restored", "the test restored the environment",
              tree(run.root, skip=("check",)) == load(STATE / "mark.json")["tree"],
              {"entries_while_inconsistent": len(tampered_tree or {})})
    return run.finish(description)


def changed_distribution(run):
    """F7 and F11: an installed distribution has another version."""
    version = run.fixed["distributions"]["mypy-extensions"]
    (metadata,) = (run.root / "venv/lib").glob("python*/site-packages/mypy_extensions-%s.dist-info/METADATA" % version)
    original = metadata.read_bytes()
    times = (metadata.stat().st_atime_ns, metadata.stat().st_mtime_ns)
    line = ("Version: %s" % version).encode("ascii")
    if original.count(line) != 1:
        raise ValueError("Unexpected METADATA of mypy-extensions")

    def change():
        metadata.write_bytes(original.replace(line, b"Version: 0.0.1"))

    def restore():
        metadata.write_bytes(original)
        os.utime(metadata, ns=times)

    return tampered(run, "The test changes the version in the installed metadata of one distribution "
                         "(mypy-extensions) to 0.0.1, as a later pip run could, and restores the file "
                         "with its times afterwards.", change, restore, "distributions")


def missing_cli(run):
    """F7: a required CLI is missing."""
    name = "ansible-config"
    if name not in run.fixed["runtime_clis"]:
        raise ValueError("ansible-config is no recorded run-time CLI")
    entry = run.root / "bin" / name
    hidden = Path(str(run.root) + ".hidden-by-orb-test")

    def change():
        os.rename(entry, hidden)

    def restore():
        os.rename(hidden, entry)

    return tampered(run, "The test moves bin/ansible-config, a recorded run-time CLI, out of the managed "
                         "environment and moves it back afterwards.", change, restore, "command")


# --- pip settings (F12) ---------------------------------------------------

def pip_settings_setup(run):
    """Write conflicting pip configuration files before the public install."""
    files = {
        run.home / ".config/pip/pip.conf":
            "[global]\nindex-url = https://user:%s@%s/simple\n\n[install]\ntarget = /tmp/ansible-lint-pip-target-user\n"
            % (PIP_SECRET, PIP_HOSTS[1]),
        Path(os.environ["PIP_CONFIG_FILE"]):
            "[global]\nindex-url = https://%s/simple\nno-index = true\n\n[install]\nprefix = /tmp/ansible-lint-pip-prefix\n"
            % PIP_HOSTS[2],
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    variables = sorted(name for name in os.environ if name.startswith("PIP_"))
    run.check("settings", "the job has conflicting pip settings: PIP_* variables with another index and a "
              "destination, a user configuration file and a file named by PIP_CONFIG_FILE",
              {"PIP_INDEX_URL", "PIP_TARGET", "PIP_CONFIG_FILE"} <= set(variables)
              and PIP_HOSTS[0] in os.environ.get("PIP_INDEX_URL", ""),
              {"pip_variable_names": variables, "configuration_files": [str(path) for path in files]})
    return run.finish("The job sets PIP_* variables in its environment. This step writes two pip "
                      "configuration files. The values name hosts that do not exist and destinations "
                      "outside the managed environment.")


def pip_settings(run):
    """F12: read what install prints about the settings it ignored."""
    run.start()
    result = run.result
    output = result["stdout"] + result["stderr"]
    variables = sorted(name for name in os.environ if name.startswith("PIP_"))
    (line,) = [text for text in result["stdout"].splitlines() if "ignored pip settings" in text] or [""]
    run.check("exit", "install succeeds", result["exit_code"] == 0, {"exit_code": result["exit_code"]})
    run.check("names", "install names every PIP_* variable and the configuration files it ignored",
              all(name in line for name in variables)
              and str(run.home / ".config/pip/pip.conf") in line
              and "the file named by PIP_CONFIG_FILE" in line,
              {"line": line, "pip_variable_names": variables})
    leaked = [value for value in (PIP_SECRET,) + PIP_HOSTS + ("/tmp/ansible-lint-pip-target",
                                                             "/tmp/ansible-lint-pip-prefix",
                                                             os.environ.get("PIP_CONFIG_FILE", "\0"))
              if value in output]
    run.check("no-values", "install prints no value of a pip setting: no URL, credential, destination or "
              "path of the named file", not leaked, {"leaked": leaked})
    destinations = [path for path in ("/tmp/ansible-lint-pip-target-environment",
                                      "/tmp/ansible-lint-pip-target-user", "/tmp/ansible-lint-pip-prefix")
                    if os.path.lexists(path)]
    run.check("destination", "nothing was installed to a destination named by the settings",
              not destinations, {"existing": destinations})
    return run.finish("Nothing in this step. The settings are those of scenario pip-settings-setup and of "
                      "the job environment; the public install ran with them before this step.")


# --- Other images -------------------------------------------------------

def unverified_image(run):
    """E5 and F2: an image without the verified interpreter and without any
    exposed command. The job sets it through the image parameter of python."""
    source_revision(run)
    interpreter = run.fixed["interpreter"]["path"]
    existing = ansible_on_path()
    version = "%d.%d.%d" % sys.version_info[:3]
    run.check("image", "this is not the default image of the python executor: the verified interpreter is "
              "missing, no command whose name starts with 'ansible' is on PATH, and no publishing token "
              "is present",
              not os.path.lexists(interpreter) and not existing and not os.environ.get("CIRCLE_TOKEN"),
              {"verified_interpreter": interpreter, "exists": os.path.lexists(interpreter),
               "ansible_commands_on_path": existing, "checker_python": version,
               "checker_interpreter": sys.executable,
               "pyenv_versions": sorted(os.listdir(run.home / ".pyenv/versions"))
               if os.path.isdir(run.home / ".pyenv/versions") else None,
               "os_release": (read_text("/etc/os-release") or "").splitlines()[:4]})
    run.start()
    run.expect_failure(["interpreter"], reason="No other Python is used")
    run.expect_tree("nothing-created", "install created no managed environment", "absent")
    return run.finish("Nothing. The image is the one that the job sets with the image parameter of the "
                      "python executor. Confirm its reference in the job's Spin up environment log.")


def default_executor(run):
    """E7 and F3: install on the existing default executor."""
    source_revision(run)
    interpreter = run.fixed["interpreter"]["path"]
    direct = run.fixed["direct_commands"]
    before = {name: subprocess.run([name, "--version"], capture_output=True, text=True, check=False)
              for name in direct}
    run.check("image", "this is the existing path: the four commands that execute calls are on PATH "
              "before install, and no publishing token is present",
              all(shutil.which(name) for name in direct) and not os.environ.get("CIRCLE_TOKEN")
              and all(result.returncode == 0 for result in before.values()),
              {"commands": which_all(direct), "verified_interpreter_exists": os.path.lexists(interpreter)})
    path = os.environ.get("PATH", "")
    run.start()
    run.expect_failure(["existing-command", "interpreter"])
    run.expect_tree("nothing-created", "install created no managed environment", "absent")
    after = {name: subprocess.run([name, "--version"], capture_output=True, text=True, check=False)
             for name in direct}
    run.check("existing-tools", "the existing tools and PATH are unchanged: the four commands resolve to the "
              "same files and print the same versions",
              os.environ.get("PATH", "") == path
              and all((before[name].returncode, before[name].stdout) == (after[name].returncode, after[name].stdout)
                      for name in direct),
              {"versions": {name: (after[name].stdout.splitlines() or [""])[0] for name in direct}})
    return run.finish("Nothing. The job uses the default executor of this commit's packed Orb.",
                      {"rejected_by": [line["category"] for line in run.result["failure_lines"]],
                       "note": "Contract E7: rejected through E6 (existing command) and possibly E5 "
                               "(interpreter). The category shows which check stopped install first."})


SCENARIOS = {
    "clean-start": clean_start,
    "existing-command": existing_command,
    "not-writable": not_writable,
    "location": location,
    "no-bash-env": no_bash_env,
    "no-venv": no_venv,
    "index-unreachable": index_unreachable,
    "foreign": foreign,
    "nothing-published": nothing_published,
    "mark": mark,
    "reinstalled": reinstalled,
    "consistent": consistent,
    "changed-distribution": changed_distribution,
    "missing-cli": missing_cli,
    "pip-settings-setup": pip_settings_setup,
    "pip-settings": pip_settings,
    "unverified-image": unverified_image,
    "default-executor": default_executor,
}


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in SCENARIOS:
        print("usage: check-install-script.py SOURCE_DIRECTORY SCENARIO\nscenarios: " + ", ".join(SCENARIOS),
              file=sys.stderr)
        return 2
    try:
        return SCENARIOS[sys.argv[2]](Run(sys.argv[1], sys.argv[2]))
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
        print("install script check failed unexpectedly (" + type(error).__name__ + ": " + str(error) + ")",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
