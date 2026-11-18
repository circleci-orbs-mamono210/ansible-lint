#!/bin/bash
# Read the actual orb-tools 12.5.0 workspace archive; never repack or modify it.
# #5538: executors.default and commands.execute of the packed Orb equal the
# published 1.0.0 baseline (docs/python-install-contract.md, section 5).
# The comparison itself is compare-baseline.sh, the file that
# test-compare-baseline.sh tests in the step before this one.
set -euo pipefail

archive=${1:?archive path required}
purpose=${2:?injection or publication required}
case "$purpose" in injection|publication) ;; *) exit 1 ;; esac
record=tests/baseline/orbss-ansible-lint-1.0.0.json
test "$(git rev-parse HEAD)" = "$CIRCLE_SHA1"
# The baseline and the comparison are the files of this commit.
git diff --exit-code HEAD -- src tests/baseline .circleci/compare-baseline.sh
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
yq --version
jq --version

# The baseline is read from this checkout and is never downloaded or replaced.
# A missing or mismatching baseline and any difference end this step.
bash .circleci/compare-baseline.sh . "$record" "$archive" "$temporary/result.json"

copy=$(jq -r '.baseline.stored_copy' "$temporary/result.json")
mkdir -p /tmp/ansible-lint-pack-evidence
jq --arg purpose "$purpose" --arg commit "$CIRCLE_SHA1" \
  --arg job_url "${CIRCLE_BUILD_URL:-}" --arg source_tree "$(git rev-parse HEAD:src)" \
  --arg archive_sha256 "$(sha256sum "$archive" | cut -d ' ' -f 1)" \
  --arg record_blob "$(git rev-parse "HEAD:$record")" \
  --arg copy_blob "$(git rev-parse "HEAD:$copy")" \
  --arg comparison_sha256 "$(sha256sum .circleci/compare-baseline.sh | cut -d ' ' -f 1)" \
  '{result, purpose: $purpose, commit: $commit, job_url: $job_url,
    input_source: "src", source_tree: $source_tree, archive_sha256: $archive_sha256,
    comparison: ".circleci/compare-baseline.sh", comparison_sha256: $comparison_sha256,
    baseline: (.baseline + {record_git_blob: $record_blob, stored_copy_git_blob: $copy_blob}),
    candidate, parser, ignored, not_compared_as_text, targets, definition_sha256_note}' \
  "$temporary/result.json" | tee "/tmp/ansible-lint-pack-evidence/baseline-${purpose}.json"
