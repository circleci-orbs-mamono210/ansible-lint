#!/usr/bin/env python3
"""Check the base environment of the python executor (Redmine #5536).

The CI job runs on the default configuration of ``ansible-lint/python`` from
this commit's packed Orb. This script measures that container and records the
evidence. It uses only the Python standard library. It never installs
packages, never uses sudo, and prints environment values only from a fixed
safe list.

The container cannot see its own image digest. Confirm the full image
reference in the job's "Spin up environment" log.
"""

import json
import os
import platform
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


EVIDENCE = Path("/tmp/ansible-lint-python-executor-evidence")
# A version that is never installed. It shows how pyenv shims react to a
# repository's .python-version, independent of the installed versions.
PROBE_VERSION = "0.0.0-ansible-lint-orb-probe"
SAFE_VARIABLES = ("HOME", "USER", "SHELL", "PATH", "PYENV_ROOT", "PYENV_VERSION",
                  "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV")
DEFAULT_PATTERN = re.compile(r"^    default: (cimg/python@sha256:[0-9a-f]{64})$", re.MULTILINE)
INTERPRETER_REPORT = (
    "import json, platform, sys; "
    "print(json.dumps({'version': '%d.%d.%d' % sys.version_info[:3], "
    "'releaselevel': sys.version_info.releaselevel, 'executable': sys.executable, "
    "'prefix': sys.prefix, 'base_prefix': sys.base_prefix, "
    "'machine': platform.machine()}))"
)
DISTRIBUTIONS_REPORT = (
    "import importlib.metadata as m, json; "
    "print(json.dumps(sorted([d.metadata['Name'], d.version] for d in m.distributions())))"
)


def now():
    return datetime.now(timezone.utc).isoformat()


