#!/bin/bash
# Command "install": install the pinned Ansible lint tool set.
#
# This file is the whole implementation and holds the fixed information.
# The pack embeds it in the command, so a consumer repository needs no file.
# Contract: docs/python-install-contract.md. Record: python-install-lock.json.
#
# The script only starts the verified Python interpreter by its absolute path.
# It never looks up python on PATH and never reads a version-manager setting.
set -euo pipefail

interpreter=/home/circleci/.pyenv/versions/3.14.10/bin/python3.14

fail() {
  echo "ansible-lint/install failed [$1]: $2" >&2
  echo "ansible-lint/install: no command was published by this invocation." >&2
  exit 1
}

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  fail platform "this command supports only Linux on amd64 (x86_64)."
fi

if [ ! -f "$interpreter" ] || [ ! -x "$interpreter" ]; then
  fail interpreter "the verified Python interpreter was not found at $interpreter. This command supports only verified images. No other Python is used."
fi

# -I: isolated mode. Python ignores PYTHON* variables, the user site
# directory and the current directory. The program is read from this file.
exec "$interpreter" -I - <<'ANSIBLE_LINT_ORB_INSTALL'
"""Implementation of the Orb command "install"."""

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path

# Fixed information of the Orb (contract section 12). The fixed-set identifier
# is the SHA-256 of this object as canonical JSON (sorted keys, no spaces).
# python-install-lock.json records the same object and its basis.
FIXED_INFORMATION = json.loads(r"""
{
  "schema": 1,
  "orb": "orbss/ansible-lint",
  "platform": {"system": "linux", "machine": "x86_64"},
  "interpreter": {"path": "/home/circleci/.pyenv/versions/3.14.10/bin/python3.14", "version": "3.14.10"},
  "index_url": "https://pypi.org/simple",
  "bootstrap_distributions": {"pip": "26.2.2"},
  "distributions": {
    "ansible": "14.5.0",
    "ansible-compat": "26.10.0",
    "ansible-core": "2.21.5",
    "ansible-lint": "26.10.1",
    "attrs": "26.1.0",
    "black": "26.10.1",
    "bracex": "3.2.3",
    "cffi": "2.1.1",
    "click": "8.5.1",
    "cryptography": "50.0.2",
    "distro": "1.9.0",
    "filelock": "4.2.11",
    "jinja2": "3.1.6",
    "jsonschema": "4.26.0",
    "jsonschema-specifications": "2025.9.1",
    "markupsafe": "3.0.4",
    "mypy-extensions": "1.2.0",
    "packaging": "26.3",
    "pathspec": "1.1.1",
    "platformdirs": "4.14.5",
    "pycparser": "3.12",
    "pytokens": "0.4.1",
    "pyyaml": "6.0.3",
    "referencing": "0.37.0",
    "resolvelib": "1.2.1",
    "rpds-py": "2026.9.1",
    "ruamel-yaml": "0.19.1",
    "subprocess-tee": "0.4.2",
    "wcmatch": "12.0.3",
    "yamllint": "1.38.0"
  },
  "exposed_commands": [
    "ansible",
    "ansible-community",
    "ansible-config",
    "ansible-console",
    "ansible-doc",
    "ansible-galaxy",
    "ansible-inventory",
    "ansible-lint",
    "ansible-playbook",
    "ansible-pull",
    "ansible-test",
    "ansible-vault"
  ],
  "direct_commands": ["ansible", "ansible-community", "ansible-galaxy", "ansible-lint"],
  "runtime_clis": ["ansible", "ansible-config", "ansible-doc", "ansible-galaxy", "ansible-playbook"]
}
""")

PREFIX = "ansible-lint/install"
# The managed environment is $HOME/.orbss-ansible-lint (contract section 9.1):
#   venv/           virtual environment that holds the fixed set
#   bin/            only links or wrappers of the exposed commands
#   fixed-set.txt   requirement lines given to pip
#   check/          working directory and HOME of the command check
#   state.json      state record, written last
ROOT_NAME = ".orbss-ansible-lint"
RECORD_NAME = "state.json"
RECORD_LIMIT = 65536
# The state record keeps the name of the Orb. A command cannot read the
# version of its Orb, so the fixed-set identifier tells versions apart.

