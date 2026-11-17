#!/usr/bin/env python3
"""Minimal CI check of #5537: install, command resolution and the real execute.

The job python-install-test runs this file in three separate run steps, with
the verified interpreter by its absolute path and -I:

  before         clean-job checks, fixture, state before install
  after-install  managed environment, command resolution, effect on later steps
  after-execute  what the real ansible-lint/execute steps called and printed

Between the steps the job runs the public ansible-lint/install and
ansible-lint/execute of this commit's packed Orb. After install, this file puts
observers in front of the four commands that execute calls directly. An
observer passes arguments, environment and exit status through unchanged.

It uses only the standard library and changes nothing under src/.
#5539 expands this check; keep its success conditions when merging jobs.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = Path("/tmp/ansible-lint-python-install-evidence")
# Working state between the steps. It is not stored as an artifact.
STATE = Path("/tmp/ansible-lint-python-install-state")
ROOT_NAME = ".orbss-ansible-lint"
PROBE_VERSION = "0.0.0-ansible-lint-orb-probe"
FIXTURE = "tests/fixtures/normal"
FAMILIES = ("PYTHONPATH", "VIRTUAL_ENV", "PIP_", "PYENV_", "ANSIBLE_")
PUBLISHED_BLOCK = ("\n# orbss/ansible-lint install: Ansible commands of the managed environment\n"
                   "export PATH=%s:\"$PATH\"\n")
SUMMARY = re.compile(r"Passed: (\d+) failure\(s\), (\d+) warning\(s\) in (\d+) files processed of (\d+) encountered\.")

# Runs inside the managed environment and reports what is installed there.
QUERY = r"""
import importlib.metadata, json, sys
print(json.dumps({
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "version": "%d.%d.%d" % sys.version_info[:3],
    "distributions": sorted([d.metadata["Name"], d.version] for d in importlib.metadata.distributions()),
}))
"""

# Runs ansible-lint of the managed environment in its own interpreter and logs
# every program that this process starts. It is an observation run, not the
# execute step.
TRACE = r"""
import json, os, shutil, sys
log = sys.argv[1]
def hook(event, arguments):
    if event != "subprocess.Popen":
        return
    try:
        executable, argv, cwd, environment = arguments
        argv = [os.fsdecode(item) for item in argv] if isinstance(argv, (list, tuple)) else [os.fsdecode(argv)]
        path = (environment if environment is not None else os.environ).get("PATH", "")
        program = os.fsdecode(executable) if executable else argv[0]
        record = {"argv": argv, "resolved": shutil.which(program, path=path)}
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
    except Exception as error:  # never change the traced program
        with open(log, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"hook_error": repr(error)}) + "\n")
sys.addaudithook(hook)
sys.argv = [sys.argv[2]]
from importlib.metadata import entry_points
(entry,) = entry_points(group="console_scripts", name="ansible-lint")
sys.exit(entry.load()())
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def plain(text):
    # Remove presentation only: SGR colours and OSC-8 hyperlink delimiters.
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    return re.sub(r"\x1b\]8;;[^\x00-\x1f\x7f]*(?:\x1b\\|\x07)", "", text)


