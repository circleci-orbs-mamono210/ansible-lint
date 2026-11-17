#!/bin/bash
# Read the actual orb-tools 12.5.0 workspace archive; never repack or modify it.
# #5537: the packed install command has no parameters, is this commit's
# src/scripts/install.sh, and holds the fixed information of the record.
set -euo pipefail

archive=${1:?archive path required}
purpose=${2:?injection or publication required}
case "$purpose" in injection|publication) ;; *) exit 1 ;; esac
test "$(git rev-parse HEAD)" = "$CIRCLE_SHA1"
git diff --exit-code HEAD -- src python-install-lock.json
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT

tar -xOzf "$archive" ./orb.yml > "$temporary/orb.yml"
yq -o=json '.' "$temporary/orb.yml" > "$temporary/orb.json"

# No parameters and exactly one run step that has only a name and a command.
jq -e '
  .commands.install as $install |
  ($install | type == "object") and
  ($install | keys == ["description", "steps"]) and
  ($install.description | type == "string") and
  ($install.steps | type == "array") and
  ($install.steps | length == 1) and
  ($install.steps[0] | type == "object") and
  ($install.steps[0] | keys == ["run"]) and
  ($install.steps[0].run | type == "object") and
  ($install.steps[0].run | keys == ["command", "name"]) and
  ($install.steps[0].run.name | type == "string") and
  ($install.steps[0].run.command | type == "string")
' "$temporary/orb.json" > /dev/null

# The pack writes "<<" of an included script as "\<<", and CircleCI turns it
# back when it compiles a configuration. Nothing else may differ.
jq -j '.commands.install.steps[0].run.command | split("\\<<") | join("<<")' \
  "$temporary/orb.json" > "$temporary/install.sh"
packed_sha256=$(sha256sum "$temporary/install.sh" | cut -d ' ' -f 1)
script_sha256=$(sha256sum src/scripts/install.sh | cut -d ' ' -f 1)
test "$packed_sha256" = "$script_sha256"

# The fixed information inside the packed command equals the record.
jq -r '.commands.install.steps[0].run.command
  | split("FIXED_INFORMATION = json.loads(r\"\"\"\n")[1]
  | split("\n\"\"\")")[0]' "$temporary/orb.json" > "$temporary/fixed.json"
test "$(jq -S '.' "$temporary/fixed.json")" = "$(jq -S '.fixed_information' python-install-lock.json)"
fixed_set_sha256=$(jq -cjS '.' "$temporary/fixed.json" | sha256sum | cut -d ' ' -f 1)
test "$fixed_set_sha256" = "$(jq -r '.fixed_set_sha256' python-install-lock.json)"

mkdir -p /tmp/ansible-lint-pack-evidence
jq -n --arg purpose "$purpose" --arg commit "$CIRCLE_SHA1" \
  --arg job_url "${CIRCLE_BUILD_URL:-}" --arg source_tree "$(git rev-parse HEAD:src)" \
  --arg archive_sha256 "$(sha256sum "$archive" | cut -d ' ' -f 1)" \
  --arg install_command_sha256 "$packed_sha256" --arg fixed_set_sha256 "$fixed_set_sha256" \
  '{result:"passed",purpose:$purpose,commit:$commit,job_url:$job_url,
    input_source:"src",source_tree:$source_tree,archive_sha256:$archive_sha256,
    command:"install",public_parameters:[],run_steps:1,
    allowed_run_attributes:["command","name"],
    script:"src/scripts/install.sh",install_command_sha256:$install_command_sha256,
    install_command_note:"SHA-256 of the packed command after \\<< is read as <<. It equals the script of this commit.",
    fixed_set_sha256:$fixed_set_sha256,fixed_information_record:"python-install-lock.json"}' \
  | tee "/tmp/ansible-lint-pack-evidence/install-${purpose}.json"
