#!/usr/bin/env python3
"""Record CI-only evidence without changing the Orb's install commands."""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit


EVIDENCE = Path("/tmp/ansible-lint-ci-evidence")


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def append_record(name, value):
    with (EVIDENCE / name).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value) + "\n")


def git_output(*args):
    return subprocess.check_output(
        [os.environ["ORB_EVIDENCE_REAL_GIT"], *args], text=True
    ).strip()


def repository_name(url):
    """Keep a GitHub repository identity, never credentials or URL queries."""
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.split(":", 1)[1]
    parsed = urlsplit(url)
    path = parsed.path.removesuffix(".git")
    if parsed.hostname == "github.com" and re.fullmatch(r"/[\w.-]+/[\w.-]+", path):
        return "https://github.com" + path
    # Local repositories are used by the offline regression test.
    if parsed.scheme == "file" or url.startswith("/"):
        return "local-test-repository"
    raise ValueError("Cannot safely identify this repository")


def revision(ref):
    commit = git_output("rev-parse", "--verify", ref + "^{commit}")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
        raise ValueError("Expected a full Git commit ID")
    return {
        "repository": repository_name(git_output("config", "--get", "remote.origin.url")),
        "commit": commit,
        "tree": git_output("rev-parse", "--verify", commit + "^{tree}"),
    }


def prepare(source):
    source = Path(source).resolve()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    helper = EVIDENCE / "record-evidence.py"
    shutil.copyfile(__file__, helper)
    real_git = shutil.which("git")
    if not real_git:
        raise ValueError("git is required")
    os.environ["ORB_EVIDENCE_REAL_GIT"] = real_git
    commit = git_output("-C", str(source), "rev-parse", "HEAD")
    if commit != os.environ["CIRCLE_SHA1"]:
        raise ValueError("The evidence source checkout must match CIRCLE_SHA1")
    lock = json.loads((source / "image-lock.json").read_text(encoding="utf-8"))
    actual_platform = platform.system().lower() + "/" + {"x86_64": "amd64"}.get(
        platform.machine(), platform.machine()
    )
    write_json("context.json", {
        "observed_at": now(), "commit": commit,
        "job": os.environ["CIRCLE_JOB"], "job_url": os.environ["CIRCLE_BUILD_URL"],
        "configured_image_reference": lock["selected_image"]["reference"],
        "image_reference_evidence": "Confirm the full reference in this job's Spin up environment log.",
        "expected_platform": lock["selected_image"]["platform"],
        "observed_platform": actual_platform,
    })
    if actual_platform != lock["selected_image"]["platform"]:
        raise ValueError("Runtime platform differs from image-lock.json")
    outputs = []
    for executable in ("python3", "ansible-community", "ansible", "ansible-lint"):
        result = subprocess.run([executable, "--version"], capture_output=True, text=True)
        outputs.append({"command": [executable, "--version"], "observed_at": now(),
                        "exit_code": result.returncode, "stdout": result.stdout,
                        "stderr": result.stderr})
        write_json("versions.json", outputs)
        print("$ " + executable + " --version", flush=True)
        print(result.stdout, end="", flush=True)
        print(result.stderr, end="", file=sys.stderr, flush=True)
        if result.returncode:
            raise ValueError("Version command failed: " + executable)
    actual_versions = {"python": platform.python_version()}
    for key, distribution in (("ansible", "ansible"), ("ansible_core", "ansible-core"),
                              ("ansible_lint", "ansible-lint")):
        actual_versions[key] = importlib.metadata.version(distribution)
    write_json("package-versions.json", actual_versions)
    if actual_versions != lock["observed_versions"]:
        raise ValueError("Runtime versions differ from image-lock.json")
    wrapper = EVIDENCE / "bin" / "git"
    wrapper.parent.mkdir(exist_ok=True)
    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                       shlex.quote(str(helper)) + ' git "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    with open(os.environ["BASH_ENV"], "a", encoding="utf-8") as stream:
        stream.write("\nexport ORB_EVIDENCE_REAL_GIT=" + shlex.quote(real_git) + "\n")
        stream.write("export PATH=" + shlex.quote(str(wrapper.parent)) + ':"$PATH"\n')
    print("Prepared image versions and Git archive evidence.", flush=True)


def wrap_git(args):
    real_git = os.environ["ORB_EVIDENCE_REAL_GIT"]
    if not args or args[0] != "archive":
        return subprocess.call([real_git, *args])
    # ansible-core 2.21.5 scm_archive_resource uses exactly this argument shape.
    # Resolve the archive's ref, not HEAD: a role may select another commit/tag.
    refs = [arg for arg in args[1:] if not arg.startswith("--prefix=") and
            not arg.startswith("--output=")]
    outputs = [arg.removeprefix("--output=") for arg in args[1:] if arg.startswith("--output=")]
    if len(refs) != 1 or refs[0].startswith("-") or len(outputs) != 1:
        raise ValueError("Unexpected git archive arguments; cannot certify the installed revision")
    record = revision(refs[0])
    result = subprocess.call([real_git, *args])
    if result:
        append_record("errors.jsonl", {"operation": "git archive", "exit_code": result})
        return result
    if revision(refs[0]) != record:
        raise ValueError("Archive reference changed during execution")
    record.update({"kind": "installed-role-archive", "observed_at": now(),
                   "archive_sha256": hashlib.sha256(Path(outputs[0]).read_bytes()).hexdigest()})
    append_record("repositories.jsonl", record)
    return 0


def worktree():
    record = revision("HEAD")
    record.update({"kind": "integration-test-worktree", "observed_at": now()})
    append_record("repositories.jsonl", record)
    print(json.dumps(record), flush=True)


def report():
    for name in ("context.json", "versions.json", "package-versions.json", "repositories.jsonl", "errors.jsonl"):
        path = EVIDENCE / name
        if path.exists():
            print(name + ":\n" + path.read_text(encoding="utf-8"), flush=True)
    if (EVIDENCE / "errors.jsonl").exists():
        raise ValueError("Evidence collection or Git archive failed; inspect the artifact")
    records = [json.loads(line) for line in (EVIDENCE / "repositories.jsonl").read_text().splitlines()]
    if not any(r["kind"] == "integration-test-worktree" for r in records):
        raise ValueError("Missing test worktree revision")
    if not any(r["kind"] == "installed-role-archive" and
               r["repository"].startswith("https://github.com/ansible-roles-mamono210/") for r in records):
        raise ValueError("Missing external role archive revision")
    print("Repository evidence collected. Integration-test status is reported separately by CircleCI.")


def main():
    try:
        action = sys.argv[1]
        if action == "prepare":
            prepare(sys.argv[2])
        elif action == "git":
            code = wrap_git(sys.argv[2:])
            return code if code >= 0 else 128 - code
        elif action == "worktree":
            worktree()
        elif action == "report":
            report()
        else:
            raise ValueError("Unknown evidence action")
        return 0
    except Exception as error:
        # Do not dump command arguments or remote URLs on error.
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        append_record("errors.jsonl", {"operation": sys.argv[1:2],
                                        "error_type": type(error).__name__, "observed_at": now()})
        print("CI evidence failed (" + type(error).__name__ + "); inspect the job and artifact.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
