#!/usr/bin/env python3
"""CI-only observer: preserve real argv/environment and accept one exact failure."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


def stamp():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def lines(raw):
    text = raw.decode("utf-8", errors="strict")
    # Remove presentation only: SGR colours and OSC-8 hyperlink delimiters.
    # Keep the link's visible text. Unknown escapes/control codes are rejected.
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"\x1b\]8;;[^\x00-\x1f\x7f]*(?:\x1b\\|\x07)", "", text)
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text) or "\x7f" in text:
        raise ValueError("Unrecognized output control code")
    return Counter(line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip())


def assess(code, stdout, stderr, expected):
    if code != expected["exit_code"] or code == 0:
        raise ValueError("Unexpected real linter exit code")
    if lines(stdout) != Counter(expected["stdout_lines"]):
        raise ValueError("Unexpected stdout diagnostic or unclassified line")
    actual = lines(stderr)
    baseline = Counter(expected["stderr_lines"])
    if actual == baseline:
        return []
    # Classify a complete, observed informational notice; do not suppress warnings
    # or discard diagnostics during normalization. Every line/count still matches.
    notice = expected["optional_stderr_notice"]
    if actual == baseline + Counter(notice["lines"]):
        return [{"id": notice["id"], "count": 1, "lines": notice["lines"]}]
    raise ValueError("Unexpected stderr diagnostic or unclassified line")


def prepare(expected_path, evidence):
    evidence = Path(evidence).resolve()
    # Never reuse an earlier invocation ledger.
    evidence.mkdir(parents=True, exist_ok=False)
    real = shutil.which("ansible-lint")
    if not real or not Path(real).is_absolute():
        raise ValueError("Real ansible-lint must be resolved before changing PATH")
    helper = Path(__file__).resolve()
    wrapper = evidence / "bin" / "ansible-lint"
    wrapper.parent.mkdir()
    if Path(real).resolve() == wrapper.resolve():
        raise ValueError("Recursive linter wrapper")
    expected = json.loads(Path(expected_path).read_text(encoding="utf-8"))
    write(evidence / "expected.json", expected)
    context = {"real": real, "cwd": str(Path.cwd().resolve()), "created_at": stamp(),
               "run_id": os.urandom(16).hex(), "commit": os.environ.get("CIRCLE_SHA1"),
               "job_url": os.environ.get("CIRCLE_BUILD_URL"),
               "helper_sha256": hashlib.sha256(helper.read_bytes()).hexdigest()}
    write(evidence / "context.json", context)
    (evidence / "calls.jsonl").write_text("", encoding="utf-8")
    wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                       shlex.quote(str(helper)) + " wrap " + shlex.quote(str(evidence)) +
                       ' "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    with open(os.environ["BASH_ENV"], "a", encoding="utf-8") as stream:
        stream.write("\nexport PATH=" + shlex.quote(str(wrapper.parent)) + ':"$PATH"\n')


def wrap(evidence, args):
    evidence = Path(evidence)
    context = json.loads((evidence / "context.json").read_text())
    calls = evidence / "calls.jsonl"
    previous = [json.loads(x) for x in calls.read_text().splitlines()]
    index = len(previous)
    event = {"index": index, "run_id": context["run_id"], "args": args,
             "cwd": str(Path.cwd().resolve()), "started_at": stamp()}
    # A started-but-unfinished record cannot pass verification.
    with calls.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event) + "\n")
    if event["cwd"] != context["cwd"] or args not in ([], ["--version"]):
        raise ValueError("Unexpected linter invocation")
    if not args and any(x["args"] == [] for x in previous):
        raise ValueError("Extra no-argument linter invocation")
    real = Path(context["real"])
    if real.resolve() == (evidence / "bin" / "ansible-lint").resolve():
        raise ValueError("Recursive linter wrapper")
    # No options or environment overrides: inherit the caller's environment.
    result = subprocess.run([str(real), *args], capture_output=True)
    for name, data in (("stdout", result.stdout), ("stderr", result.stderr)):
        (evidence / f"{index}.{name}").write_bytes(data)
        getattr(sys, name).buffer.write(data)
        getattr(sys, name).flush()
    event.update({"finished_at": stamp(), "exit_code": result.returncode})
    write(evidence / f"{index}.result.json", event)
    if args == ["--version"]:
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    expected = json.loads((evidence / "expected.json").read_text())
    assess(result.returncode, result.stdout, result.stderr, expected)
    return 0


def verify(evidence):
    evidence = Path(evidence)
    context = json.loads((evidence / "context.json").read_text())
    calls = [json.loads(x) for x in (evidence / "calls.jsonl").read_text().splitlines()]
    if [x["args"] for x in calls] != [["--version"], []]:
        raise ValueError("Expected one version call and exactly one no-argument lint call")
    expected = json.loads((evidence / "expected.json").read_text())
    for index, start in enumerate(calls):
        result = json.loads((evidence / f"{index}.result.json").read_text())
        if any(result.get(k) != v for k, v in start.items()):
            raise ValueError("Invocation record changed")
        if result["run_id"] != context["run_id"] or result["cwd"] != context["cwd"]:
            raise ValueError("Wrong job or working directory")
        if not result.get("finished_at"):
            raise ValueError("Missing completed invocation")
        if index == 0 and result["exit_code"] != 0:
            raise ValueError("Version invocation failed")
    notices = assess(result["exit_code"], (evidence / "1.stdout").read_bytes(),
                     (evidence / "1.stderr").read_bytes(), expected)
    report = {"result": "passed", "real_exit_code": result["exit_code"],
              "violations": expected["violations"], "lint_calls": 1,
              "commit": context["commit"], "job_url": context["job_url"],
              "observed_non_lint_notices": notices,
              "circleci_failed_step_observed": False}
    write(evidence / "verification.json", report)
    print(json.dumps(report))


def main():
    try:
        if sys.argv[1] == "prepare":
            prepare(sys.argv[2], sys.argv[3])
        elif sys.argv[1] == "wrap":
            return wrap(sys.argv[2], sys.argv[3:])
        elif sys.argv[1] == "verify":
            verify(sys.argv[2])
        else:
            raise ValueError("Unknown action")
        return 0
    except (OSError, ValueError, KeyError, IndexError) as error:
        print("Negative-test rejected: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