# Runs inside the virtual environment and reports what is installed there.
QUERY = r"""
import importlib.metadata, json, os, sys
bin_directory = os.path.join(sys.prefix, "bin")
distributions, bin_files = [], set()
for distribution in importlib.metadata.distributions():
    distributions.append([distribution.metadata["Name"], distribution.version])
    for item in distribution.files or []:
        path = os.path.normpath(str(distribution.locate_file(item)))
        if os.path.dirname(path) == bin_directory:
            bin_files.add(os.path.basename(path))
print(json.dumps({
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "version": "%d.%d.%d" % sys.version_info[:3],
    "releaselevel": sys.version_info.releaselevel,
    "distributions": sorted(distributions),
    "bin_files": sorted(bin_files),
}))
"""


class InstallError(Exception):
    """A failure of install. The category names the kind of failure."""

    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


def say(message):
    print(PREFIX + ": " + message, flush=True)


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def fixed_set_identifier(fixed):
    canonical = json.dumps(fixed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def expected_distributions(fixed):
    # The fixed set, plus each bootstrap distribution that it does not pin.
    expected = dict(fixed["bootstrap_distributions"])
    expected.update(fixed["distributions"])
    return expected


def inside(path, directory):
    path, directory = os.path.realpath(path), os.path.realpath(directory)
    return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)


def check_platform(fixed):
    wanted = fixed["platform"]
    if sys.platform != wanted["system"] or platform.machine() != wanted["machine"]:
        raise InstallError("platform", "this command supports only Linux on amd64 (x86_64). "
                           "Found %s on %s." % (sys.platform, platform.machine()))


def check_interpreter(fixed):
    wanted = fixed["interpreter"]
    version = "%d.%d.%d" % sys.version_info[:3]
    if sys.executable != wanted["path"]:
        raise InstallError("interpreter", "the running interpreter is %s, not the verified "
                           "interpreter %s." % (sys.executable, wanted["path"]))
    if version != wanted["version"] or sys.version_info.releaselevel != "final":
        raise InstallError("interpreter", "%s reports Python %s (%s). The verified version is %s "
                           "(final). No other Python is used."
                           % (wanted["path"], version, sys.version_info.releaselevel, wanted["version"]))
    if sys.prefix != sys.base_prefix:
        raise InstallError("interpreter", "the verified interpreter must not run inside a virtual environment.")
    try:
        import ensurepip
        import venv  # noqa: F401
    except ImportError as error:
        raise InstallError("virtual-environment", "the verified interpreter cannot create a virtual "
                           "environment with pip (%s)." % error) from error
    bundled = ensurepip.version()
    if bundled != fixed["bootstrap_distributions"]["pip"]:
        raise InstallError("virtual-environment", "the verified interpreter bundles pip %s. The recorded "
                           "bootstrap pip is %s." % (bundled, fixed["bootstrap_distributions"]["pip"]))


def managed_root():
    home = os.environ.get("HOME", "")
    if not os.path.isabs(home) or not os.path.isdir(home):
        raise InstallError("location", "HOME must name an existing absolute directory. "
                           "The managed environment is created under it.")
    return Path(os.path.normpath(home)) / ROOT_NAME


def check_location(root):
    # The managed environment stays outside the working directory, any
    # checkout made there, and an active virtual environment.
    places = [("the current directory", os.getcwd())]
    working = os.environ.get("CIRCLE_WORKING_DIRECTORY")
    if working:
        places.append(("CIRCLE_WORKING_DIRECTORY", os.path.expanduser(working)))
    active = os.environ.get("VIRTUAL_ENV")
    if active:
        places.append(("the active virtual environment", active))
    for label, place in places:
        if inside(root, place) or inside(place, root):
            raise InstallError("location", "the managed environment %s would overlap %s. Use a working "
                               "directory other than the home directory." % (root, label))


def check_publication_target():
    target = os.environ.get("BASH_ENV", "")
    if not target:
        raise InstallError("publish", "BASH_ENV is not set, so later steps could not receive PATH. "
                           "This command needs CircleCI run steps that use Bash.")
    writable = os.access(target, os.W_OK) if os.path.exists(target) else \
        os.access(os.path.dirname(target) or ".", os.W_OK)
    if not writable:
        raise InstallError("publish", "the file named by BASH_ENV is not writable.")
    return target


def check_existing_commands(fixed, root):
    # Never shadow a tool that the image or the user already provides.
    found = []
    for name in fixed["exposed_commands"]:
        path = shutil.which(name)
        if path is not None and path != str(root / "bin" / name):
            found.append("%s (%s)" % (name, path))
    if found:
        raise InstallError("existing-command", "these commands already resolve on PATH outside the managed "
                           "environment: %s. install does not replace or shadow them, and it does not "
                           "report success through them." % ", ".join(found))


