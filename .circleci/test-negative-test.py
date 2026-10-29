#!/usr/bin/env python3
"""Run the real observer implementation in child processes, substituting only the linter."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HELPER = Path(__file__).with_name("negative-test.py").resolve()
EXPECTED = HELPER.parent.parent / "tests/negative-expected.json"


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "evidence"
        self.expected = json.loads(EXPECTED.read_text())
        self.config = self.root / "stub.json"
        self.behavior = {"code": self.expected["exit_code"],
                         "stdout": "\n".join(self.expected["stdout_lines"]) + "\n",
                         "stderr": "\n".join(self.expected["stderr_lines"]) + "\n",
                         "version_code": 0}
        stub = self.root / "ansible-lint"
        stub.write_text("#!" + sys.executable + "\nimport json,sys\n"
                        f"c=json.load(open({str(self.config)!r}))\n"
                        "if sys.argv[1:]==['--version']:\n"
                        " print('stub version'); sys.exit(c['version_code'])\n"
                        "print(c['stdout'],end=''); print(c['stderr'],end='',file=sys.stderr)\n"
                        "sys.exit(c['code'])\n")
        stub.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"],
                        BASH_ENV=str(self.root / "bash-env"))
        self.config.write_text(json.dumps(self.behavior))
        self.run_helper("prepare", str(EXPECTED), str(self.evidence), ok=True)

    def run_helper(self, *args, ok=None):
        result = subprocess.run([sys.executable, str(HELPER), *args], env=self.env,
                                cwd=self.root, capture_output=True, text=True)
        if ok is True:
            self.assertEqual(result.returncode, 0, result.stderr)
        elif ok is False:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def invoke(self, ok=True):
        self.config.write_text(json.dumps(self.behavior))
        self.run_helper("wrap", str(self.evidence), "--version", ok=True)
        self.run_helper("wrap", str(self.evidence), ok=ok)

    def test_exact_control_passes(self):
        self.invoke()
        self.run_helper("verify", str(self.evidence), ok=True)

    def test_unexpected_success_rejected(self):
        self.behavior["code"] = 0
        self.invoke(ok=False)
        self.run_helper("verify", str(self.evidence), ok=False)

    def test_other_exit_code_rejected(self):
        self.behavior["code"] = 3
        self.invoke(ok=False)
        self.run_helper("verify", str(self.evidence), ok=False)

    def test_wrong_rule_rejected(self):
        self.behavior["stdout"] = self.behavior["stdout"].replace("name[missing]", "syntax-check[specific]")
        self.invoke(ok=False)
        self.run_helper("verify", str(self.evidence), ok=False)

    def test_wrong_file_rejected(self):
        self.behavior["stdout"] = self.behavior["stdout"].replace("playbook.yml", "other.yml")
        self.invoke(ok=False)

    def test_extra_rule_rejected(self):
        self.behavior["stdout"] += "fqcn[action-core]: Use FQCN\nother.yml:1\n"
        self.invoke(ok=False)

    def test_mixed_dependency_error_rejected(self):
        self.behavior["stderr"] += "ERROR: Failed to download role\n"
        self.invoke(ok=False)

    def test_unknown_line_rejected(self):
        self.behavior["stderr"] += "unclassified diagnostic\n"
        self.invoke(ok=False)

    def add_known_notice(self):
        self.behavior["stderr"] += "\n".join(self.expected["optional_stderr_notice"]["lines"]) + "\n"

    def test_exact_schema_304_cleanup_notice_is_classified(self):
        self.add_known_notice()
        self.invoke()
        self.run_helper("verify", str(self.evidence), ok=True)
        report = json.loads((self.evidence / "verification.json").read_text())
        self.assertEqual(report["observed_non_lint_notices"], [{
            "id": self.expected["optional_stderr_notice"]["id"], "count": 1,
            "lines": self.expected["optional_stderr_notice"]["lines"]}])

    def test_other_http_status_is_rejected(self):
        self.add_known_notice()
        self.behavior["stderr"] = self.behavior["stderr"].replace("304: 'Not Modified'", "403: 'Forbidden'")
        self.invoke(ok=False)

    def test_partial_cleanup_notice_is_rejected(self):
        self.behavior["stderr"] += self.expected["optional_stderr_notice"]["lines"][0] + "\n"
        self.invoke(ok=False)

    def test_duplicate_cleanup_notice_is_rejected(self):
        self.add_known_notice()
        self.add_known_notice()
        self.invoke(ok=False)

    def test_cleanup_notice_and_dependency_error_is_rejected(self):
        self.add_known_notice()
        self.behavior["stderr"] += "ERROR: Failed to download role\n"
        self.invoke(ok=False)

    def test_other_resource_warning_is_rejected(self):
        self.add_known_notice()
        self.behavior["stderr"] = self.behavior["stderr"].replace("HTTPError 304: 'Not Modified'", "unclosed file")
        self.invoke(ok=False)

    def test_duplicate_violation_rejected(self):
        self.behavior["stdout"] *= 2
        self.invoke(ok=False)

    def test_missing_ledger_rejected(self):
        self.invoke()
        (self.evidence / "calls.jsonl").unlink()
        self.run_helper("verify", str(self.evidence), ok=False)

    def test_missing_result_rejected(self):
        self.invoke()
        (self.evidence / "1.result.json").unlink()
        self.run_helper("verify", str(self.evidence), ok=False)

    def test_never_invoked_rejected(self):
        self.run_helper("verify", str(self.evidence), ok=False)

    def test_extra_call_rejected(self):
        self.invoke()
        self.run_helper("wrap", str(self.evidence), ok=False)
        self.run_helper("verify", str(self.evidence), ok=False)

    def test_extra_arguments_rejected(self):
        self.run_helper("wrap", str(self.evidence), "--offline", ok=False)

    def test_version_failure_propagated(self):
        self.behavior["version_code"] = 17
        self.config.write_text(json.dumps(self.behavior))
        result = self.run_helper("wrap", str(self.evidence), "--version")
        self.assertEqual(result.returncode, 17)

    def test_colour_and_display_order_allowed(self):
        self.behavior["stdout"] = "\x1b[31m" + self.behavior["stdout"] + "\x1b[0m"
        self.behavior["stderr"] = "\n".join(reversed(self.behavior["stderr"].splitlines()))
        self.invoke()
        self.run_helper("verify", str(self.evidence), ok=True)

    def test_unknown_terminal_control_rejected(self):
        self.behavior["stdout"] += "\x1b[2J"
        self.invoke(ok=False)

    def test_stale_record_rejected(self):
        self.invoke()
        path = self.evidence / "1.result.json"
        data = json.loads(path.read_text())
        data["run_id"] = "earlier-job"
        path.write_text(json.dumps(data))
        self.run_helper("verify", str(self.evidence), ok=False)

    def test_existing_evidence_cannot_be_reused(self):
        self.run_helper("prepare", str(EXPECTED), str(self.evidence), ok=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
