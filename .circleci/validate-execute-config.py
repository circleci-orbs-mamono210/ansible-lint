"""Compile the six public execute calls against one verified workflow archive."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


ENDPOINT = "https://circleci.com/api/v3/configs/compile"
SUMMARY = "execute-config-summary.json"
ROLE = "molecule_role_test"
PLAYBOOK = "molecule_playbook_test"
OLD_ROLE = "molecule-role-test"
OLD_PLAYBOOK = "molecule-playbook-test"
# Supplied keys (all true), followed by the only acceptable rejected key.
CASES = {
    "role": ((ROLE,), None),
    "playbook": ((PLAYBOOK,), None),
    "both": ((ROLE, PLAYBOOK), None),
    "omitted": ((), None),
    "legacy-role": ((OLD_ROLE,), OLD_ROLE),
    "legacy-playbook": ((OLD_PLAYBOOK,), OLD_PLAYBOOK),
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def candidate_pack(workspace, commit, pipeline):
    record_path = workspace / "baseline-publication.json"
    record = json.loads(record_path.read_bytes())
    if (record["commit"], record["pipeline_id"], record["purpose"], record["result"]) != (
        commit, pipeline, "publication", "passed"
    ):
        raise ValueError("pack comparison did not pass for this commit and pipeline")

    archive = workspace / "orb_source.tar.gz"
    archive_hash = sha256(archive.read_bytes())
    with tarfile.open(archive, "r:gz") as tar:
        members = [member for member in tar if member.name == "./orb.yml"]
        if len(members) != 1 or not members[0].isfile():
            raise ValueError("expected exactly one regular ./orb.yml in orb_source.tar.gz")
        packed_yaml = tar.extractfile(members[0]).read()
    member_hash = sha256(packed_yaml)
    if (archive_hash, "./orb.yml", member_hash) != (
        record["archive_sha256"], record["candidate"]["member"], record["candidate"]["sha256"]
    ):
        raise ValueError("archive or member does not match the pack comparison")
    provenance = {
        "job_url": record["job_url"], "archive": record["archive"],
        "archive_sha256": archive_hash, "member": "./orb.yml", "member_sha256": member_hash,
        "source": "test-deploy / orb-tools/pack, attached workflow workspace",
        "insertion": "parse the verified member once and inline it as orbs.ansible-lint",
        "comparison_file": record_path.name, "comparison_sha256": sha256(record_path.read_bytes()),
    }
    return yaml.safe_load(packed_yaml), provenance


def consumer_config(orb, keys):
    command = "ansible-lint/execute"
    step = {command: dict.fromkeys(keys, True)} if keys else command
    return {
        "version": 2.1, "orbs": {"ansible-lint": orb},
        "jobs": {"consumer": {"executor": "ansible-lint/default", "steps": ["checkout", step]}},
        "workflows": {"verify": {"jobs": ["consumer"]}},
    }


def workflow_calls_consumer(config):
    return config.get("workflows", {}).get("verify", {}).get("jobs") == ["consumer"]


def compile_case(config, keys, rejected_key, compiled_path):
    # Only the fixture is sent. urllib does not load CircleCI CLI credentials.
    payload = {"data": {"attributes": {"config": config}}}
    request = Request(ENDPOINT, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=45) as response:
            status = response.status
            data = json.load(response)
        attributes = data["data"]["attributes"]
        outcome = attributes["outcome"]
        messages = [item["title"] for item in data.get("meta", {}).get("messages", [])]
        if attributes.get("phase") != "ended" or not all(isinstance(m, str) for m in messages):
            raise ValueError("incomplete compiler response")
        if outcome == "succeeded" and not messages:
            compiled = attributes["compiled_config"]
            compiled_path.write_text(compiled, encoding="utf-8")
            expanded = yaml.safe_load(compiled)
            if not workflow_calls_consumer(expanded):
                return {"http_status": status, "outcome": "unreferenced-job"}
            steps = expanded["jobs"]["consumer"]["steps"]
            runs = [s["run"] for s in steps if isinstance(s, dict) and isinstance(s.get("run"), dict)]
            if not runs:
                return {"http_status": status, "outcome": "command-not-expanded"}
            if not rejected_key:
                expected = {f"PARAM_{key.upper()}": key in keys for key in (ROLE, PLAYBOOK)}
                if not any(all(run.get("environment", {}).get(k) is v for k, v in expected.items())
                           for run in runs):
                    return {"http_status": status, "outcome": "unexpected-compiled-flags"}
            return {"http_status": status, "outcome": "accepted", "compiled": compiled_path.name}
        if outcome != "failed" or not messages:
            raise ValueError("unexpected compiler response")
    except HTTPError as error:
        reason = "authentication-error" if error.code in (401, 403) else "http-error"
        return {"http_status": error.code, "outcome": reason}
    except (URLError, OSError, HTTPException) as error:
        return {"outcome": "transport-error", "error_type": type(error).__name__}
    except (KeyError, IndexError, ValueError, TypeError, AttributeError, yaml.YAMLError):
        return {"outcome": "invalid-compiler-response"}

    # The compiler returns one diagnostic, including the complete call chain.
    expected = ["Error calling workflow: 'verify'", "Error calling job: 'consumer'",
                "Error calling command: 'ansible-lint/execute'", f"Unexpected argument(s): {rejected_key}"]
    if any(re.search(r"\b(unauthorized|unauthenticated|forbidden|authentication required|not authorized)\b",
                     message, re.IGNORECASE) for message in messages):
        return {"http_status": status, "outcome": "authentication-error"}
    if rejected_key and len(messages) == 1 and messages[0].splitlines() == expected:
        result = "undefined-key"
    else:
        result = "other-config-error"
    return {"http_status": status, "outcome": result, "diagnostics": messages}


def passed(results):
    return results.keys() == CASES.keys() and all(
        results[name]["outcome"] == ("undefined-key" if rejected else "accepted")
        for name, (_, rejected) in CASES.items()
    )


def check(workspace, evidence, commit, pipeline, job_url):
    evidence.mkdir(parents=True, exist_ok=True)
    results = {name: {"outcome": "not-run", "expected_rejected_key": key}
               for name, (_, key) in CASES.items()}
    summary = {"commit": commit, "pipeline_id": pipeline, "job_url": job_url,
               "processor": ENDPOINT, "authentication": "anonymous HTTPS",
               "operation": "configuration compilation", "cases": results}
    try:
        config = yaml.safe_load(Path(".circleci/test-deploy.yml").read_text())
        jobs = config["workflows"]["test-deploy"]["jobs"]
        for name in ("validate-execute-config", "verify-execute-config-evidence"):
            invocations = [j[name] for j in jobs if isinstance(j, dict) and name in j]
            if len(invocations) != 1 or "context" in invocations[0]:
                raise ValueError(f"expected one invocation of {name} without a context")
        summary["context"] = None
        orb, summary["pack"] = candidate_pack(workspace, commit, pipeline)
        for name, (keys, rejected) in CASES.items():
            document = consumer_config(orb, keys)
            fixture = evidence / f"{name}.yml"
            fixture.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
            encoded = fixture.read_bytes()
            results[name].update(input=fixture.name, input_sha256=sha256(encoded))
            if workflow_calls_consumer(document):
                observation = compile_case(encoded.decode(), keys, rejected, evidence / f"{name}.compiled.yml")
                results[name].update(observation)
            else:
                results[name]["outcome"] = "unreferenced-job"
            print(f"{name}: {results[name]['outcome']}", flush=True)
    except (OSError, ValueError, KeyError, tarfile.TarError, yaml.YAMLError) as error:
        summary["setup_error"] = str(error)
    finally:
        summary["result"] = "passed" if passed(results) else "failed"
        (evidence / SUMMARY).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if summary["result"] != "passed":
        raise SystemExit(summary.get("setup_error", f"see {SUMMARY} for the six outcomes"))


def confirm(workspace, commit, pipeline, job_url):
    summary = json.loads((workspace / SUMMARY).read_bytes())
    if (summary["commit"], summary["pipeline_id"], summary["result"]) != (commit, pipeline, "passed"):
        raise ValueError("expected a successful validation summary for this commit and pipeline")
    if not passed(summary["cases"]):
        raise ValueError("expected all six compiler outcomes in the upstream summary")
    print(f"Validation job {summary['job_url']} passed all six cases for {commit}.")
    print(f"Downstream job {job_url} confirmed that result in pipeline {pipeline}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    run = modes.add_parser("check")
    run.add_argument("workspace", type=Path)
    run.add_argument("evidence", type=Path)
    modes.add_parser("confirm").add_argument("workspace", type=Path)
    args = parser.parse_args()
    commit = os.environ["CIRCLE_SHA1"]
    pipeline = os.environ["CONFIG_PIPELINE_ID"]
    job_url = os.environ["CIRCLE_BUILD_URL"]
    if not all((commit, pipeline, job_url)) or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip() != commit:
        sys.exit("expected the candidate checkout and its CircleCI job and pipeline identity")
    if args.mode == "check":
        check(args.workspace, args.evidence, commit, pipeline, job_url)
    else:
        confirm(args.workspace, commit, pipeline, job_url)


if __name__ == "__main__":
    main()