def ignored_pip_settings(root):
    # Names only. Values can hold credentials and are never printed.
    names = sorted(name for name in os.environ if name.startswith("PIP_"))
    home = os.path.expanduser("~")
    candidates = ["/etc/pip.conf"]
    for directory in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(os.pathsep):
        if directory:
            candidates.append(os.path.join(directory, "pip", "pip.conf"))
    candidates.append(os.path.join(home, ".pip", "pip.conf"))
    candidates.append(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"),
                                   "pip", "pip.conf"))
    candidates.append(os.path.join(sys.prefix, "pip.conf"))
    candidates.append(str(root / "venv" / "pip.conf"))
    files = [path for path in dict.fromkeys(candidates) if os.path.exists(path)]
    named = os.environ.get("PIP_CONFIG_FILE")
    if named and named != os.devnull and os.path.exists(named):
        files.append("the file named by PIP_CONFIG_FILE")
    return names, files


def pip_environment():
    # The consumer's pip settings are not applied (contract section 11):
    # no PIP_* variable reaches pip, and PIP_CONFIG_FILE=os.devnull makes pip
    # skip every configuration file. pip also runs with --isolated.
    # Other variables, such as the standard proxy variables, stay as they are.
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith(("PIP_", "_PIP_")) and name != "ENSUREPIP_OPTIONS"}
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def check_environment(root):
    # Environment of the command check. Settings of the consumer do not reach
    # the checked commands: no ANSIBLE_*, PYTHON*, PIP_* or XDG_* variable and
    # no VIRTUAL_ENV. HOME is inside the managed environment, so the check
    # writes nothing elsewhere.
    environment = {name: value for name, value in os.environ.items()
                   if not name.startswith(("ANSIBLE_", "PYTHON", "PIP_", "_PIP_", "XDG_")) and name != "VIRTUAL_ENV"}
    path = [str(root / "bin")] + [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
    environment["PATH"] = os.pathsep.join(path)
    environment["HOME"] = str(root / "check" / "home")
    return environment


def run(command, category, description, environment, directory, capture=False):
    # Without capture the output goes to the step log as it is. With capture
    # it is printed only when the command fails.
    pipe = subprocess.PIPE if capture else None
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, env=environment, cwd=str(directory),
                                stdout=pipe, stderr=pipe, text=True, check=False)
    except OSError as error:
        raise InstallError(category, "%s could not start (%s)." % (description, error)) from error
    if result.returncode != 0:
        if capture:
            sys.stdout.write(result.stdout)
            sys.stdout.flush()
            sys.stderr.write(result.stderr)
            sys.stderr.flush()
        raise InstallError(category, "%s failed with exit status %d." % (description, result.returncode))
    return result.stdout if capture else None


def wrapper_text(root):
    # ansible-lint puts the directory of its interpreter first on PATH for its
    # child processes, and prints a warning when it has to. This wrapper does
    # the same before it starts ansible-lint, for that process only.
    directory = root / "venv" / "bin"
    return ("#!/bin/bash\n"
            "# orbss/ansible-lint: start ansible-lint of the managed environment.\n"
            "export PATH=%s\"${PATH:+:$PATH}\"\n"
            "exec %s \"$@\"\n" % (shlex.quote(str(directory)), shlex.quote(str(directory / "ansible-lint"))))


def create_environment(root, fixed):
    try:
        os.mkdir(root, 0o755)
    except FileExistsError as error:
        raise InstallError("foreign-environment", "%s appeared while install was running." % root) from error
    except OSError as error:
        raise InstallError("permission", "the managed environment %s could not be created (%s). "
                           "install does not use sudo." % (root, error)) from error
    environment = pip_environment()
    venv = root / "venv"
    python = str(venv / "bin" / "python")
    say("creating the virtual environment %s" % venv)
    run([sys.executable, "-I", "-m", "venv", str(venv)], "virtual-environment",
        "creating the virtual environment", environment, root)
    requirements = root / "fixed-set.txt"
    requirements.write_text("".join("%s==%s\n" % item for item in sorted(fixed["distributions"].items())),
                            encoding="ascii")
    say("installing the fixed set (%d distributions) from %s" % (len(fixed["distributions"]), fixed["index_url"]))
    pip = [python, "-I", "-m", "pip", "--isolated", "--no-input", "--disable-pip-version-check", "--no-cache-dir"]
    run(pip + ["install", "--no-deps", "--only-binary", ":all:", "--no-compile", "--progress-bar", "off",
               "--index-url", fixed["index_url"], "--requirement", str(requirements)],
        "download-or-install", "downloading or installing the fixed set", environment, root)
    run(pip + ["check"], "dependency", "the dependency check of the installed set (pip check)", environment, root)
    commands = root / "bin"
    os.mkdir(commands, 0o755)
    for name in fixed["exposed_commands"]:
        if name == "ansible-lint":
            (commands / name).write_text(wrapper_text(root), encoding="ascii")
            os.chmod(commands / name, 0o755)
        else:
            os.symlink(str(venv / "bin" / name), str(commands / name))
    os.makedirs(root / "check" / "home", exist_ok=True)


