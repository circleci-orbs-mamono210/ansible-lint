#!/usr/bin/env python3
"""Checks of the new path: install, command resolution and the real execute.

A job runs this file in three separate run steps, with the verified
interpreter by its absolute path and -I:

  before         clean-job checks, fixture, state before install
  after-install  managed environment, command resolution, effect on later steps
  after-execute  what the real ansible-lint/execute steps called and printed

Between the steps the job runs the public ansible-lint/install and
ansible-lint/execute of this commit's packed Orb. After install, this file puts
observers in front of the four commands that execute calls directly. An
observer passes arguments, environment and exit status through unchanged.

#5537 made this the minimal CI of install (job python-install-test, case
"normal", checks T0 to T14). #5539 keeps those checks and their conditions and
adds cases for the other inputs of the new path and checks T15 to T18. The
case names the fixture and what execute is expected to call (CASES below).

It uses only the standard library and changes nothing under src/.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = Path("/tmp/ansible-lint-python-install-evidence")
# Working state between the steps. It is not stored as an artifact.
STATE = Path("/tmp/ansible-lint-python-install-state")
ROOT_NAME = ".orbss-ansible-lint"
PROBE_VERSION = "0.0.0-ansible-lint-orb-probe"
# The pinned external role of the fixtures, as in .circleci/integration-test.py.
EPEL = "747af654d2a2e05c1cfabce9c0b79b2a1eae3650"
EPEL_REPOSITORY = "https://github.com/ansible-roles-mamono210/epel"
REPOSITORY = "https://github.com/circleci-orbs-mamono210/ansible-lint"
ROLES = Path("/tmp/ansible-lint-installed-roles")
GIT_EVIDENCE = Path("/tmp/ansible-lint-ci-evidence")
PLAYBOOK = ["install", "-r", "roles/requirements.yml"]
MOLECULE = ["install", "-r", "molecule/default/requirements.yml"]
# CircleCI Docker resource classes: CPU cores and memory in bytes.
RESOURCE_CLASSES = {"small": (1.0, 2 * 1024 ** 3), "medium": (2.0, 4 * 1024 ** 3)}

# One entry for each input of the new path. The fixtures, the flags of execute
# and the pinned role are those of the existing path, so that results can be
# compared (tests/README.md).
#   fixture   directory copied into the empty working directory
#   probe     add a .python-version that names a version that is not installed
#   galaxy    ansible-galaxy calls that execute must make, in this order
#   roles     roles that must be installed afterwards, with their revision
#   lint      "exact": 1 file processed, every file encountered
#             "passed": at least 1 file processed, no failure and no warning
#             "violation": the one expected violation (tests/python-negative-expected.json)
#   marker    the fixture has a project marker, so lint may add .ansible/ to it
CASES = {
    # The minimal CI of #5537. Do not change this entry.
    "normal": {"fixture": "tests/fixtures/normal", "probe": True, "galaxy": [], "roles": [],
               "lint": "exact", "marker": False, "resource_class": "small"},
    # The same playbook without the probe file: the input of normal-test.
    "plain": {"fixture": "tests/fixtures/normal", "probe": False, "galaxy": [], "roles": [],
              "lint": "exact", "marker": False, "resource_class": "small"},
    # Both flags false, but Molecule requirements exist.
    "molecule": {"fixture": "test_resources", "probe": False, "galaxy": [MOLECULE],
                 "roles": [["mamono210.epel", EPEL]],
                 "lint": "passed", "marker": True, "resource_class": "small"},
    "role": {"fixture": "test_resources", "probe": False, "galaxy": ["SELF", MOLECULE],
             "roles": [["ansible-lint", "COMMIT"], ["mamono210.epel", EPEL]],
             "lint": "passed", "marker": True, "resource_class": "small"},
    "playbook": {"fixture": "tests/fixtures/playbook", "probe": False,
                 "galaxy": [PLAYBOOK, MOLECULE],
                 "roles": [["fixture_playbook_epel", EPEL], ["fixture_molecule_epel", EPEL]],
                 "lint": "passed", "marker": True, "resource_class": "small"},
    "both": {"fixture": "tests/fixtures/playbook", "probe": False,
             "galaxy": ["SELF", PLAYBOOK, MOLECULE],
             "roles": [["ansible-lint", "COMMIT"], ["fixture_playbook_epel", EPEL],
                       ["fixture_molecule_epel", EPEL]],
             "lint": "passed", "marker": True, "resource_class": "small"},
    "resource-class": {"fixture": "tests/fixtures/playbook", "probe": False,
                       "galaxy": [PLAYBOOK, MOLECULE],
                       "roles": [["fixture_playbook_epel", EPEL], ["fixture_molecule_epel", EPEL]],
                       "lint": "passed", "marker": True, "resource_class": "medium"},
    "negative": {"fixture": "tests/fixtures/negative", "probe": False, "galaxy": [], "roles": [],
                 "lint": "violation", "marker": False, "resource_class": "small"},
}
NEGATIVE_EXPECTED = "tests/python-negative-expected.json"
EXISTING_NEGATIVE_EXPECTED = "tests/negative-expected.json"
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


def home_snapshot(home, root):
    # Every entry below the home directory except the managed environment:
    # kind, and for files and links their size and modification time. A change
    # of a directory's own time follows from an added or removed entry, which
    # is reported itself, so it is not recorded.
    found, errors = {}, []
    home, root = os.path.realpath(home), os.path.realpath(root)

    def note(error):
        errors.append(str(error))

    for directory, directories, files in os.walk(home, onerror=note, followlinks=False):
        if directory == home and os.path.basename(root) in directories and os.path.dirname(root) == home:
            directories.remove(os.path.basename(root))
        for name in directories + files:
            path = os.path.join(directory, name)
            try:
                status = os.lstat(path)
            except OSError as error:
                errors.append(str(error))
                continue
            relative = os.path.relpath(path, home)
            if stat.S_ISDIR(status.st_mode):
                found[relative] = ["d"]
            elif stat.S_ISLNK(status.st_mode):
                found[relative] = ["l", os.readlink(path)]
            else:
                found[relative] = ["f", status.st_size, status.st_mtime_ns]
    return {"entries": found, "errors": errors}


def snapshot_difference(before, after):
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    return {"added": added, "removed": removed, "changed": changed}


def read_first(*paths):
    for path in paths:
        try:
            return path, Path(path).read_text(encoding="ascii").strip()
        except OSError:
            continue
    return None, None


def resource_limits():
    # What the container can see of its own limits (cgroup v2, then v1).
    cpu_path, cpu_text = read_first("/sys/fs/cgroup/cpu.max")
    cores = None
    if cpu_text:
        quota, _, period = cpu_text.partition(" ")
        if quota.isdigit() and period.isdigit() and int(period):
            cores = int(quota) / int(period)
    else:
        quota_path, quota = read_first("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us")
        _, period = read_first("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us")
        cpu_path, cpu_text = quota_path, "%s %s" % (quota, period)
        if quota and period and quota.isdigit() and period.isdigit() and int(period):
            cores = int(quota) / int(period)
    memory_path, memory_text = read_first("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes")
    memory = int(memory_text) if memory_text and memory_text.isdigit() else None
    return {"cpu_source": cpu_path, "cpu_raw": cpu_text, "cpu_cores": cores,
            "memory_source": memory_path, "memory_raw": memory_text, "memory_bytes": memory,
            "processors_visible": os.cpu_count()}


def expected_galaxy_calls(case, commit):
    calls = []
    for call in CASES[case]["galaxy"]:
        calls.append(["install", "git+" + os.environ.get("CIRCLE_REPOSITORY_URL", "") + "," + commit]
                     if call == "SELF" else list(call))
    return calls


def expected_roles(case, commit):
    return [[name, commit if version == "COMMIT" else version] for name, version in CASES[case]["roles"]]


def repository_name(url):
    # The identity of a GitHub repository, without credentials or queries.
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.split(":", 1)[1]
    return url[:-4] if url.endswith(".git") else url


def clean_lines(raw):
    # The normalization of .circleci/negative-test.py: remove presentation
    # only, reject other control codes, and count each stripped line.
    text = plain(raw.decode("utf-8", errors="strict"))
    if any(ord(character) < 32 and character not in "\n\r\t" for character in text) or "\x7f" in text:
        raise ValueError("Unrecognized output control code")
    return Counter(line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip())


def classify_negative(code, stdout, stderr, expected):
    """Accept only the one expected lint failure of the negative fixture.

    Required: the exact exit code, exactly the expected lines on standard
    output, and on standard error every expected line of the finding. Each
    optional notice may appear once, and one release notice in the wording of
    this path. Any other line is rejected, so a failed installation or
    download is never taken for the lint violation.
    """
    if code != expected["exit_code"] or code == 0:
        raise ValueError("Unexpected real linter exit code")
    if clean_lines(stdout) != Counter(expected["stdout_lines"]):
        raise ValueError("Unexpected stdout diagnostic or unclassified line")
    actual = clean_lines(stderr)
    required = Counter(expected["stderr_lines"])
    if not actual >= required:
        raise ValueError("Missing expected stderr line")
    remaining = actual - required
    notices = []
    for notice in expected.get("optional_stderr_notices", []):
        block = Counter(notice["lines"])
        if block and remaining >= block:
            remaining.subtract(block)
            notices.append({"id": notice["id"], "count": 1, "lines": notice["lines"]})
    current = expected["measurement"]["ansible_lint"]
    release = re.compile(
        r"A new release of ansible-lint is available: " + re.escape(current) +
        r" → (0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
        r" Upgrade by running: " + re.escape(expected["release_notice_command"]))
    for line, count in list(remaining.items()):
        match = release.fullmatch(line)
        if count and match and tuple(map(int, match.groups())) > tuple(map(int, current.split("."))):
            remaining.subtract({line: 1})
            notices.append({"id": "ansible-lint-new-release", "count": 1, "lines": [line]})
            break
    if any(remaining.values()):
        raise ValueError("Unexpected stderr diagnostic or unclassified line")
    return notices


def self_test(source):
    """Show that classify_negative accepts the expected failure and nothing else."""
    expected = load(Path(source) / NEGATIVE_EXPECTED)
    stdout = "\n".join(expected["stdout_lines"]) + "\n"
    lines = expected["stderr_lines"]
    stderr = "\n".join(lines) + "\n"
    optional = ["\n".join(notice["lines"]) + "\n" for notice in expected["optional_stderr_notices"]]
    current = expected["measurement"]["ansible_lint"]
    newer = "A new release of ansible-lint is available: %s → 99.0.0 Upgrade by running: " % current
    notice = newer + expected["release_notice_command"] + "\n"
    code = expected["exit_code"]
    cases = [
        ("the exact expected failure", True, code, stdout, stderr),
        ("with one release notice in the wording of this path", True, code, stdout, stderr + notice),
        ("coloured output with the same text", True, code, "\x1b[31m" + stdout + "\x1b[0m", stderr),
        ("with every optional notice once", True, code, stdout, stderr + "".join(optional)),
        ("an optional notice twice", False, code, stdout, stderr + optional[0] + optional[0]),
        ("a part of an optional notice", False, code, stdout,
         stderr + expected["optional_stderr_notices"][0]["lines"][0] + "\n"),
        ("an optional notice with another HTTP status", False, code, stdout,
         stderr + optional[0].replace("304: 'Not Modified'", "403: 'Forbidden'")),
        ("exit code 0", False, 0, stdout, stderr),
        ("another exit code", False, code + 1, stdout, stderr),
        ("another rule", False, code, stdout.replace("name[missing]", "syntax-check[specific]"), stderr),
        ("another file", False, code, stdout.replace("playbook.yml", "other.yml"), stderr),
        ("an extra finding", False, code, stdout + "fqcn[action-core]: Use FQCN\nother.yml:1\n", stderr),
        ("a download error next to the finding", False, code, stdout, stderr + "ERROR: Failed to download role\n"),
        ("an unknown line", False, code, stdout, stderr + "unclassified diagnostic\n"),
        ("a missing line of the finding", False, code, stdout,
         "\n".join(lines[1:]) + "\n"),
        ("a repeated line of the finding", False, code, stdout, stderr + expected["stderr_lines"][0] + "\n"),
        ("two release notices", False, code, stdout, stderr + notice + notice),
        ("the release notice of the existing path", False, code, stdout,
         stderr + newer + "pip3 install --user --upgrade ansible-lint\n"),
        ("a release notice for an older version", False, code, stdout,
         stderr + notice.replace("99.0.0", "0.0.1")),
        ("an unknown control code", False, code, stdout, stderr + "\x07\n"),
    ]
    failed = 0
    for name, accepted, exit_code, out, err in cases:
        try:
            classify_negative(exit_code, out.encode("utf-8"), err.encode("utf-8"), expected)
            result = True
        except ValueError:
            result = False
        ok = result == accepted
        failed += not ok
        print("%s %s: %s" % ("PASS" if ok else "FAIL", "accepts" if accepted else "rejects", name), flush=True)
    print("negative classification self-test: %d cases, %d failed" % (len(cases), failed), flush=True)
    return 1 if failed else 0


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


def context(source, lock, image_lock, case):
    return {
        "observed_at": now(),
        "ticket": 5537,
        "expanded_by": 5557 if case == "both" else 5539,
        "case": case,
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


def pre_install_facts(directory):
    # What an inline step recorded before install, in a job that runs install
    # before the checkout: text files with one value or one name per line.
    directory = Path(directory)

    def text(name):
        return (directory / name).read_text(encoding="utf-8")

    def names(name):
        return [line for line in text(name).splitlines() if line]

    def entries(name):
        # One line for each entry below the home directory, written by find:
        # "d<TAB>path" or "kind<TAB>size<TAB>modification time<TAB>path".
        found = {}
        for line in names(name):
            fields = line.split("\t")
            found[fields[-1]] = fields[:-1]
        return found

    commands = {}
    for line in names("commands"):
        name, _, path = line.partition("=")
        commands[name] = {"path": path or None}
    # The checkout of this job runs after install and adds files to the home
    # directory (~/.ssh), so the state after install is also recorded inline,
    # before the checkout.
    home_before, home_after = entries("home-entries"), entries("home-entries-after-install")
    return {"path": text("path").rstrip("\n"), "commands": commands,
            "bash_env": text("bash-env-path").strip(), "bash_env_text": text("bash-env"),
            "home": names("home"), "home_after_install": names("home-after-install"),
            "home_difference": snapshot_difference(home_before, home_after),
            "home_entries_compared": len(home_after),
            "ansible_commands": names("ansible-commands"),
            "managed_environment_exists": text("managed").strip() != "no",
            "publishing_token_present": text("token").strip() != "no",
            "working_directory_entries": names("working-directory")}


def before(source, case, pre_install=None):
    source = Path(source).resolve()
    lock = load(source / "python-install-lock.json")
    image_lock = load(source / "python-image-lock.json")
    settings = CASES[case]
    facts = pre_install_facts(pre_install) if pre_install else None
    EVIDENCE.mkdir(parents=True, exist_ok=False)
    STATE.mkdir(parents=True, exist_ok=bool(facts))
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

    if facts:
        # install already ran. The clean state is what the inline step saw
        # before it; the working directory must still be empty now.
        recorder.check("T2", "The job is clean: no managed environment, no command whose name starts with "
                       "'ansible' on PATH, no publishing token, and an empty working directory",
                       not facts["managed_environment_exists"] and not facts["ansible_commands"]
                       and not facts["publishing_token_present"] and not facts["working_directory_entries"]
                       and not os.environ.get("CIRCLE_TOKEN")
                       and not any(Path.cwd().iterdir()) and bool(sys.flags.isolated),
                       {"recorded_by": "the inline step before install; install ran before the checkout",
                        "managed_environment": str(root),
                        "managed_environment_existed_before_install": facts["managed_environment_exists"],
                        "ansible_commands_on_path_before_install": facts["ansible_commands"],
                        "publishing_token_present": facts["publishing_token_present"]
                        or bool(os.environ.get("CIRCLE_TOKEN")),
                        "working_directory_entries_before_install": facts["working_directory_entries"],
                        "working_directory_entries_after_install_and_checkout":
                            sorted(path.name for path in Path.cwd().iterdir())})
    else:
        existing = ansible_on_path()
        recorder.check("T2", "The job is clean: no managed environment, no command whose name starts with "
                       "'ansible' on PATH, no publishing token, and an empty working directory",
                       not os.path.lexists(root) and not existing and not os.environ.get("CIRCLE_TOKEN")
                       and not any(Path.cwd().iterdir()) and bool(sys.flags.isolated),
                       {"managed_environment": str(root), "managed_environment_exists": os.path.lexists(root),
                        "ansible_commands_on_path": existing,
                        "publishing_token_present": bool(os.environ.get("CIRCLE_TOKEN")),
                        "working_directory_entries": sorted(path.name for path in Path.cwd().iterdir())})

    wanted = settings["resource_class"]
    cores, memory = RESOURCE_CLASSES[wanted]
    limits = resource_limits()
    # Only the memory limit decides. CircleCI may give a CPU quota above the
    # cores of the class, depending on the plan, so the quota is recorded and
    # not compared.
    recorder.check("T15", "The container has the memory limit of the configured resource class (%s): "
                   "%d bytes" % (wanted, memory),
                   limits["memory_bytes"] == memory,
                   dict(limits, expected_resource_class=wanted, expected_memory_bytes=memory,
                        cpu_cores_of_the_class=cores,
                        note="The memory limit must be readable and equal. The CPU quota is an "
                             "observation only. CircleCI's record of the job names the class as well."))

    # The input: a fixture of this repository. Case "normal" also gets a
    # .python-version that names a version that is not installed.
    fixture = source / settings["fixture"]
    for path in sorted(fixture.rglob("*")):
        if path.is_file() and ".ansible" not in path.parts and "__pycache__" not in path.parts:
            target = Path.cwd() / path.relative_to(fixture)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    if settings["probe"]:
        Path(".python-version").write_text(PROBE_VERSION + "\n", encoding="utf-8")
    files = tree_hashes(Path.cwd())

    pyenv_root = os.environ.get("PYENV_ROOT") or ""
    probe_run = run(["python3", "--version"], cwd=os.getcwd())
    if facts:
        bash_env, bash_env_text = facts["bash_env"], facts["bash_env_text"]
    else:
        bash_env = os.environ.get("BASH_ENV") or ""
        bash_env_text = Path(bash_env).read_text(encoding="utf-8") if bash_env and os.path.exists(bash_env) else ""
    state = {
        "case": case,
        "commit": commit,
        "pre_install": bool(facts),
        "source": str(source),
        "working_directory": os.getcwd(),
        "root": str(root),
        "files": files,
        "path": facts["path"] if facts else os.environ.get("PATH", ""),
        "commands": facts["commands"] if facts else resolution(["python", "python3", "pip", "pip3", "pyenv"]),
        "environment_hashes": None if facts else environment_hashes(),
        "pyenv_version_file": os.path.join(pyenv_root, "version") if pyenv_root else None,
        "pyenv_version_file_sha256": file_hash(os.path.join(pyenv_root, "version")) if pyenv_root else None,
        "bash_env": bash_env,
        "bash_env_text": bash_env_text,
        "home_top_level": facts["home"] if facts else sorted(os.listdir(os.environ["HOME"])),
        "pre_install_home": {key: facts[key] for key in ("home_after_install", "home_difference",
                                                         "home_entries_compared")} if facts else None,
    }
    save(STATE / "before.json", state)
    # The last action of this step: the home directory as install will find it.
    if not facts:
        save(STATE / "home-before.json", home_snapshot(os.environ["HOME"], root))

    evidence = {
        "context": context(source, lock, image_lock, case),
        "fixture": {"directory": settings["fixture"],
                    "added_file": ".python-version" if settings["probe"] else None,
                    "python_version_file": PROBE_VERSION if settings["probe"] else None, "sha256": files},
        "observations": {
            "path": state["path"],
            "command_resolution": state["commands"],
            # How the job shell resolves Python in the working directory, which
            # holds a .python-version file in case "normal". install must not
            # depend on it.
            "python3_on_path_in_working_directory": probe_run,
            "family_variable_names": sorted(name for name in os.environ if name.startswith(FAMILIES)),
            "pip_variable_names": sorted(name for name in os.environ if name.startswith("PIP_")),
            "pyenv_version_file": state["pyenv_version_file"],
            "bash_env_bytes_before": len(bash_env_text.encode("utf-8")),
        },
    }
    return finish("before", recorder, evidence)


def traced_lint(recorder, fixed, venv, commands, expected_code):
    """T8: run the managed ansible-lint once more, on a copy of the working
    directory, and log every program that its process starts."""
    with tempfile.TemporaryDirectory(prefix="ansible-lint-orb-trace-") as temporary:
        project = Path(temporary) / "project"
        shutil.copytree(os.getcwd(), project, symlinks=True)
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
    recorder.check("T8", "A traced run of the managed ansible-lint on the fixture %s, starts only "
                   "recorded run-time CLIs as Ansible commands, and each resolves inside the managed environment"
                   % ("succeeds" if expected_code == 0 else "ends with exit code %d" % expected_code),
                   traced["exit_code"] == expected_code and bool(ansible)
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
    return traced


def after_install(source):
    source = Path(source).resolve()
    lock = load(source / "python-install-lock.json")
    image_lock = load(source / "python-image-lock.json")
    state = load(STATE / "before.json")
    case, settings = state["case"], CASES[state["case"]]
    fixed, identifier = lock["fixed_information"], lock["fixed_set_sha256"]
    root = Path(state["root"])
    commands, venv = root / "bin", root / "venv"
    recorder = Recorder()
    # First of all: the home directory as install left it.
    home_after = home_snapshot(os.environ["HOME"], root)
    home_top_level = sorted(os.listdir(os.environ["HOME"]))

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

    # Which programs does the adopted ansible-lint start at run time? The
    # other cases answer this after execute, when their roles are installed.
    traced = None
    if settings["lint"] == "exact":
        traced = traced_lint(recorder, fixed, venv, commands, 0)

    after = resolution(["python", "python3", "pip", "pip3", "pyenv"])
    if state["pre_install"]:
        # The inline step recorded the paths only.
        after = {name: {"path": found["path"]} for name, found in after.items()}
    recorder.check("T9", "python, python3, pip and pip3 resolve as before install",
                   after == state["commands"], {"before": state["commands"], "after": after})

    hashes = environment_hashes()
    if state["environment_hashes"] is None:
        # No values were recorded before install. BASH_ENV is the only way
        # for install to reach later steps, and it is compared in full below.
        changed = None
    else:
        changed = sorted(name for name in set(hashes) | set(state["environment_hashes"])
                         if hashes.get(name) != state["environment_hashes"].get(name))
    bash_env_text = Path(state["bash_env"]).read_text(encoding="utf-8") if state["bash_env"] else ""
    block = PUBLISHED_BLOCK % shlex.quote(str(commands))
    recorder.check("T10", "install changed only PATH for later steps: one export line in BASH_ENV, the command "
                   "directory in front of the earlier PATH, and no change of PYTHONPATH, VIRTUAL_ENV, PIP_*, "
                   "PYENV_* or ANSIBLE_*",
                   os.environ.get("PATH") == str(commands) + os.pathsep + state["path"]
                   and bash_env_text == state["bash_env_text"] + block
                   and not [name for name in changed or [] if name.startswith(FAMILIES)],
                   {"path_before": state["path"], "path_after": os.environ.get("PATH"),
                    "bash_env_added_text": bash_env_text[len(state["bash_env_text"]):]
                    if bash_env_text.startswith(state["bash_env_text"]) else None,
                    "changed_variable_names": changed})

    files = tree_hashes(Path.cwd())
    pyenv_hash = file_hash(state["pyenv_version_file"]) if state["pyenv_version_file"] else None
    probe_kept = (Path(".python-version").read_text(encoding="utf-8") == PROBE_VERSION + "\n"
                  if settings["probe"] else not os.path.lexists(".python-version"))
    recorder.check("T11", "The working directory, its .python-version and the pyenv version file are unchanged",
                   files == state["files"] and pyenv_hash == state["pyenv_version_file_sha256"] and probe_kept,
                   {"files": files, "pyenv_version_file": state["pyenv_version_file"],
                    "pyenv_version_file_unchanged": pyenv_hash == state["pyenv_version_file_sha256"],
                    "python_version_file": "the probe, unchanged" if settings["probe"] and probe_kept
                    else "none in this case" if probe_kept else "changed"})

    if state["pre_install"]:
        # Both lists were written by inline steps, directly before install and
        # directly after it. The checkout came later and is not part of them.
        recorded = state["pre_install_home"]
        home_top_level, difference = recorded["home_after_install"], recorded["home_difference"]
        entries_compared = recorded["home_entries_compared"]
        compared = ("every entry below the home directory, listed by inline steps directly before and "
                    "directly after install: kind, and size and modification time of files")
        errors = []
    else:
        before_home = load(STATE / "home-before.json")
        difference = snapshot_difference(before_home["entries"], home_after["entries"])
        entries_compared = len(home_after["entries"])
        compared = "every entry below the home directory: kind, and size and modification time of files"
        errors = before_home["errors"] + home_after["errors"]
    top = {"added": sorted(set(home_top_level) - set(state["home_top_level"])),
           "removed": sorted(set(state["home_top_level"]) - set(home_top_level))}
    clean = (top == {"added": [ROOT_NAME], "removed": []} and not any(difference.values())
             and entries_compared > 0 and not errors)
    recorder.check("T16", "In the home directory install added only the managed environment and changed "
                   "nothing else",
                   clean,
                   {"home": os.environ["HOME"], "compared": compared, "top_level": top,
                    "entries_compared": entries_compared,
                    "difference": {key: value[:40] for key, value in difference.items()},
                    "difference_counts": {key: len(value) for key, value in difference.items()},
                    "unreadable": errors[:10]})

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
    exports = ["\n# python-install-test: observers of the commands that execute calls\n"
               "export PATH=%s:\"$PATH\"\n" % shlex.quote(str(observers))]
    if case != "normal":
        # As on the existing path (.circleci/integration-test.py and
        # record-evidence.py): roles go to a directory of the test, and the
        # unchanged Git observer records the revision of every role archive.
        ROLES.mkdir(exist_ok=False)
        GIT_EVIDENCE.mkdir(exist_ok=False)
        helper = GIT_EVIDENCE / "record-evidence.py"
        shutil.copyfile(source / ".circleci/record-evidence.py", helper)
        real_git = shutil.which("git")
        if not real_git:
            raise ValueError("git is required")
        (GIT_EVIDENCE / "bin").mkdir()
        git_wrapper = GIT_EVIDENCE / "bin" / "git"
        git_wrapper.write_text("#!/bin/sh\nexec %s -I %s git \"$@\"\n" % (
            shlex.quote(sys.executable), shlex.quote(str(helper))), encoding="utf-8")
        git_wrapper.chmod(0o755)
        exports.append("export ORB_EVIDENCE_REAL_GIT=%s\nexport PATH=%s:\"$PATH\"\n"
                       "export ANSIBLE_ROLES_PATH=%s\n" % (
                           shlex.quote(real_git), shlex.quote(str(git_wrapper.parent)),
                           shlex.quote(str(ROLES))))
        real["git"] = real_git
    with open(state["bash_env"], "a", encoding="utf-8") as stream:
        stream.write("".join(exports))
    save(STATE / "after-install.json", {"real": real, "state_record_sha256": file_hash(root / "state.json"),
                                        "distributions": managed["distributions"]})

    evidence = {"context": context(source, lock, image_lock, case),
                "observations": {"direct_command_outputs": versions, "observed_commands": real,
                                 "traced_run_stderr": traced["stderr"] if traced else None}}
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
    if load(STATE / "before.json")["case"] == "negative" and name == "ansible-lint" and not arguments:
        # The negative case, as on the existing path: the step of execute
        # ends with 0 only for the one expected lint failure. Everything else,
        # including a success and a second lint call, ends it with 1.
        marker = STATE / "negative-lint-call"
        try:
            if marker.exists():
                raise ValueError("Extra no-argument linter invocation")
            marker.write_text(str(index), encoding="utf-8")
            expected = load(Path(__file__).resolve().parent.parent / NEGATIVE_EXPECTED)
            classify_negative(result.returncode, result.stdout, result.stderr, expected)
        except (OSError, ValueError, KeyError) as error:
            print("Negative case rejected: " + str(error), file=sys.stderr, flush=True)
            (STATE / ("call-%d.returned" % index)).write_text("1", encoding="utf-8")
            return 1
        (STATE / ("call-%d.returned" % index)).write_text("0", encoding="utf-8")
        return 0
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def role_revision(name):
    # ansible-galaxy writes the installed revision as "version: <value>".
    text = (ROLES / name / "meta/.galaxy_install_info").read_text(encoding="utf-8")
    match = re.search(r"^version: \'?\"?([^\s\'\"]+)\'?\"?\s*$", text, re.M)
    if not match:
        raise ValueError("No version in the install record of role " + name)
    return match.group(1)


def after_execute(source):
    source = Path(source).resolve()
    lock = load(source / "python-install-lock.json")
    image_lock = load(source / "python-image-lock.json")
    state = load(STATE / "before.json")
    case, settings = state["case"], CASES[state["case"]]
    installed = load(STATE / "after-install.json")
    root = Path(state["root"])
    recorder = Recorder()

    calls = [json.loads(line) for line in (STATE / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    for call in calls:
        exit_file = STATE / ("call-%d.exit" % call["index"])
        call["exit_code"] = int(exit_file.read_text(encoding="utf-8")) if exit_file.exists() else None
        returned = STATE / ("call-%d.returned" % call["index"])
        call["returned_to_step"] = int(returned.read_text(encoding="utf-8")) if returned.exists() else call["exit_code"]
        for stream_name in ("stdout", "stderr"):
            path = STATE / ("call-%d.%s" % (call["index"], stream_name))
            call[stream_name] = path.read_bytes().decode("utf-8", "replace") if path.exists() else None
    galaxy = expected_galaxy_calls(case, state["commit"])
    wanted = [["ansible-lint", ["--version"]], ["ansible", ["--version"]],
              ["ansible-community", ["--version"]]]
    wanted += [["ansible-galaxy", arguments] for arguments in galaxy]
    wanted += [["ansible-lint", []]]
    final_code = 2 if settings["lint"] == "violation" else 0
    codes = [0] * (len(wanted) - 1) + [final_code]
    recorder.check("T12", "The real execute steps called ansible-lint --version, ansible --version, "
                   "ansible-community --version%s and ansible-lint without arguments, in this order and "
                   "nothing else; each call ran the command of the managed environment and returned %s"
                   % (", then ansible-galaxy for %s" % " and for ".join(" ".join(a) for a in galaxy)
                      if galaxy else "",
                      "0" if not final_code else "0, except the final lint, which returned %d" % final_code),
                   [[call["name"], call["arguments"]] for call in calls] == wanted
                   and [call["exit_code"] for call in calls] == codes
                   and all(call["returned_to_step"] == 0 for call in calls)
                   and all(call["real"] == str(root / "bin" / call["name"]) for call in calls),
                   {"calls": [{key: call[key] for key in ("index", "name", "arguments", "real", "exit_code",
                                                         "returned_to_step")}
                              for call in calls],
                    "expected_calls": wanted})

    final = calls[-1] if calls else {"stderr": "", "stdout": ""}
    summary = SUMMARY.search(plain(final.get("stderr") or ""))
    numbers = [int(value) for value in summary.groups()] if summary else None
    if settings["lint"] == "exact":
        recorder.check("T13", "The final lint of execute processed the real Ansible file of the fixture with no "
                       "violation: 0 failures, 0 warnings, 1 file processed of the %d files in the working "
                       "directory" % len(state["files"]),
                       numbers == [0, 0, 1, len(state["files"])],
                       {"summary": summary.group(0) if summary else None, "numbers": numbers,
                        "files_in_working_directory": sorted(state["files"])})
    elif settings["lint"] == "passed":
        recorder.check("T13", "The final lint of execute processed real Ansible files of the fixture with no "
                       "violation: 0 failures, 0 warnings, at least 1 file processed",
                       bool(numbers) and numbers[:2] == [0, 0] and numbers[2] >= 1,
                       {"summary": summary.group(0) if summary else None, "numbers": numbers,
                        "files_in_working_directory": sorted(state["files"])})
    else:
        expected = load(source / NEGATIVE_EXPECTED)
        existing = load(source / EXISTING_NEGATIVE_EXPECTED)
        shared = ("exit_code", "violations", "stdout_lines", "stderr_lines")
        try:
            notices = classify_negative(final.get("exit_code"), (final.get("stdout") or "").encode("utf-8"),
                                        (final.get("stderr") or "").encode("utf-8"), expected)
            rejected = None
        except ValueError as error:
            notices, rejected = [], str(error)
        recorder.check("T13", "The final lint of execute failed with exit code %d and reported exactly the "
                       "expected violation of the fixture, and nothing unclassified" % expected["exit_code"],
                       rejected is None,
                       {"real_exit_code": final.get("exit_code"), "violations": expected["violations"],
                        "rejected_because": rejected, "observed_non_lint_notices": notices,
                        "lint_calls": sum(1 for call in calls if call["name"] == "ansible-lint"
                                          and not call["arguments"]),
                        "circleci_failed_step_observed": False,
                        "note": "The observer ended the step with 0 for this exact failure, so the job could "
                                "continue. CircleCI did not run a failing step."})
        # The optional notices are those of the existing path. A notice that
        # names a file of the Python installation names it under the prefix
        # of the verified interpreter here.
        prefix = str(Path(lock["fixed_information"]["interpreter"]["path"]).parent.parent)
        notices_there = [existing["optional_stderr_notice"]] + existing.get("optional_stderr_notices", [])
        translated = sorted((notice["id"], [line.replace("/usr/local/lib/python", prefix + "/lib/python")
                                            for line in notice["lines"]]) for notice in notices_there)
        notices_here = sorted((notice["id"], notice["lines"]) for notice in expected["optional_stderr_notices"])
        recorder.check("T18", "The expected exit code, violation, lines of the finding and optional notices "
                       "are those of the existing path (%s); only the location of the Python installation "
                       "and the wording of the release notice differ" % EXISTING_NEGATIVE_EXPECTED,
                       all(expected[key] == existing[key] for key in shared) and notices_here == translated,
                       {"compared": list(shared) + ["optional notices"],
                        "optional_notice_ids": [identifier for identifier, _ in notices_here],
                        "python_prefix_on_this_path": prefix,
                        "release_notice_command_on_this_path": expected["release_notice_command"]})

    files = tree_hashes(Path.cwd())
    added = sorted(set(files) - set(state["files"]))
    kept = {name: files.get(name) for name in state["files"]}
    try:
        distributions = managed_distributions(root)["distributions"]
    except (OSError, ValueError) as error:
        distributions = {"error": str(error)}
    if settings["marker"]:
        # ansible-lint keeps its cache in .ansible/ of a project that has a marker.
        fixture_kept = kept == state["files"] and all(name.split(os.sep)[0] == ".ansible" for name in added)
        requirement = ("After execute the files of the fixture, the state record and the installed "
                       "distributions are unchanged; lint added files only below .ansible/")
    else:
        fixture_kept = files == state["files"]
        requirement = ("After execute the working directory, the state record and the installed "
                       "distributions are unchanged")
    recorder.check("T14", requirement,
                   fixture_kept and distributions == installed["distributions"]
                   and file_hash(root / "state.json") == installed["state_record_sha256"],
                   {"files": kept, "added_files": len(added), "added_outside_cache":
                    [name for name in added if name.split(os.sep)[0] != ".ansible"],
                    "state_record_sha256": file_hash(root / "state.json")})

    traced = None
    if settings["lint"] != "exact":
        # After T14, so that this extra run cannot hide a change by execute.
        lock_fixed = lock["fixed_information"]
        traced = traced_lint(recorder, lock_fixed, root / "venv", root / "bin", final_code)

    if case != "normal":
        # What execute fetched: the role revisions and the Git archives.
        roles, problems = [], []
        for name, version in expected_roles(case, state["commit"]):
            try:
                found = role_revision(name)
            except (OSError, ValueError) as error:
                found = None
                problems.append(str(error))
            roles.append({"name": name, "expected": version, "installed": found})
        present = sorted(path.name for path in ROLES.iterdir())
        records_file = GIT_EVIDENCE / "repositories.jsonl"
        records = [json.loads(line) for line in records_file.read_text(encoding="utf-8").splitlines()] \
            if records_file.exists() else []
        archives = [record for record in records if record.get("kind") == "installed-role-archive"]
        allowed = [[EPEL_REPOSITORY, EPEL]] if settings["roles"] else []
        installs_self = "SELF" in settings["galaxy"]
        repository_matches = (not installs_self
                              or repository_name(os.environ.get("CIRCLE_REPOSITORY_URL", "")) == REPOSITORY)
        if installs_self:
            allowed.append([REPOSITORY, state["commit"]])
        seen = [[record["repository"], record["commit"]] for record in archives]
        recorder.check("T17", "execute installed exactly the expected roles at the pinned revisions, every "
                       "Git archive came from an expected repository and commit, and the Git observer "
                       "recorded no error" if settings["roles"] else
                       "execute installed no role and fetched no Git archive",
                       not problems and all(role["installed"] == role["expected"] for role in roles)
                       and present == sorted(role["name"] for role in roles)
                       and all(item in allowed for item in seen)
                       and all(item in seen for item in allowed)
                       and not (GIT_EVIDENCE / "errors.jsonl").exists()
                       and repository_matches,
                       {"roles": roles, "roles_directory": str(ROLES), "roles_present": present,
                        "archives": [{key: record.get(key) for key in ("repository", "commit", "tree",
                                                                       "archive_sha256")}
                                     for record in archives],
                        "allowed_archives": allowed, "problems": problems,
                        "git_observer_errors": (GIT_EVIDENCE / "errors.jsonl").exists()})

    archives_file = GIT_EVIDENCE / "repositories.jsonl"
    if archives_file.exists():
        shutil.copyfile(archives_file, EVIDENCE / "git-archives.jsonl")
    code = finish("after-execute", recorder, {
        "context": context(source, lock, image_lock, case),
        "observations": {"execute_outputs": [{key: call[key] for key in ("name", "arguments", "stdout", "stderr")}
                                             for call in calls],
                         "traced_run_stderr": traced["stderr"] if traced else None}})
    phases = {phase: load(EVIDENCE / (phase + ".json")) for phase in ("before", "after-install", "after-execute")}
    combined = {"ticket": 5537, "expanded_by": phases["before"]["context"]["expanded_by"], "case": case,
                "result": "passed" if code == 0 else "failed",
                "commit": os.environ.get("CIRCLE_SHA1"), "job": os.environ.get("CIRCLE_JOB"),
                "job_url": os.environ.get("CIRCLE_BUILD_URL"),
                "checks": {check["id"]: check["passed"] for phase in phases.values() for check in phase["checks"]},
                "phases": phases}
    save(EVIDENCE / "python-install.json", combined)
    print(json.dumps(combined, indent=2), flush=True)
    if code == 0:
        print("All python install checks passed.", flush=True)
    return code


def main():
    usage = ("usage: check-python-install.py before SOURCE_DIRECTORY [CASE [PRE_INSTALL_DIRECTORY]]\n"
             "       check-python-install.py after-install|after-execute|self-test SOURCE_DIRECTORY\n"
             "cases: " + ", ".join(CASES))
    arguments = sys.argv[1:]
    try:
        if len(arguments) >= 3 and arguments[0] == "observe":
            return observe(arguments[1], arguments[2], arguments[3:])
        if len(arguments) in (2, 3, 4) and arguments[0] == "before":
            case = arguments[2] if len(arguments) > 2 else "normal"
            if case in CASES:
                return before(arguments[1], case, arguments[3] if len(arguments) > 3 else None)
        elif len(arguments) == 2 and arguments[0] == "after-install":
            return after_install(arguments[1])
        elif len(arguments) == 2 and arguments[0] == "after-execute":
            return after_execute(arguments[1])
        elif len(arguments) == 2 and arguments[0] == "self-test":
            return self_test(arguments[1])
        print(usage, file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, IndexError) as error:
        print("python install check failed unexpectedly (" + type(error).__name__ + ": " + str(error) + ")",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
