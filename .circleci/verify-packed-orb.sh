#!/bin/bash
# Read the actual orb-tools 12.5.0 workspace archive; never repack or modify it.
set -euo pipefail

archive=${1:?archive path required}
purpose=${2:?injection or publication required}
case "$purpose" in injection|publication) ;; *) exit 1 ;; esac
test "$(git rev-parse HEAD)" = "$CIRCLE_SHA1"
git diff --exit-code HEAD -- src
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT

# orb-tools/workspace-prep.sh archives dist/ and removes the original orb.yml.
tar -tzf "$archive" > "$temporary/members"
test "$(sort "$temporary/members")" = "$(printf './\n./orb.yml\n' | sort)"
tar -xOzf "$archive" ./orb.yml > "$temporary/orb.yml"
yq -o=json '.' "$temporary/orb.yml" > "$temporary/orb.json"
jq -e '
  .commands.execute.steps[-1] as $step |
  ($step | type == "object") and
  ($step | keys == ["run"]) and
  ($step.run | type == "object") and
  ($step.run | has("command")) and
  ($step.run | keys - ["command", "name"] | length == 0) and
  ($step.run.command == "ansible-lint") and
  (if $step.run | has("name") then $step.run.name | type == "string" else true end)
' "$temporary/orb.json" > /dev/null

mkdir -p /tmp/ansible-lint-pack-evidence
jq -n --arg purpose "$purpose" --arg commit "$CIRCLE_SHA1" \
  --arg job_url "${CIRCLE_BUILD_URL:-}" --arg source_tree "$(git rev-parse HEAD:src)" \
  --arg archive_sha256 "$(sha256sum "$archive" | cut -d ' ' -f 1)" \
  --arg packed_sha256 "$(sha256sum "$temporary/orb.yml" | cut -d ' ' -f 1)" \
  '{result:"passed",purpose:$purpose,commit:$commit,job_url:$job_url,
    input_source:"src",source_tree:$source_tree,archive_sha256:$archive_sha256,
    packed_sha256:$packed_sha256,final_command:"ansible-lint",
    allowed_run_attributes:["command","name"],circleci_failed_step_observed:false}' \
  | tee "/tmp/ansible-lint-pack-evidence/${purpose}.json"