def read_record(root):
    # Returns the record, or raises when the path is not a managed environment.
    foreign = InstallError("foreign-environment", "%s exists without a valid state record, so a completed "
                           "install did not create it. install does not change or delete it." % root)
    path = root / RECORD_NAME
    try:
        if not stat.S_ISDIR(os.lstat(root).st_mode) or not stat.S_ISREG(os.lstat(path).st_mode):
            raise foreign
        if os.path.getsize(path) > RECORD_LIMIT:
            raise foreign
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise foreign from error
    interpreter = record.get("interpreter") if isinstance(record, dict) else None
    if not (isinstance(record, dict) and isinstance(record.get("orb"), str)
            and isinstance(record.get("fixed_set_sha256"), str) and isinstance(interpreter, dict)
            and isinstance(interpreter.get("path"), str) and isinstance(interpreter.get("version"), str)):
        raise foreign
    return record


def check_record(record, fixed, identifier):
    # Part 1 of the environment check (contract section 9.3).
    if record.get("schema") != fixed["schema"] or record["orb"] != fixed["orb"]:
        raise InstallError("record", "the state record belongs to another Orb or record format.")
    if record["fixed_set_sha256"] != identifier:
        raise InstallError("record", "the state record names another fixed set (%s)." % record["fixed_set_sha256"])
    if record["interpreter"] != fixed["interpreter"]:
        raise InstallError("record", "the state record names another interpreter.")
    if record.get("complete") is not True:
        raise InstallError("record", "the state record has no completion marker.")


def check_installation(root, fixed):
    # Parts 2 and 3 of the environment check (contract section 9.3).
    venv = root / "venv"
    python = venv / "bin" / "python"
    if not os.access(python, os.X_OK):
        raise InstallError("command", "the interpreter of the managed environment is missing.")
    output = run([str(python), "-I", "-c", QUERY], "command", "the interpreter of the managed environment",
                 pip_environment(), root, capture=True)
    try:
        found = json.loads(output)
    except ValueError as error:
        raise InstallError("command", "the interpreter of the managed environment gave no usable answer.") from error
    if (found["prefix"] != str(venv) or found["base_prefix"] != sys.base_prefix
            or found["version"] != fixed["interpreter"]["version"] or found["releaselevel"] != "final"):
        raise InstallError("command", "the managed environment does not use the verified interpreter.")

    expected = expected_distributions(fixed)
    installed = {}
    for name, version in found["distributions"]:
        installed.setdefault(normalize(name), []).append(version)
    problems = []
    for name in sorted(set(expected) | set(installed)):
        if name not in installed:
            problems.append("%s %s is missing" % (name, expected[name]))
        elif name not in expected:
            problems.append("%s %s is extra" % (name, ", ".join(installed[name])))
        elif installed[name] != [expected[name]]:
            problems.append("%s is %s, not %s" % (name, ", ".join(installed[name]), expected[name]))
    if problems:
        raise InstallError("distributions", "the installed distributions differ from the fixed set and the "
                           "bootstrap distributions: %s." % "; ".join(problems))

    names = fixed["exposed_commands"]
    provided = [name for name in found["bin_files"] if name.startswith("ansible")]
    if provided != sorted(names):
        raise InstallError("command", "the managed environment provides the commands %s. The recorded list is %s."
                           % (", ".join(provided) or "none", ", ".join(names)))
    missing = [name for name in fixed["direct_commands"] + fixed["runtime_clis"] if name not in names]
    if missing:
        raise InstallError("command", "required commands are outside the exposed list: %s." % ", ".join(missing))
    commands = root / "bin"
    try:
        entries = sorted(os.listdir(commands))
    except OSError as error:
        raise InstallError("command", "the command directory %s is missing." % commands) from error
    if entries != sorted(names):
        raise InstallError("command", "the command directory %s holds %s. The recorded list is %s."
                           % (commands, ", ".join(entries) or "nothing", ", ".join(names)))
    for name in names:
        entry, target = commands / name, venv / "bin" / name
        if not os.access(target, os.X_OK):
            raise InstallError("command", "%s is missing in the managed environment." % name)
        if name == "ansible-lint":
            correct = (stat.S_ISREG(os.lstat(entry).st_mode) and os.access(entry, os.X_OK)
                       and entry.read_text(encoding="ascii", errors="replace") == wrapper_text(root))
        else:
            correct = os.path.islink(entry) and os.readlink(entry) == str(target)
        if not correct:
            raise InstallError("command", "%s does not start %s of the managed environment." % (entry, name))

    environment = check_environment(root)
    os.makedirs(root / "check" / "home", exist_ok=True)
    for name in names:
        # --offline: ansible-lint would otherwise ask GitHub for its latest release.
        arguments = ["--offline", "--version"] if name == "ansible-lint" else ["--version"]
        run([str(commands / name)] + arguments, "command", "%s %s" % (name, " ".join(arguments)),
            environment, root / "check", capture=True)
    return {normalize(name): version for name, version in found["distributions"]}


