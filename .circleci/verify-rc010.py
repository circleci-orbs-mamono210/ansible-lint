"""Require one executed, successful RC010 in the orb-tools review JUnit report."""

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(directory):
    matches = []
    for report in sorted(directory.glob("*.xml")):
        for case in ET.parse(report).iter("testcase"):
            if case.get("name", "").startswith("RC010:"):
                matches.append((report, case))
    if len(matches) != 1:
        sys.exit(f"Expected one RC010 test result, found {len(matches)} in {directory}")

    report, case = matches[0]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if commit != os.environ["CIRCLE_SHA1"]:
        sys.exit("Review checkout does not match the candidate commit")
    result = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), "passed")
    evidence = {
        "commit": commit,
        "pipeline_id": os.environ["REVIEW_PIPELINE_ID"],
        "job_url": os.environ["CIRCLE_BUILD_URL"],
        "rule_source": "https://github.com/CircleCI-Public/orb-tools-orb/blob/"
                       "78fe512bb2b1355667ef0f53bb8e7518f519332c/src/scripts/review.bats#L198-L229",
        "junit": report.name,
        "test": case.get("name"),
        "result": result,
    }
    (directory / "rc010.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"RC010 {result} for {commit} ({report.name})")
    if result != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
