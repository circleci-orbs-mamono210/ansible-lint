#!/usr/bin/env python3
"""Prepare local fixtures and verify dependency installation without changing src/."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


EVIDENCE = Path("/tmp/ansible-lint-integration-evidence")
EPEL = "747af654d2a2e05c1cfabce9c0b79b2a1eae3650"
REPOSITORY = "https://github.com/circleci-orbs-mamono210/ansible-lint"


def save(name, data):
    (EVIDENCE / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def setup(source, case):
    source = Path(source).resolve()
    case_fixtures = {"normal": "tests/fixtures/normal", "negative": "tests/fixtures/negative",
                     "role": "test_resources", "playbook": "tests/fixtures/playbook",
                     "resource-class": "tests/fixtures/playbook", "custom-image": "tests/fixtures/playbook"}
    fixture = source / case_fixtures[case]
    if any(Path.cwd().iterdir()):
        raise ValueError("Fixture working directory must be empty")
    EVIDENCE.mkdir(exist_ok=False)
    if os.environ.get("CIRCLE_TOKEN"):
        raise ValueError("Publishing token must not be injected into integration jobs")
    lock = json.loads((source / "image-lock.json").read_text())
    comparison = json.loads((source / "tests/image-comparison.json").read_text())
    selected, baseline = lock["selected_image"], lock["comparison_image"]
    if not (selected["manifest_digest"] == baseline["manifest_digest"] ==
            comparison["selected_manifest_digest"] == comparison["comparison_manifest_digest"]
            and selected["platform"] == baseline["platform"] == comparison["platform"]
            and baseline["published_source_sha256"] == comparison["public_0_0_3_source_sha256"]):
        raise ValueError("Image comparison decision must be reviewed after an image change")
    save("image-comparison.json", comparison)
    files = {}
    for path in sorted(fixture.rglob("*")):
        if path.is_file() and ".ansible" not in path.parts and "__pycache__" not in path.parts:
            relative = path.relative_to(fixture)
            target = Path.cwd() / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            files[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if case in ("normal", "negative") and set(files) != {"playbook.yml"}:
        raise ValueError("Normal/negative fixtures must contain exactly one real playbook")
    if case in ("playbook", "resource-class", "custom-image"):
        from ansiblelint.file_utils import find_project_root
        project, _ = find_project_root([])
        if project.resolve() != Path.cwd().resolve():
            raise ValueError("Playbook fixture must be its own lint project root")
    # The role fixture is checked out from this repository, never an external test repo.
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if commit != os.environ["CIRCLE_SHA1"]:
        raise ValueError("Fixture source differs from CIRCLE_SHA1")
    calls, installs = [], []
    if case == "role":
        url = os.environ["CIRCLE_REPOSITORY_URL"]
        if url.startswith("git@github.com:"):
            url = "https://github.com/" + url.split(":", 1)[1]
        if url.removesuffix(".git") != REPOSITORY:
            raise ValueError("Unexpected self-repository URL")
        calls = [["install", "git+" + os.environ["CIRCLE_REPOSITORY_URL"] + "," + commit],
                 ["install", "-r", "molecule/default/requirements.yml"]]
        installs = [{"name": "ansible-lint", "version": commit}, {"name": "mamono210.epel", "version": EPEL}]
    elif case in ("playbook", "resource-class", "custom-image"):
        calls = [["install", "-r", "roles/requirements.yml"],
                 ["install", "-r", "molecule/default/requirements.yml"]]
        installs = [{"name": "fixture_playbook_epel", "version": EPEL},
                    {"name": "fixture_molecule_epel", "version": EPEL}]
    roles = Path("/tmp/ansible-lint-installed-roles")
    roles.mkdir(exist_ok=False)
    save("context.json", {"case": case, "commit": commit, "job_url": os.environ["CIRCLE_BUILD_URL"],
                          "fixture_directory": str(fixture.relative_to(source)), "fixture_sha256": files,
                          "working_directory": str(Path.cwd()), "expected_calls": calls,
                          "expected_installs": installs, "roles_path": str(roles),
                          "publishing_token_present": False})
    (EVIDENCE / "galaxy.jsonl").write_text("")
    real = shutil.which("ansible-galaxy")
    if not real:
        raise ValueError("ansible-galaxy is required")
    bins = EVIDENCE / "bin"
    bins.mkdir()
    wrapper = bins / "ansible-galaxy"
    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                       shlex.quote(str(Path(__file__).resolve())) + " galaxy " +
                       shlex.quote(real) + ' "$@"\n')
    wrapper.chmod(0o755)
    if case != "negative":
        real_lint = shutil.which("ansible-lint")
        if not real_lint:
            raise ValueError("ansible-lint is required")
        lint_wrapper = bins / "ansible-lint"
        lint_wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                                shlex.quote(str(Path(__file__).resolve())) + " lint " +
                                shlex.quote(real_lint) + ' "$@"\n')
        lint_wrapper.chmod(0o755)
        (EVIDENCE / "lint.jsonl").write_text("")
    with open(os.environ["BASH_ENV"], "a", encoding="utf-8") as stream:
        stream.write("\nexport PATH=" + shlex.quote(str(bins)) + ':"$PATH"\n')
        stream.write("export ANSIBLE_ROLES_PATH=" + shlex.quote(str(roles)) + "\n")
    print(json.dumps({"case": case, "fixture_sha256": files, "expected_calls": calls}))


def galaxy(real, args):
    # Observe exactly the public command's requests; keep argv, environment and status.
    code = subprocess.call([real, *args])
    with (EVIDENCE / "galaxy.jsonl").open("a") as stream:
        stream.write(json.dumps({"args": args, "exit_code": code,
                                 "lint_started": (EVIDENCE / "lint-started").exists()}) + "\n")
    return code if code >= 0 else 128 - code


def lint(real, args):
    if args not in ([], ["--version"]):
        raise ValueError("Public execute must call the linter without arguments")
    if not args:
        if (EVIDENCE / "lint-started").exists():
            raise ValueError("Extra no-argument linter invocation")
        (EVIDENCE / "lint-started").touch(exist_ok=False)
    # Positive tests observe and propagate the actual status unchanged.
    result = subprocess.run([real, *args], capture_output=True)
    name = "version" if args else "lint"
    for stream, data in (("stdout", result.stdout), ("stderr", result.stderr)):
        (EVIDENCE / f"{name}.{stream}").write_bytes(data)
        getattr(sys, stream).buffer.write(data)
        getattr(sys, stream).flush()
    with (EVIDENCE / "lint.jsonl").open("a") as stream:
        stream.write(json.dumps({"args": args, "exit_code": result.returncode}) + "\n")
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


def verify():
    import yaml
    context = json.loads((EVIDENCE / "context.json").read_text())
    all_calls = [json.loads(line) for line in (EVIDENCE / "galaxy.jsonl").read_text().splitlines()]
    # ansible-lint also queries installed collections; this is not an install.
    calls = [c for c in all_calls if c["args"] != ["collection", "list", "--format=json"]]
    expected = context["expected_calls"]
    if [c["args"] for c in calls[:len(expected)]] != expected or any(c["exit_code"] for c in all_calls):
        raise ValueError("Missing or failed public execute dependency-install request")
    if any(c["lint_started"] for c in calls[:len(expected)]):
        raise ValueError("Required installs must occur before the final linter invocation")
    if not expected and calls:
        raise ValueError("Normal/negative execute unexpectedly installed dependencies")
    for relative, digest in context["fixture_sha256"].items():
        if hashlib.sha256(Path(relative).read_bytes()).hexdigest() != digest:
            raise ValueError("Fixture changed during execute")
    installed = []
    for wanted in context["expected_installs"]:
        info = Path(context["roles_path"]) / wanted["name"] / "meta/.galaxy_install_info"
        data = yaml.safe_load(info.read_text())
        if data["version"] != wanted["version"]:
            raise ValueError("Installed role revision mismatch")
        installed.append(wanted)
    records = [json.loads(x) for x in Path("/tmp/ansible-lint-ci-evidence/repositories.jsonl").read_text().splitlines()]
    archives = [r for r in records if r["kind"] == "installed-role-archive"]
    if expected:
        for r in archives:
            allowed = ((r["repository"] == "https://github.com/ansible-roles-mamono210/epel" and r["commit"] == EPEL)
                       or (context["case"] == "role" and r["repository"] == REPOSITORY and r["commit"] == context["commit"]))
            if not allowed:
                raise ValueError("Unpinned or unexpected dependency archive")
        if not any(r["commit"] == EPEL for r in archives):
            raise ValueError("Missing pinned external role archive")
        if context["case"] == "role" and not any(r["commit"] == context["commit"] for r in archives):
            raise ValueError("Missing self-repository archive")
    elif archives:
        raise ValueError("Unexpected dependency archive")
    if context["case"] != "negative":
        lint_calls = [json.loads(x) for x in (EVIDENCE / "lint.jsonl").read_text().splitlines()]
        if [x["args"] for x in lint_calls] != [["--version"], []] or any(x["exit_code"] for x in lint_calls):
            raise ValueError("Expected one successful version and one successful no-argument lint call")
        output = (EVIDENCE / "lint.stderr").read_text()
        output = re.sub(r"\x1b\[[0-9;]*m", "", output)
        output = re.sub(r"\x1b\]8;;[^\x00-\x1f\x7f]*(?:\x1b\\|\x07)", "", output)
        summary = re.search(r"Passed: 0 failure\(s\), 0 warning\(s\) in ([1-9][0-9]*) files processed of ([1-9][0-9]*) encountered\.", output)
        if not summary:
            raise ValueError("No evidence that real Ansible files were linted successfully")
        if context["case"] == "normal" and summary.groups() != ("1", "1"):
            raise ValueError("Normal test must inspect exactly its one playbook")
    report = {"result": "passed", "case": context["case"], "commit": context["commit"],
              "job_url": context["job_url"], "installed_roles": installed,
              "fixture_sha256": context["fixture_sha256"],
              "execute_success_evidence": "Previous public ansible-lint/execute steps in this same job"}
    save("verification.json", report)
    print(json.dumps(report))


def main():
    try:
        if sys.argv[1] == "setup":
            setup(sys.argv[2], sys.argv[3])
        elif sys.argv[1] == "galaxy":
            return galaxy(sys.argv[2], sys.argv[3:])
        elif sys.argv[1] == "lint":
            return lint(sys.argv[2], sys.argv[3:])
        elif sys.argv[1] == "verify":
            verify()
        else:
            raise ValueError("Unknown action")
        return 0
    except (OSError, ValueError, KeyError, IndexError) as error:
        print("Integration evidence failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