def write_record(root, fixed, identifier):
    # Written only after parts 2 and 3 pass. The completion marker is the last
    # key, and the file appears in one step.
    record = {
        "schema": fixed["schema"],
        "orb": fixed["orb"],
        "fixed_set_sha256": identifier,
        "interpreter": fixed["interpreter"],
        "complete": True,
    }
    temporary = root / (RECORD_NAME + ".new")
    with open(temporary, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(record, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, root / RECORD_NAME)


def publish(root, target):
    # Later run steps read BASH_ENV. Only PATH changes.
    commands = str(root / "bin")
    current = [item for item in os.environ.get("PATH", "").split(os.pathsep) if item]
    if current[:1] == [commands]:
        say("PATH of later steps already starts with %s" % commands)
        return
    try:
        with open(target, "a", encoding="utf-8") as stream:
            stream.write("\n# orbss/ansible-lint install: Ansible commands of the managed environment\n"
                         "export PATH=%s:\"$PATH\"\n" % shlex.quote(commands))
    except OSError as error:
        raise InstallError("publish", "PATH could not be passed to later steps (%s)." % error) from error
    say("later run steps get %s at the front of PATH" % commands)


def main():
    fixed = FIXED_INFORMATION
    identifier = fixed_set_identifier(fixed)
    check_platform(fixed)
    check_interpreter(fixed)
    say("Python interpreter: %s (%s)" % (fixed["interpreter"]["path"], fixed["interpreter"]["version"]))
    root = managed_root()
    check_location(root)
    target = check_publication_target()
    check_existing_commands(fixed, root)
    variables, files = ignored_pip_settings(root)
    if variables or files:
        say("ignored pip settings (names only, values are not printed): %s"
            % "; ".join(part for part in (
                "environment variables " + ", ".join(variables) if variables else "",
                "configuration files " + ", ".join(files) if files else "") if part))
    else:
        say("ignored pip settings: none found")

    if os.path.lexists(root):
        record = read_record(root)
        try:
            check_record(record, fixed, identifier)
            versions = check_installation(root, fixed)
        except InstallError as error:
            raise InstallError("inconsistent-environment", "the managed environment %s does not pass the "
                               "environment check. install does not repair or delete it. Reason [%s]: %s"
                               % (root, error.category, error)) from error
        say("managed environment: %s (reused, nothing downloaded or installed)" % root)
    else:
        create_environment(root, fixed)
        versions = check_installation(root, fixed)
        write_record(root, fixed, identifier)
        say("managed environment: %s (new)" % root)
    say("fixed set: sha256:%s" % identifier)
    say("versions: ansible-lint %s, Ansible package (ansible) %s, ansible-core %s"
        % (versions["ansible-lint"], versions["ansible"], versions["ansible-core"]))
    say("exposed commands in %s: %s" % (root / "bin", ", ".join(fixed["exposed_commands"])))
    publish(root, target)


try:
    main()
except InstallError as error:
    print("%s failed [%s]: %s" % (PREFIX, error.category, error), file=sys.stderr, flush=True)
    print(PREFIX + ": no command was published by this invocation.", file=sys.stderr, flush=True)
    sys.exit(1)
ANSIBLE_LINT_ORB_INSTALL