def run(command, cwd=None):
    """Run a command without a shell and return what it printed."""
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                timeout=600, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return {"command": command, "cwd": cwd, "exit_code": None,
                "error": type(error).__name__ + ": " + str(error)}
    return {"command": command, "cwd": cwd, "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def first_line(result):
    if not result:
        return None
    text = ((result.get("stdout") or "") + (result.get("stderr") or "")).strip()
    return text.splitlines()[0] if text else ""


def parse_json(result):
    if not result or result.get("exit_code") != 0:
        return None
    try:
        return json.loads(result["stdout"])
    except (KeyError, ValueError):
        return None


def ansible_commands_on_path():
    found = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory or not os.path.isdir(directory):
            continue
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            path = os.path.join(directory, name)
            if name.startswith("ansible") and os.path.isfile(path) and os.access(path, os.X_OK):
                found.append(path)
    return found


def writable(directory):
    try:
        probe = tempfile.mkdtemp(prefix="ansible-lint-orb-write-check-", dir=directory)
    except OSError as error:
        return {"directory": directory, "writable": False, "error": type(error).__name__}
    os.rmdir(probe)
    return {"directory": directory, "writable": True}


def os_release():
    values = {}
    try:
        lines = Path("/etc/os-release").read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        key, _, value = line.partition("=")
        if key in ("NAME", "VERSION_ID", "PRETTY_NAME"):
            values[key] = value.strip('"')
    return values


class Recorder:
    def __init__(self):
        self.checks = []

    def check(self, identifier, requirement, passed, observed):
        self.checks.append({"id": identifier, "requirement": requirement,
                            "passed": bool(passed), "observed": observed})
        print(("PASS " if passed else "FAIL ") + identifier + ": " + requirement, flush=True)


def measure(source, lock_name):
    source = Path(source).resolve()
    lock = json.loads((source / lock_name).read_text(encoding="utf-8"))
    selected = lock["selected_image"]
    interpreter = lock["expected_interpreter"]["path"]
    version = lock["expected_interpreter"]["version"]
    EVIDENCE.mkdir(parents=True, exist_ok=False)
    recorder = Recorder()
    observations = {}
    commands = []

    head = run(["git", "-C", str(source), "rev-parse", "HEAD"])
    commit = (head.get("stdout") or "").strip()
    recorder.check("P0", "The checked-out source is this pipeline's revision (CIRCLE_SHA1)",
                   head["exit_code"] == 0 and commit == os.environ.get("CIRCLE_SHA1"),
                   {"head": commit, "circle_sha1": os.environ.get("CIRCLE_SHA1")})

    executor = (source / "src/executors/python.yml").read_text(encoding="utf-8")
    defaults = DEFAULT_PATTERN.findall(executor)
    recorder.check("P1", "src/executors/python.yml pins the reference recorded in " + lock_name,
                   defaults == [selected["reference"]],
                   {"executor_defaults": defaults, "recorded_reference": selected["reference"]})

    machine = platform.machine()
    observed_platform = platform.system().lower() + "/" + {"x86_64": "amd64"}.get(machine, machine)
    recorder.check("P2", "The job runs on " + selected["platform"],
                   observed_platform == selected["platform"],
                   {"observed_platform": observed_platform})

    for identifier, tool in (("P3", "bash"), ("P4", "git")):
        location = shutil.which(tool)
        if location:
            result = run([tool, "--version"])
        else:
            result = {"command": [tool, "--version"], "exit_code": None, "error": "not on PATH"}
        commands.append(result)
        recorder.check(identifier, tool + " is available on PATH",
                       location is not None and result["exit_code"] == 0,
                       {"path": location, "version_line": first_line(result)})

    is_file = os.path.isfile(interpreter)
    executable = is_file and os.access(interpreter, os.X_OK)
    recorder.check("P5", "The recorded interpreter path exists and is executable", executable,
                   {"path": interpreter,
                    "realpath": os.path.realpath(interpreter) if is_file else None})

    report = run([interpreter, "-I", "-c", INTERPRETER_REPORT]) if executable else None
    details = parse_json(report)
    recorder.check("P6", "The interpreter reports Python " + version + " (final release)",
                   details is not None and details.get("version") == version
                   and details.get("releaselevel") == "final",
                   details if details is not None else {"result": report})

    pip_result = run([interpreter, "-I", "-m", "pip", "--version"]) if executable else None
    recorder.check("P7", "pip is available to the interpreter",
                   pip_result is not None and pip_result["exit_code"] == 0,
                   {"version_line": first_line(pip_result)})

    venv_record = {"created": False}
    if executable:
        parent = tempfile.mkdtemp(prefix="ansible-lint-orb-venv-check-")
        try:
            target = os.path.join(parent, "venv")
            create = run([interpreter, "-I", "-m", "venv", target])
            venv_record = {"created": create["exit_code"] == 0, "create": create}
            if venv_record["created"]:
                venv_python = os.path.join(target, "bin", "python")
                venv_pip = run([venv_python, "-I", "-m", "pip", "--version"])
                venv_record.update({
                    "pip_exit_code": venv_pip["exit_code"],
                    "pip_version_line": first_line(venv_pip),
                    "bootstrap_distributions": parse_json(
                        run([venv_python, "-I", "-c", DISTRIBUTIONS_REPORT])),
                })
        finally:
            shutil.rmtree(parent, ignore_errors=True)
    recorder.check("P8", "The interpreter creates a virtual environment that has pip",
                   venv_record.get("created") and venv_record.get("pip_exit_code") == 0,
                   venv_record)

    found = ansible_commands_on_path()
    recorder.check("P9", "No command whose name starts with 'ansible' is on PATH", not found,
                   {"found": found})

    home = writable(os.path.expanduser("~"))
    try:
        user = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        user = None
    recorder.check("P10", "The job user can write its home directory without sudo",
                   home["writable"],
                   {"home": home, "tmp": writable(tempfile.gettempdir()),
                    "uid": os.getuid(), "user": user})

    probe = tempfile.mkdtemp(prefix="ansible-lint-orb-python-version-probe-")
    try:
        Path(probe, ".python-version").write_text(PROBE_VERSION + "\n", encoding="utf-8")
        shim = run(["python3", "--version"], cwd=probe)
        absolute = run([interpreter, "--version"], cwd=probe) if executable else None
    finally:
        shutil.rmtree(probe, ignore_errors=True)
    observations["python_version_file_probe"] = {
        "python_version_file": PROBE_VERSION, "python3_on_path": shim,
        "recorded_interpreter": absolute}
    absolute_output = ((absolute or {}).get("stdout") or "") + ((absolute or {}).get("stderr") or "")
    recorder.check("P11", "A .python-version file does not change the recorded interpreter",
                   absolute is not None and absolute["exit_code"] == 0
                   and absolute_output.strip() == "Python " + version,
                   {"recorded_interpreter": absolute})

    resolution = {}
    for name in ("python", "python3", "pip", "pip3", "pyenv"):
        location = shutil.which(name)
        resolution[name] = {"path": location,
                            "realpath": os.path.realpath(location) if location else None}
    observations["command_resolution"] = resolution
    if resolution["pyenv"]["path"]:
        observations["pyenv"] = {
            key: run(["pyenv", *arguments]) for key, arguments in (
                ("pyenv_version", ["--version"]), ("root", ["root"]),
                ("version", ["version"]), ("versions", ["versions", "--bare"]),
                ("which_python3", ["which", "python3"]))}
    observations["environment"] = {name: os.environ.get(name) for name in SAFE_VARIABLES}
    observations["pip_variable_names"] = sorted(n for n in os.environ if n.startswith("PIP_"))
    observations["os_release"] = os_release()
    observations["kernel_release"] = platform.release()

    evidence = {
        "context": {
            "observed_at": now(), "ticket": 5536, "commit": commit,
            "job": os.environ.get("CIRCLE_JOB"), "job_url": os.environ.get("CIRCLE_BUILD_URL"),
            "configured_image_reference": selected["reference"],
            "image_reference_evidence": "The container cannot read its image digest. "
                                        "Confirm the full reference in this job's "
                                        "Spin up environment log.",
            "expected_platform": selected["platform"], "observed_platform": observed_platform,
        },
        "checks": recorder.checks,
        "observations": observations,
        "commands": commands,
    }
    (EVIDENCE / "python-executor.json").write_text(json.dumps(evidence, indent=2) + "\n",
                                                   encoding="utf-8")
    print(json.dumps(evidence, indent=2), flush=True)
    failed = [check["id"] for check in recorder.checks if not check["passed"]]
    if failed:
        print("Failed checks: " + ", ".join(failed), file=sys.stderr)
        return 1
    print("All python executor checks passed.", flush=True)
    return 0


def main(argv):
    if len(argv) != 3:
        print("usage: check-python-executor.py SOURCE_DIRECTORY LOCK_FILE", file=sys.stderr)
        return 2
    try:
        return measure(argv[1], argv[2])
    except Exception as error:  # Report the failure without dumping the environment.
        print("python executor check failed unexpectedly (" + type(error).__name__ + ": "
              + str(error) + ")", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
