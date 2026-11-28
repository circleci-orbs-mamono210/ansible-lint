#!/bin/bash
# Verify this pack job's ./orb.yml against the published 1.1.0 baseline
# and the 2.0.0 differences adopted in #5552 (contract sections 5.6 and 23).
set -euo pipefail

archive=${1:?archive path required}
purpose=${2:?injection or publication required}
case "$purpose" in injection|publication) ;; *) exit 1 ;; esac
record=tests/baseline/orbss-ansible-lint-1.1.0.json
compare=.circleci/compare-baseline.sh
suite=.circleci/test-compare-baseline.sh
evidence=/tmp/ansible-lint-pack-evidence
self_test_file="baseline-self-test-2.0.0-${purpose}.json"
job_url=${CIRCLE_BUILD_URL:?pack job URL required}
pipeline_id=${PACK_PIPELINE_ID:?CircleCI pipeline ID required}

test "$(git rev-parse HEAD)" = "${CIRCLE_SHA1:?candidate commit required}"
git diff --exit-code HEAD -- src tests/baseline "$compare" "$suite" \
  .circleci/baseline-policy.jq .circleci/verify-packed-baseline.sh \
  .circleci/config.yml .circleci/test-deploy.yml
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
comparison_sha256=$(sha256sum "$compare" | cut -d ' ' -f 1)
suite_sha256=$(sha256sum "$suite" | cut -d ' ' -f 1)

# The preceding run step writes the report in this job's filesystem.
cp "$evidence/$self_test_file" "$temporary/self-test.json"
if ! jq -es --arg commit "$CIRCLE_SHA1" --arg job_url "$job_url" --arg purpose "$purpose" \
  --arg comparison "$comparison_sha256" --arg suite "$suite_sha256" '
    length == 1 and (.[0] |
    .result == "passed" and .target_release == "2.0.0" and .baseline_version == "1.1.0" and
    .commit == $commit and .job_url == $job_url and .purpose == $purpose and
    .comparison_sha256 == $comparison and .self_test_sha256 == $suite and
    .failed_cases == 0 and .skipped_cases == 0 and .cases > 0 and
    .cases == (.results | length) and all(.results[]; .result == "passed"))
  ' "$temporary/self-test.json" > /dev/null; then
  echo "Expected a successful 2.0.0 self-test from this $purpose pack job and commit: $self_test_file" >&2
  exit 1
fi

# Read the archive that orb-tools packed in this job.
bash "$compare" . "$record" "$archive" "$temporary/result.json"
copy=$(jq -er '.baseline.stored_copy' "$temporary/result.json")
list=$(jq -er '.expected_differences.path' "$temporary/result.json")
record_blob=$(git rev-parse --verify "HEAD:$record")
copy_blob=$(git rev-parse --verify "HEAD:$copy")
list_blob=$(git rev-parse --verify "HEAD:$list")
source_tree=$(git rev-parse --verify HEAD:src)
archive_sha256=$(sha256sum "$archive" | cut -d ' ' -f 1)
report_sha256=$(sha256sum "$temporary/self-test.json" | cut -d ' ' -f 1)

# Retain all findings of the comparator and link the two steps in one record.
jq --slurpfile test_report "$temporary/self-test.json" \
  --arg purpose "$purpose" --arg commit "$CIRCLE_SHA1" --arg job_url "$job_url" --arg pipeline_id "$pipeline_id" \
  --arg source_tree "$source_tree" --arg archive "$archive" --arg archive_sha256 "$archive_sha256" \
  --arg record_blob "$record_blob" --arg copy_blob "$copy_blob" --arg list_blob "$list_blob" \
  --arg comparison "$compare" --arg comparison_sha256 "$comparison_sha256" \
  --arg report_file "$self_test_file" --arg report_sha256 "$report_sha256" '
    . + {purpose:$purpose, commit:$commit, job_url:$job_url, pipeline_id:$pipeline_id,
         input_source:"src", source_tree:$source_tree, archive:$archive, archive_sha256:$archive_sha256,
         comparison_status:.comparison, comparison:$comparison, comparison_sha256:$comparison_sha256,
         self_test: ($test_report[0] | {file:$report_file, report_sha256:$report_sha256,
           script:.self_test, script_sha256:.self_test_sha256, comparison_sha256,
           result, cases, failed_cases, skipped_cases})}
    | .baseline += {record_git_blob:$record_blob, stored_copy_git_blob:$copy_blob}
    | .expected_differences.git_blob = $list_blob
  ' "$temporary/result.json" > "$temporary/evidence.json"
mv "$temporary/evidence.json" "$evidence/baseline-${purpose}.json"
cat "$evidence/baseline-${purpose}.json"