def run(command, cwd=None, env=None):
    try:
        result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, check=False)
    except OSError as error:
        return {"command": command, "cwd": cwd, "exit_code": None, "stdout": "", "stderr": str(error)}
    return {"command": command, "cwd": cwd, "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def resolution(names):
    found = {}
    for name in names:
        path = shutil.which(name)
        found[name] = {"path": path, "realpath": os.path.realpath(path) if path else None}
    return found


def ansible_on_path():
    found = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        try:
            names = sorted(os.listdir(directory)) if directory else []
        except OSError:
            continue
        found.extend(os.path.join(directory, name) for name in names if name.startswith("ansible"))
    return found


def environment_hashes():
    return {name: sha256(value.encode("utf-8", "surrogateescape")) for name, value in os.environ.items()}


def tree_hashes(directory):
    directory = Path(directory)
    return {str(path.relative_to(directory)): sha256(path.read_bytes())
            for path in sorted(directory.rglob("*")) if path.is_file()}


def file_hash(path):
    try:
        return sha256(Path(path).read_bytes())
    except OSError:
        return None


def fixed_information(source):
    # The object embedded in the install script of this commit.
    text = (Path(source) / "src/scripts/install.sh").read_text(encoding="utf-8")
    match = re.search(r'^FIXED_INFORMATION = json\.loads\(r"""\n(.*?)\n"""\)$', text, re.S | re.M)
    if not match:
        raise ValueError("The fixed information was not found in src/scripts/install.sh")
    fixed = json.loads(match.group(1))
    canonical = json.dumps(fixed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return fixed, sha256(canonical.encode("ascii"))


def expected_distributions(fixed):
    expected = dict(fixed["bootstrap_distributions"])
    expected.update(fixed["distributions"])
    return expected


def managed_distributions(root):
    result = run([str(root / "venv/bin/python"), "-I", "-c", QUERY])
    if result["exit_code"] != 0:
        raise ValueError("The managed interpreter did not answer: " + result["stderr"].strip())
    found = json.loads(result["stdout"])
    found["distributions"] = {normalize(name): version for name, version in found["distributions"]}
    return found


class Recorder:
    def __init__(self):
        self.checks = []

    def check(self, identifier, requirement, passed, observed):
        self.checks.append({"id": identifier, "requirement": requirement,
                            "passed": bool(passed), "observed": observed})
        print(("PASS " if passed else "FAIL ") + identifier + ": " + requirement, flush=True)


def finish(phase, recorder, evidence):
    evidence["checks"] = recorder.checks
    save(EVIDENCE / (phase + ".json"), evidence)
    failed = [check["id"] for check in recorder.checks if not check["passed"]]
    if failed:
        print(json.dumps(evidence, indent=2), flush=True)
        print("Failed checks: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


def context(source, lock, image_lock):
    return {
        "observed_at": now(),
        "ticket": 5537,
        "commit": os.environ.get("CIRCLE_SHA1"),
        "job": os.environ.get("CIRCLE_JOB"),
        "job_url": os.environ.get("CIRCLE_BUILD_URL"),
        "checker_interpreter": sys.executable,
        "checker_isolated": bool(sys.flags.isolated),
        "configured_image_reference": image_lock["selected_image"]["reference"],
        "image_reference_evidence": "The container cannot read its image digest. Confirm the full "
                                    "reference in this job's Spin up environment log.",
        "fixed_set_sha256": lock["fixed_set_sha256"],
        "source": str(source),
        "working_directory": os.getcwd(),
    }


def before(source):
    source = Path(source).resolve()
    lock = load(source / "python-install-lock.json")
    image_lock = load(source / "python-image-lock.json")
    EVIDENCE.mkdir(parents=True, exist_ok=False)
    STATE.mkdir(parents=True, exist_ok=False)
    recorder = Recorder()
    root = Path(os.environ["HOME"]) / ROOT_NAME

    head = run(["git", "-C", str(source), "rev-parse", "HEAD"])
    commit = head["stdout"].strip()
    recorder.check("T0", "The checked-out source is this pipeline's revision (CIRCLE_SHA1)",
                   head["exit_code"] == 0 and commit == os.environ.get("CIRCLE_SHA1"),
                   {"head": commit, "circle_sha1": os.environ.get("CIRCLE_SHA1")})

    fixed, identifier = fixed_information(source)
    recorder.check("T1", "The fixed information in src/scripts/install.sh equals python-install-lock.json "
                   "and names the verified interpreter of python-image-lock.json",
                   fixed == lock["fixed_information"] and identifier == lock["fixed_set_sha256"]
                   and fixed["interpreter"]["path"] == image_lock["expected_interpreter"]["path"] == sys.executable
                   and fixed["interpreter"]["version"] == image_lock["expected_interpreter"]["version"],
                   {"source_fixed_set_sha256": identifier, "recorded_fixed_set_sha256": lock["fixed_set_sha256"],
                    "equal_objects": fixed == lock["fixed_information"], "interpreter": fixed["interpreter"],
                    "checker_interpreter": sys.executable})

    existing = ansible_on_path()
    recorder.check("T2", "The job is clean: no managed environment, no command whose name starts with "
                   "'ansible' on PATH, no publishing token, and an empty working directory",
                   not os.path.lexists(root) and not existing and not os.environ.get("CIRCLE_TOKEN")
                   and not any(Path.cwd().iterdir()) and bool(sys.flags.isolated),
                   {"managed_environment": str(root), "managed_environment_exists": os.path.lexists(root),
                    "ansible_commands_on_path": existing,
                    "publishing_token_present": bool(os.environ.get("CIRCLE_TOKEN")),
                    "working_directory_entries": sorted(path.name for path in Path.cwd().iterdir())})

    # The input: the real playbook of the existing normal fixture, plus a
    # .python-version that names a version that is not installed.
    for path in sorted((source / FIXTURE).rglob("*")):
        if path.is_file():
            target = Path.cwd() / path.relative_to(source / FIXTURE)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    Path(".python-version").write_text(PROBE_VERSION + "\n", encoding="utf-8")
    files = tree_hashes(Path.cwd())

    pyenv_root = os.environ.get("PYENV_ROOT") or ""
    bash_env = os.environ.get("BASH_ENV") or ""
    bash_env_text = Path(bash_env).read_text(encoding="utf-8") if bash_env and os.path.exists(bash_env) else ""
    state = {
        "source": str(source),
        "working_directory": os.getcwd(),
        "root": str(root),
        "files": files,
        "path": os.environ.get("PATH", ""),
        "commands": resolution(["python", "python3", "pip", "pip3", "pyenv"]),
        "environment_hashes": environment_hashes(),
        "pyenv_version_file": os.path.join(pyenv_root, "version") if pyenv_root else None,
        "pyenv_version_file_sha256": file_hash(os.path.join(pyenv_root, "version")) if pyenv_root else None,
        "bash_env": bash_env,
        "bash_env_text": bash_env_text,
    }
    save(STATE / "before.json", state)

    evidence = {
        "context": context(source, lock, image_lock),
        "fixture": {"directory": FIXTURE, "added_file": ".python-version",
                    "python_version_file": PROBE_VERSION, "sha256": files},
        "observations": {
            "path": state["path"],
            "command_resolution": state["commands"],
            # How the job shell resolves Python in a directory with a
            # .python-version file. install must not depend on it.
            "python3_on_path_in_working_directory": run(["python3", "--version"], cwd=os.getcwd()),
            "family_variable_names": sorted(name for name in os.environ if name.startswith(FAMILIES)),
            "pip_variable_names": sorted(name for name in os.environ if name.startswith("PIP_")),
            "pyenv_version_file": state["pyenv_version_file"],
            "bash_env_bytes_before": len(bash_env_text.encode("utf-8")),
        },
    }
    return finish("before", recorder, evidence)


def after_install(source):
    source = Path(source).resolve()
    lock = load(source / "python-install-lock.json")
    image_lock = load(source / "python-image-lock.json")
    state = load(STATE / "before.json")
    fixed, identifier = lock["fixed_information"], lock["fixed_set_sha256"]
    root = Path(state["root"])
    commands, venv = root / "bin", root / "venv"
    recorder = Recorder()

    try:
        record = load(root / "state.json")
    except (OSError, ValueError) as error:
        record = {"error": str(error)}
    recorder.check("T3", "The state record is complete and names this Orb, the recorded fixed set and the "
                   "verified interpreter",
                   record.get("complete") is True and record.get("orb") == fixed["orb"]
                   and record.get("fixed_set_sha256") == identifier
                   and record.get("interpreter") == fixed["interpreter"]
                   and list(record)[-1:] == ["complete"],
                   {"state_record": record})

    working, checkout = os.path.realpath(state["working_directory"]), os.path.realpath(state["source"])
    real_root = os.path.realpath(root)
    separate = all(not (real_root + os.sep).startswith(place + os.sep) and not (place + os.sep).startswith(real_root + os.sep)
                   for place in (working, checkout))
    recorder.check("T4", "The managed environment is outside the working directory and the checkout",
                   separate and os.path.isdir(venv),
                   {"managed_environment": str(root), "working_directory": working, "checkout": checkout})

    try:
        managed = managed_distributions(root)
    except (OSError, ValueError) as error:
        managed = {"error": str(error), "distributions": {}}
    expected = expected_distributions(fixed)
    recorder.check("T5", "The installed distributions equal the fixed set plus the recorded bootstrap "
                   "distributions, in the verified interpreter's virtual environment",
                   managed["distributions"] == expected and managed.get("prefix") == str(venv)
                   and managed.get("version") == fixed["interpreter"]["version"],
                   {"prefix": managed.get("prefix"), "base_prefix": managed.get("base_prefix"),
                    "python_version": managed.get("version"), "installed": managed["distributions"],
                    "differences": {name: [expected.get(name), managed["distributions"].get(name)]
                                    for name in sorted(set(expected) | set(managed["distributions"]))
                                    if expected.get(name) != managed["distributions"].get(name)},
                    "ansible_lint": managed["distributions"].get("ansible-lint"),
                    "ansible_package": managed["distributions"].get("ansible"),
                    "ansible_core": managed["distributions"].get("ansible-core"),
                    "error": managed.get("error")})

    names = fixed["exposed_commands"]
    resolved = resolution(names)
    entries = sorted(os.listdir(commands)) if os.path.isdir(commands) else []
    kinds = {}
    for name in entries:
        entry = commands / name
        kinds[name] = ("link to " + os.readlink(entry)) if os.path.islink(entry) else "wrapper file"
    in_place = all(resolved[name]["path"] == str(commands / name) for name in names)
    recorder.check("T6", "In this separate step every exposed command, including the four direct commands "
                   "and the recorded run-time CLIs, resolves to the command directory of the managed "
                   "environment, and that directory holds nothing else",
                   in_place and entries == sorted(names)
                   and set(fixed["direct_commands"] + fixed["runtime_clis"]) <= set(names),
                   {"command_directory": str(commands), "entries": kinds, "resolution": resolved,
                    "direct_commands": fixed["direct_commands"], "runtime_clis": fixed["runtime_clis"]})

    versions = {name: run([name, "--version"], cwd=os.getcwd()) for name in fixed["direct_commands"]}
    lint = re.search(r"^ansible-lint (\S+) using ansible-core:(\S+) ansible-compat:(\S+) ruamel-yaml:(\S+)",
                     plain(versions["ansible-lint"]["stdout"]), re.M)
    core = re.search(r"^ansible \[core (\S+)\]", plain(versions["ansible"]["stdout"]), re.M)
    location = re.search(r"^\s*executable location = (.+)$", plain(versions["ansible"]["stdout"]), re.M)
    python = re.search(r"^\s*python version = (\S+) .*\((\S+)\)$", plain(versions["ansible"]["stdout"]), re.M)
    package = re.search(r"^Ansible community version (\S+)", plain(versions["ansible-community"]["stdout"]), re.M)
    galaxy = re.search(r"^ansible-galaxy \[core (\S+)\]", plain(versions["ansible-galaxy"]["stdout"]), re.M)
    observed = {
        "ansible_lint": lint.group(1) if lint else None,
        "ansible_lint_reports": {"ansible_core": lint.group(2), "ansible_compat": lint.group(3),
                                 "ruamel_yaml": lint.group(4)} if lint else None,
        "ansible_core": core.group(1) if core else None,
        "ansible_package": package.group(1) if package else None,
        "ansible_galaxy_core": galaxy.group(1) if galaxy else None,
        "ansible_executable_location": location.group(1) if location else None,
        "ansible_python_version": python.group(1) if python else None,
        "ansible_python_executable": python.group(2) if python else None,
        "exit_codes": {name: versions[name]["exit_code"] for name in versions},
    }
    recorder.check("T7", "The four direct commands run from the managed environment and report the recorded "
                   "versions; ansible-core and the Ansible package are checked separately",
                   all(code == 0 for code in observed["exit_codes"].values())
                   and observed["ansible_lint"] == expected["ansible-lint"]
                   and observed["ansible_core"] == observed["ansible_galaxy_core"] == expected["ansible-core"]
                   and observed["ansible_package"] == expected["ansible"]
                   and observed["ansible_lint_reports"] == {"ansible_core": expected["ansible-core"],
                                                            "ansible_compat": expected["ansible-compat"],
                                                            "ruamel_yaml": expected["ruamel-yaml"]}
                   and observed["ansible_executable_location"] == str(commands / "ansible")
                   and observed["ansible_python_version"] == fixed["interpreter"]["version"]
                   and observed["ansible_python_executable"] == str(venv / "bin/python"),
                   observed)

    # Which programs does the adopted ansible-lint start at run time?
    with tempfile.TemporaryDirectory(prefix="ansible-lint-orb-trace-") as temporary:
        project = Path(temporary) / "project"
        shutil.copytree(os.getcwd(), project)
        log = Path(temporary) / "programs.jsonl"
        log.write_text("", encoding="utf-8")
        environment = dict(os.environ)
        environment["PATH"] = str(venv / "bin") + os.pathsep + environment.get("PATH", "")
        traced = run([str(venv / "bin/python"), "-c", TRACE, str(log), str(venv / "bin/ansible-lint")],
                     cwd=str(project), env=environment)
        programs = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    started = [item for item in programs if "argv" in item]
    ansible = [item for item in started if os.path.basename(item["argv"][0]).startswith("ansible")]
    others = [item for item in started if item not in ansible]
    managed_places = (str(venv / "bin") + os.sep, str(commands) + os.sep)
    recorder.check("T8", "A traced run of the managed ansible-lint on the fixture succeeds, starts only "
                   "recorded run-time CLIs as Ansible commands, and each resolves inside the managed environment",
                   traced["exit_code"] == 0 and bool(ansible)
                   and not any("hook_error" in item for item in programs)
                   and {os.path.basename(item["argv"][0]) for item in ansible} <= set(fixed["runtime_clis"])
                   and all((item["resolved"] or "").startswith(managed_places) for item in ansible),
                   {"exit_code": traced["exit_code"],
                    "ansible_commands": ansible,
                    "ansible_command_names": sorted({os.path.basename(item["argv"][0]) for item in ansible}),
                    "other_programs": others,
                    "hook_errors": [item for item in programs if "hook_error" in item],
                    "summary": (SUMMARY.search(plain(traced["stderr"])) or [None])[0],
                    "method": "Python audit hook subprocess.Popen in the ansible-lint process. Programs "
                              "started by its child processes are not listed."})

    after = resolution(["python", "python3", "pip", "pip3", "pyenv"])
    recorder.check("T9", "python, python3, pip and pip3 resolve as before install",
                   after == state["commands"], {"before": state["commands"], "after": after})

    hashes = environment_hashes()
    changed = sorted(name for name in set(hashes) | set(state["environment_hashes"])
                     if hashes.get(name) != state["environment_hashes"].get(name))
    bash_env_text = Path(state["bash_env"]).read_text(encoding="utf-8") if state["bash_env"] else ""
    block = PUBLISHED_BLOCK % shlex.quote(str(commands))
    recorder.check("T10", "install changed only PATH for later steps: one export line in BASH_ENV, the command "
                   "directory in front of the earlier PATH, and no change of PYTHONPATH, VIRTUAL_ENV, PIP_*, "
                   "PYENV_* or ANSIBLE_*",
                   os.environ.get("PATH") == str(commands) + os.pathsep + state["path"]
                   and bash_env_text == state["bash_env_text"] + block
                   and not [name for name in changed if name.startswith(FAMILIES)],
                   {"path_before": state["path"], "path_after": os.environ.get("PATH"),
                    "bash_env_added_text": bash_env_text[len(state["bash_env_text"]):]
                    if bash_env_text.startswith(state["bash_env_text"]) else None,
                    "changed_variable_names": changed})

    files = tree_hashes(Path.cwd())
    pyenv_hash = file_hash(state["pyenv_version_file"]) if state["pyenv_version_file"] else None
    recorder.check("T11", "The working directory, its .python-version and the pyenv version file are unchanged",
                   files == state["files"] and pyenv_hash == state["pyenv_version_file_sha256"]
                   and Path(".python-version").read_text(encoding="utf-8") == PROBE_VERSION + "\n",
                   {"files": files, "pyenv_version_file": state["pyenv_version_file"],
                    "pyenv_version_file_unchanged": pyenv_hash == state["pyenv_version_file_sha256"]})

    # Observers for the real execute. They are added after install, because
    # install rejects a job where an exposed command already resolves elsewhere.
    observers = STATE / "bin"
    observers.mkdir()
    (STATE / "calls.jsonl").write_text("", encoding="utf-8")
    real = {}
    for name in fixed["direct_commands"]:
        real[name] = shutil.which(name)
        wrapper = observers / name
        wrapper.write_text("#!/bin/bash\nexec %s -I %s observe %s %s \"$@\"\n" % (
            shlex.quote(sys.executable), shlex.quote(str(Path(__file__).resolve())),
            shlex.quote(name), shlex.quote(real[name] or "missing")), encoding="utf-8")
        wrapper.chmod(0o755)
    with open(state["bash_env"], "a", encoding="utf-8") as stream:
        stream.write("\n# python-install-test: observers of the commands that execute calls\n"
                     "export PATH=%s:\"$PATH\"\n" % shlex.quote(str(observers)))
    save(STATE / "after-install.json", {"real": real, "state_record_sha256": file_hash(root / "state.json"),
                                        "distributions": managed["distributions"]})

    evidence = {"context": context(source, lock, image_lock),
                "observations": {"direct_command_outputs": versions, "observed_commands": real,
                                 "traced_run_stderr": traced["stderr"]}}
    return finish("after-install", recorder, evidence)


def observe(name, real, arguments):
    # Pass everything through; record the call and the unchanged outputs.
    calls = STATE / "calls.jsonl"
    index = len(calls.read_text(encoding="utf-8").splitlines())
    with calls.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"index": index, "name": name, "arguments": arguments,
                                 "real": real, "started_at": now()}) + "\n")
    result = subprocess.run([real, *arguments], capture_output=True, check=False)
    for stream_name, data in (("stdout", result.stdout), ("stderr", result.stderr)):
        (STATE / ("call-%d.%s" % (index, stream_name))).write_bytes(data)
        getattr(sys, stream_name).buffer.write(data)
        getattr(sys, stream_name).flush()
    (STATE / ("call-%d.exit" % index)).write_text(str(result.returncode), encoding="utf-8")
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def after_execute(source):
    source = Path(source).resolve()
    lock = load(source / "python-install-lock.json")
    image_lock = load(source / "python-image-lock.json")
    state = load(STATE / "before.json")
    installed = load(STATE / "after-install.json")
    root = Path(state["root"])
    recorder = Recorder()

    calls = [json.loads(line) for line in (STATE / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    for call in calls:
        exit_file = STATE / ("call-%d.exit" % call["index"])
        call["exit_code"] = int(exit_file.read_text(encoding="utf-8")) if exit_file.exists() else None
        for stream_name in ("stdout", "stderr"):
            path = STATE / ("call-%d.%s" % (call["index"], stream_name))
            call[stream_name] = path.read_bytes().decode("utf-8", "replace") if path.exists() else None
    wanted = [["ansible-lint", ["--version"]], ["ansible", ["--version"]],
              ["ansible-community", ["--version"]], ["ansible-lint", []]]
    recorder.check("T12", "The real execute steps called ansible-lint --version, ansible --version, "
                   "ansible-community --version and ansible-lint without arguments, in this order and "
                   "nothing else; each call ran the command of the managed environment and returned 0",
                   [[call["name"], call["arguments"]] for call in calls] == wanted
                   and all(call["exit_code"] == 0 for call in calls)
                   and all(call["real"] == str(root / "bin" / call["name"]) for call in calls),
                   {"calls": [{key: call[key] for key in ("index", "name", "arguments", "real", "exit_code")}
                              for call in calls]})

    final = calls[-1] if calls else {"stderr": "", "stdout": ""}
    summary = SUMMARY.search(plain(final.get("stderr") or ""))
    numbers = [int(value) for value in summary.groups()] if summary else None
    recorder.check("T13", "The final lint of execute processed the real Ansible file of the fixture with no "
                   "violation: 0 failures, 0 warnings, 1 file processed of the %d files in the working "
                   "directory" % len(state["files"]),
                   numbers == [0, 0, 1, len(state["files"])],
                   {"summary": summary.group(0) if summary else None, "numbers": numbers,
                    "files_in_working_directory": sorted(state["files"])})

    files = tree_hashes(Path.cwd())
    try:
        distributions = managed_distributions(root)["distributions"]
    except (OSError, ValueError) as error:
        distributions = {"error": str(error)}
    recorder.check("T14", "After execute the working directory, the state record and the installed "
                   "distributions are unchanged",
                   files == state["files"] and distributions == installed["distributions"]
                   and file_hash(root / "state.json") == installed["state_record_sha256"],
                   {"files": files, "state_record_sha256": file_hash(root / "state.json")})

    code = finish("after-execute", recorder, {
        "context": context(source, lock, image_lock),
        "observations": {"execute_outputs": [{key: call[key] for key in ("name", "arguments", "stdout", "stderr")}
                                             for call in calls]}})
    phases = {phase: load(EVIDENCE / (phase + ".json")) for phase in ("before", "after-install", "after-execute")}
    combined = {"ticket": 5537, "result": "passed" if code == 0 else "failed",
                "commit": os.environ.get("CIRCLE_SHA1"), "job_url": os.environ.get("CIRCLE_BUILD_URL"),
                "checks": {check["id"]: check["passed"] for phase in phases.values() for check in phase["checks"]},
                "phases": phases}
    save(EVIDENCE / "python-install.json", combined)
    print(json.dumps(combined, indent=2), flush=True)
    if code == 0:
        print("All python install checks passed.", flush=True)
    return code


def main():
    actions = {"before": before, "after-install": after_install, "after-execute": after_execute}
    try:
        if len(sys.argv) >= 4 and sys.argv[1] == "observe":
            return observe(sys.argv[2], sys.argv[3], sys.argv[4:])
        if len(sys.argv) != 3 or sys.argv[1] not in actions:
            print("usage: check-python-install.py before|after-install|after-execute SOURCE_DIRECTORY",
                  file=sys.stderr)
            return 2
        return actions[sys.argv[1]](sys.argv[2])
    except (OSError, ValueError, KeyError, IndexError) as error:
        print("python install check failed unexpectedly (" + type(error).__name__ + ": " + str(error) + ")",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
