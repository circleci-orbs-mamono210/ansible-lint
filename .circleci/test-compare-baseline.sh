#!/bin/bash
# Self-test of compare-baseline.sh, the comparison that
# verify-packed-baseline.sh runs on the actual archives (#5538).
#
# Every case gets its own temporary directory with a copy of the identity
# record, a copy of the stored baseline, and an archive made for the case.
# Nothing in the repository is changed: not src/, and not tests/baseline/.
# A case passes only when the comparison ends with the expected exit status,
# the expected category, and exactly the expected differing paths.
#
# Usage: test-compare-baseline.sh <purpose> [<evidence directory>] [1.1.0|2.0.0]
set -euo pipefail

purpose=${1:?injection, publication or local required}
case "$purpose" in injection|publication|local) ;; *) exit 1 ;; esac
evidence_directory=${2:-/tmp/ansible-lint-pack-evidence}
here=$(cd "$(dirname "$0")" && pwd)
repository=$(dirname "$here")
compare="$here/compare-baseline.sh"
target_release=${3:-1.1.0}
case "$target_release" in
  1.1.0) baseline_version=1.0.0; evidence_file="baseline-self-test-${purpose}.json" ;;
  2.0.0) baseline_version=1.1.0; evidence_file="baseline-self-test-2.0.0-${purpose}.json" ;;
  *) echo "unsupported target release: $target_release" >&2; exit 1 ;;
esac
record="tests/baseline/orbss-ansible-lint-${baseline_version}.json"
copy="tests/baseline/orbss-ansible-lint-${baseline_version}.yml"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
inputs=("$repository/$record" "$repository/$copy")
positive="$repository/$copy"
if [ "$target_release" = 2.0.0 ]; then
  list=$(jq -er '.ci_reference.expected_differences' "$repository/$record")
  inputs+=("$repository/$list")
  # Build the positive fixture independently of the list and the comparator.
  # Keep the packed YAML spelling for cases that edit a tag or a comment.
  positive="$work/positive.yml"
  sed -e 's/^\( *\)molecule-role-test:$/\1molecule_role_test:/' \
      -e 's/^\( *\)molecule-playbook-test:$/\1molecule_playbook_test:/' \
      -e 's/^\( *PARAM_MOLECULE_ROLE_TEST: \)<< parameters\.molecule-role-test >>$/\1<< parameters.molecule_role_test >>/' \
      -e 's/^\( *PARAM_MOLECULE_PLAYBOOK_TEST: \)<< parameters\.molecule-playbook-test >>$/\1<< parameters.molecule_playbook_test >>/' \
      "$repository/$copy" > "$positive"
fi
baseline_before=$(sha256sum "${inputs[@]}")
# The tools of this job, shown first so that a failure names them.
yq --version
jq --version
: > "$work/cases.jsonl"
failed=0
skipped=0

# Start each case from the positive fixture for the selected release.
begin() {
  case_id=$1
  case_group=$2
  case_target=$3
  case_input=$4
  case_root="$work/$case_id"
  candidate="$case_root/dist/orb.yml"
  pack=yes
  mkdir -p "$case_root/root/tests/baseline" "$case_root/dist"
  cp "$repository/$record" "$case_root/root/$record"
  cp "$repository/$copy" "$case_root/root/$copy"
  if [ "$target_release" = 2.0.0 ]; then cp "$repository/$list" "$case_root/root/$list"; fi
  cp "$positive" "$candidate"
}

# Replace a text that occurs exactly once. The other bytes stay as they are.
edit_text() {
  jq -R -s -j --arg old "$2" --arg new "$3" '
    split($old)
    | if length == 2 then join($new) else error("the text must occur exactly once") end
  ' "$1" > "$1.new"
  mv "$1.new" "$1"
}

# Change the parsed document. The result is written as JSON, which is YAML in
# flow style with every string quoted. Case A02 shows that this form alone is
# accepted, so a rejection comes from the change itself.
edit_jq() {
  yq -o=json '.' "$1" | jq "$2" > "$1.new"
  mv "$1.new" "$1"
}

# Change a copy of the identity record.
edit_record() {
  jq "$2" "$1" > "$1.new"
  mv "$1.new" "$1"
}

category_of() {
  case "$1" in
    0) if [ "$target_release" = 2.0.0 ]; then echo adopted-differences; else echo equal; fi ;;
    20) echo baseline-record ;;
    21) echo baseline-missing ;;
    22) echo baseline-mismatch ;;
    23) echo expected-differences ;;
    30) echo candidate-archive ;;
    31) echo candidate-parse ;;
    40) echo difference ;;
    *) echo unknown ;;
  esac
}

# Run the comparison for the current case and require the expected result.
# After the status, pass mismatch paths or an optional pre-comparison diagnostic.
expect() {
  local expected_status=$1 status=0 expected actual outcome=passed message_fragment='' diagnostic=''
  shift
  if [ "$expected_status" -ne 0 ] && [ "$expected_status" -ne 40 ] && [ "$#" -gt 0 ]; then
    message_fragment=$1
    shift
  fi
  if [ "$pack" = yes ]; then
    # The layout of orb-tools/pack: the archive holds ./ and ./orb.yml.
    tar -czf "$case_root/orb_source.tar.gz" -C "$case_root/dist" .
  fi
  bash "$compare" "$case_root/root" "$record" "$case_root/orb_source.tar.gz" \
    "$case_root/result.json" > "$case_root/output" 2>&1 || status=$?
  expected=$(jq -c -n --argjson status "$expected_status" \
    --arg category "$(category_of "$expected_status")" '
      {exit_status: $status, category: $category,
       comparison: (if $status == 0 or $status == 40 then "run" else "not run" end),
       paths: ($ARGS.positional | sort)}' --args "$@")
  actual=$(jq -c -n --argjson status "$status" '{exit_status: $status, category: null, comparison: null, paths: []}')
  if [ -s "$case_root/result.json" ]; then
    actual=$(jq -c --argjson status "$status" '
      if .exit_status != $status then error("the result file and the exit status disagree") else . end
      | {exit_status: $status, category, comparison,
         paths: (([.targets[]? | (.mismatches // .differences)[]?.path] +
           [.public_names[]? | select(.matches == false) | . as $names |
             if .candidate == null then "names." + .kind
             else (.added + .missing)[] | "names." + $names.kind + "." + . end]) | sort)}' "$case_root/result.json")
    if [ -n "$message_fragment" ]; then
      diagnostic=$(jq -r '.message // ""' "$case_root/result.json")
      if [[ "$diagnostic" != *"$message_fragment"* ]]; then
        actual=$(jq -c --arg message "$diagnostic" '. + {unexpected_message:$message}' <<< "$actual")
      fi
    fi
  fi
  if [ "$expected_status" -eq 0 ] && [ "$target_release" = 2.0.0 ]; then
    # Positive evidence must identify all actual changes, including their values.
    if ! jq -e --slurpfile plan "$case_root/root/$list" '
      (.targets | length) == 4 and (.public_names | length) == 3 and
      all(.public_names[]; .matches) and all(.targets[]; .listed_differences_match) and
      .expected_differences.count == 6 and
      (([.targets[] as $t | $t.differences[] |
          {element:$t.path, path:(.path | ltrimstr($t.path+".")), change, before, after}] | sort_by(.path))
       == ($plan[0].differences | map({element,path,change,before,after}) | sort_by(.path)))
    ' "$case_root/result.json" > /dev/null; then
      actual=$(jq -c '. + {valid_positive_evidence:false}' <<< "$actual")
    fi
  fi
  if [ "$expected" != "$actual" ]; then
    outcome=failed
    failed=$((failed + 1))
    {
      echo "--- $case_id: expected $expected"
      echo "--- $case_id: actual   $actual"
      cat "$case_root/output"
    } >&2
  fi
  jq -c -n --arg id "$case_id" --arg group "$case_group" --arg target "$case_target" \
    --arg input "$case_input" --arg result "$outcome" --arg diagnostic "$diagnostic" \
    --argjson expected "$expected" --argjson actual "$actual" \
    '{id: $id, group: $group, target: $target, input: $input,
      expected: $expected, actual: $actual, result: $result}
     + (if $diagnostic == "" then {} else {message:$diagnostic} end)' >> "$work/cases.jsonl"
  printf '%-7s %-4s %3s %-18s %s\n' "$outcome" "$case_id" "$expected_status" \
    "$(category_of "$expected_status")" "$case_input"
}

# Record a case that cannot be made in this environment. It is not a pass.
skip() {
  skipped=$((skipped + 1))
  jq -c -n --arg id "$case_id" --arg group "$case_group" --arg target "$case_target" \
    --arg input "$case_input" --arg reason "$1" \
    '{id: $id, group: $group, target: $target, input: $input,
      expected: null, actual: null, result: "skipped", reason: $reason}' >> "$work/cases.jsonl"
  printf '%-7s %-4s %3s %-18s %s\n' skipped "$case_id" - - "$case_input ($1)"
}

default=executors.default
execute=commands.execute

case "$target_release" in
1.1.0)
# --- A: accepted -------------------------------------------------------------

begin A01 accepted both "the packed Orb has the same bytes as the baseline"
expect 0

begin A02 accepted both "every mapping lists its keys in reverse order; written as JSON (flow style, quoted strings)"
edit_jq "$candidate" '
  def reversed:
    if type == "object" then to_entries | reverse | map(.value |= reversed) | from_entries
    elif type == "array" then map(reversed)
    else . end;
  reversed'
expect 0

begin A03 accepted both "block-style text with only the order of mapping keys changed in both targets"
edit_text "$candidate" $'                default: small\n                description: |\n                    CircleCI resource class' \
  $'                description: |\n                    CircleCI resource class'
edit_text "$candidate" $'                type: enum\n' $'                type: enum\n                default: small\n'
edit_text "$candidate" $'                command: ansible-lint\n                name: Execute Ansible lint\n' \
  $'                name: Execute Ansible lint\n                command: ansible-lint\n'
expect 0

begin A04 accepted both "comment lines and trailing comments added inside both targets"
edit_text "$candidate" $'executors:\n    default:\n' $'executors:\n    # A comment line.\n    default:  # A trailing comment.\n'
edit_text "$candidate" $'                type: string\n' $'                type: string  # A trailing comment.\n'
edit_text "$candidate" $'        steps:\n            - run:\n                command: |\n                    ansible-lint --version\n' \
  $'        steps:  # A trailing comment.\n            # A comment line.\n            - run:\n                command: |\n                    ansible-lint --version\n'
expect 0

begin A05 accepted both "only the quoting of two string scalars changed in the block-style text"
edit_text "$candidate" $'                default: small\n' $'                default: "small"\n'
edit_text "$candidate" $'        description: CircleCI executor Ansible lint\n' $'        description: \'CircleCI executor Ansible lint\'\n'
expect 0

begin A06 accepted both "new executor and command added; Orb description, display and examples changed"
edit_jq "$candidate" '
  .executors.python = {"docker": [{"image": "cimg/python:3.14.10"}]}
  | .commands.install = {"description": "Install", "steps": [{"run": {"command": "true", "name": "Install"}}]}
  | .description = "Another description"
  | .display.source_url = "https://example.com/source"
  | del(.examples)'
expect 0

# --- B: the baseline cannot be used; the comparison must not run ---------------

begin B01 baseline record "the identity record is missing"
rm "$case_root/root/$record"
expect 20

begin B02 baseline record "the identity record is not JSON"
echo 'not json' > "$case_root/root/$record"
expect 20

begin B03 baseline record "the identity record has no expected SHA-256"
edit_record "$case_root/root/$record" 'del(.expected.sha256)'
expect 20

begin B04 baseline record "the identity record names only one of the two targets"
edit_record "$case_root/root/$record" '.ci_reference.comparison_targets = ["commands.execute"]'
expect 20

begin B05 baseline record "the identity record points to a stored copy outside the root"
edit_record "$case_root/root/$record" '.stored_copy.path = "../baseline.yml"'
expect 20

begin B06 baseline "stored copy" "the stored copy is missing"
rm "$case_root/root/$copy"
expect 21

begin B07 baseline "stored copy" "the stored copy is a directory, not a regular file"
rm "$case_root/root/$copy"
mkdir "$case_root/root/$copy"
expect 21

begin B08 baseline "stored copy" "the stored copy cannot be read (no read permission)"
if [ "$(id -u)" -eq 0 ]; then
  skip "the user root can read a file without permission"
else
  chmod 000 "$case_root/root/$copy"
  expect 21
  chmod 600 "$case_root/root/$copy"
fi

begin B09 baseline "stored copy" "one character of the stored copy is changed; the size is the same"
edit_text "$case_root/root/$copy" $'        description: CircleCI executor Ansible lint\n' $'        description: CircleCI executor Ansible lynt\n'
expect 22

begin B10 baseline "stored copy" "a newline is added at the end of the stored copy"
echo >> "$case_root/root/$copy"
expect 22

begin B11 baseline "stored copy" "the stored copy is empty"
: > "$case_root/root/$copy"
expect 22

begin B12 baseline record "one digit of the expected SHA-256 is changed"
edit_record "$case_root/root/$record" '.expected.sha256 |= (if .[0:1] == "0" then "1" else "0" end) + .[1:]'
expect 22

begin B13 baseline record "the expected size is changed by one byte"
edit_record "$case_root/root/$record" '.expected.size_bytes += 1'
expect 22

begin B14 baseline record "the record describes its stored copy with another SHA-256 than the expected one"
edit_record "$case_root/root/$record" '.stored_copy.sha256 |= (if .[0:1] == "0" then "1" else "0" end) + .[1:]'
expect 22

begin B15 baseline "stored copy" "the stored copy is changed and the packed Orb differs; the hash check must end the check first"
edit_text "$case_root/root/$copy" $'        description: CircleCI executor Ansible lint\n' $'        description: CircleCI executor Ansible lynt\n'
edit_jq "$candidate" '.executors.default.description = "changed"'
expect 22

# --- P: the packed Orb cannot be read as one unambiguous document --------------

begin P01 candidate archive "the archive is missing"
pack=no
expect 30

begin P02 candidate archive "the archive holds no ./orb.yml"
mv "$candidate" "$case_root/dist/other.yml"
expect 30

begin P03 candidate archive "./orb.yml is empty"
: > "$candidate"
expect 30

begin P04 candidate document "./orb.yml is not YAML"
printf 'executors: [unclosed\n' > "$candidate"
expect 31

begin P05 candidate document "./orb.yml holds two documents"
printf -- '---\nversion: 2.1\n' >> "$candidate"
expect 31

begin P06 candidate document "the top level of ./orb.yml is a sequence"
printf -- '- executors\n- commands\n' > "$candidate"
expect 31

begin P07 candidate document "a mapping key is repeated; the last value equals the baseline"
edit_text "$candidate" $'            image:\n                default: ghcr.io' $'            image:\n                default: cimg/base:current\n                default: ghcr.io'
expect 31

# --- E: executors.default differs ----------------------------------------------

begin E01 difference "$default" "description: one character added"
edit_jq "$candidate" '.executors.default.description += "."'
expect 40 "$default.description"

begin E02 difference "$default" "docker image expression: spaces added inside << >>"
edit_jq "$candidate" '.executors.default.docker[0].image = "<< parameters.image >>"'
expect 40 "$default.docker[0].image"

begin E03 difference "$default" "docker sequence: a second image added"
edit_jq "$candidate" '.executors.default.docker += [{"image": "cimg/base:current"}]'
expect 40 "$default.docker[1]"

begin E04 difference "$default" "default GHCR digest: one hexadecimal digit changed"
edit_jq "$candidate" '.executors.default.parameters.image.default |= sub("sha256:3dd0b103"; "sha256:3dd0b104")'
expect 40 "$default.parameters.image.default"

begin E05 difference "$default" "default GHCR image: a tag in place of the digest"
edit_jq "$candidate" '.executors.default.parameters.image.default |= sub("@sha256:[0-9a-f]{64}$"; ":latest")'
expect 40 "$default.parameters.image.default"

begin E06 difference "$default" "parameter type: string changed to enum"
edit_jq "$candidate" '.executors.default.parameters.image.type = "enum"'
expect 40 "$default.parameters.image.type"

begin E07 difference "$default" "parameter description: block scalar | changed to |- (final newline removed)"
edit_text "$candidate" $'                description: |\n                    Docker image used' $'                description: |-\n                    Docker image used'
expect 40 "$default.parameters.image.description"

begin E08 difference "$default" "parameter default: small changed to medium"
edit_jq "$candidate" '.executors.default.parameters.resource_class.default = "medium"'
expect 40 "$default.parameters.resource_class.default"

begin E09 difference "$default" "enum order: the first two values swapped"
edit_jq "$candidate" '.executors.default.parameters.resource_class.enum |= [.[1], .[0]] + .[2:]'
expect 40 "$default.parameters.resource_class.enum[0]" "$default.parameters.resource_class.enum[1]"

begin E10 difference "$default" "enum: a value added at the end"
edit_jq "$candidate" '.executors.default.parameters.resource_class.enum += ["xlarge"]'
expect 40 "$default.parameters.resource_class.enum[4]"

begin E11 difference "$default" "enum: the last value removed"
edit_jq "$candidate" '.executors.default.parameters.resource_class.enum |= .[:-1]'
expect 40 "$default.parameters.resource_class.enum[3]"

begin E12 difference "$default" "parameters: a parameter added"
edit_jq "$candidate" '.executors.default.parameters.tag = {"default": "latest", "type": "string"}'
expect 40 "$default.parameters.tag"

begin E13 difference "$default" "parameters: a parameter removed"
edit_jq "$candidate" 'del(.executors.default.parameters.resource_class)'
expect 40 "$default.parameters.resource_class"

begin E14 difference "$default" "resource_class: the parameter reference replaced by a fixed value"
edit_jq "$candidate" '.executors.default.resource_class = "small"'
expect 40 "$default.resource_class"

begin E15 difference "$default" "a key added to the executor"
edit_jq "$candidate" '.executors.default.environment = {"LANG": "C"}'
expect 40 "$default.environment"

begin E16 difference "$default" "the executor is removed"
edit_jq "$candidate" 'del(.executors.default)'
expect 40 "$default"

# --- X: commands.execute differs -----------------------------------------------

begin X01 difference "$execute" "description: the final newline removed"
edit_jq "$candidate" '.commands.execute.description |= rtrimstr("\n")'
expect 40 "$execute.description"

begin X02 difference "$execute" "parameter default: false changed to true"
edit_jq "$candidate" '.commands.execute.parameters["molecule-role-test"].default = true'
expect 40 "$execute.parameters.molecule-role-test.default"

begin X03 difference "$execute" "scalar type: boolean false changed to the string \"false\" in the text"
edit_text "$candidate" $'            molecule-playbook-test:\n                default: false\n' $'            molecule-playbook-test:\n                default: "false"\n'
expect 40 "$execute.parameters.molecule-playbook-test.default"

begin X04 difference "$execute" "parameter type: boolean changed to string"
edit_jq "$candidate" '.commands.execute.parameters["molecule-role-test"].type = "string"'
expect 40 "$execute.parameters.molecule-role-test.type"

begin X05 difference "$execute" "parameter description: one character removed"
edit_jq "$candidate" '.commands.execute.parameters["molecule-role-test"].description |= sub("CIRCLE_SHA1"; "CIRCLE_SHA")'
expect 40 "$execute.parameters.molecule-role-test.description"

begin X06 difference "$execute" "parameter name: molecule-role-test renamed to molecule_role_test"
edit_jq "$candidate" '.commands.execute.parameters |= (.molecule_role_test = .["molecule-role-test"] | del(.["molecule-role-test"]))'
expect 40 "$execute.parameters.molecule-role-test" "$execute.parameters.molecule_role_test"

begin X07 difference "$execute" "parameters: a parameter added"
edit_jq "$candidate" '.commands.execute.parameters.config = {"default": "", "type": "string"}'
expect 40 "$execute.parameters.config"

begin X08 difference "$execute" "step order: the first two steps swapped"
edit_jq "$candidate" '.commands.execute.steps |= [.[1], .[0]] + .[2:]'
expect 40 "$execute.steps[0].run.command" "$execute.steps[0].run.name" \
  "$execute.steps[1].run.command" "$execute.steps[1].run.name"

begin X09 difference "$execute" "steps: the second step removed"
edit_jq "$candidate" 'del(.commands.execute.steps[1])'
expect 40 "$execute.steps[1].run.command" "$execute.steps[1].run.environment" "$execute.steps[1].run.name" \
  "$execute.steps[2].run.command" "$execute.steps[2].run.environment" "$execute.steps[2].run.name" \
  "$execute.steps[3]"

begin X10 difference "$execute" "steps: a step added at the end"
edit_jq "$candidate" '.commands.execute.steps += [{"run": {"command": "echo done", "name": "Extra"}}]'
expect 40 "$execute.steps[4]"

begin X11 difference "$execute" "step name changed"
edit_jq "$candidate" '.commands.execute.steps[0].run.name = "Show version"'
expect 40 "$execute.steps[0].run.name"

begin X12 difference "$execute" "embedded script: one character changed"
edit_jq "$candidate" '.commands.execute.steps[2].run.command |= sub("-maxdepth 1"; "-maxdepth 2")'
expect 40 "$execute.steps[2].run.command"

begin X13 difference "$execute" "embedded script: the final newline removed"
edit_jq "$candidate" '.commands.execute.steps[2].run.command |= rtrimstr("\n")'
expect 40 "$execute.steps[2].run.command"

begin X14 difference "$execute" "embedded script: a space added at the end of one line"
edit_jq "$candidate" '.commands.execute.steps[2].run.command |= sub("#!/bin/bash\n"; "#!/bin/bash \n")'
expect 40 "$execute.steps[2].run.command"

begin X15 difference "$execute" "environment value: spaces removed inside << >>"
edit_jq "$candidate" '.commands.execute.steps[2].run.environment.PARAM_MOLECULE_ROLE_TEST = "<<parameters.molecule-role-test>>"'
expect 40 "$execute.steps[2].run.environment.PARAM_MOLECULE_ROLE_TEST"

begin X16 difference "$execute" "environment: a variable added"
edit_jq "$candidate" '.commands.execute.steps[2].run.environment.EXTRA = "1"'
expect 40 "$execute.steps[2].run.environment.EXTRA"

begin X17 difference "$execute" "final command: ansible-lint changed to ansible-lint || true"
edit_jq "$candidate" '.commands.execute.steps[3].run.command = "ansible-lint || true"'
expect 40 "$execute.steps[3].run.command"

begin X18 difference "$execute" "final step: the attribute when added"
edit_jq "$candidate" '.commands.execute.steps[3].run.when = "always"'
expect 40 "$execute.steps[3].run.when"

begin X19 difference "$execute" "first step: a run step replaced by checkout"
edit_jq "$candidate" '.commands.execute.steps[0] = "checkout"'
expect 40 "$execute.steps[0]" "$execute.steps[0].run"

begin X20 difference "$execute" "the command is removed"
edit_jq "$candidate" 'del(.commands.execute)'
expect 40 "$execute"

begin X21 difference "$execute" "description: the value removed in the text, which leaves null"
edit_text "$candidate" $'    execute:\n        description: |\n            Execute Ansible lint\n' $'    execute:\n        description:\n'
expect 40 "$execute.description"

begin X22 difference "$execute" "scalar type: boolean false changed to the number 0"
edit_jq "$candidate" '.commands.execute.parameters["molecule-role-test"].default = 0'
expect 40 "$execute.parameters.molecule-role-test.default"

# --- Y: the same JSON value, but another YAML node -----------------------------

begin Y01 difference "$default" "an explicit tag added to an unchanged scalar"
edit_text "$candidate" $'                type: string\n' $'                type: !custom string\n'
expect 40 "$default.parameters.image.type"

begin Y02 difference "$default" "an enum value replaced by an alias of an equal value"
edit_text "$candidate" $'                default: small\n' $'                default: &size small\n'
edit_text "$candidate" $'                    - small\n' $'                    - *size\n'
expect 40 "$default.parameters.resource_class.enum[0]"

begin Y03 difference "$default" "an explicit tag added to an unchanged mapping key"
edit_text "$candidate" $'        description: CircleCI executor Ansible lint\n' $'        !custom description: CircleCI executor Ansible lint\n'
expect 40 "$default.description"

begin Y04 difference "$execute" "boolean false written as the YAML 1.1 word no, which this parser reads as a string"
edit_text "$candidate" $'            molecule-playbook-test:\n                default: false\n' $'            molecule-playbook-test:\n                default: no\n'
expect 40 "$execute.parameters.molecule-playbook-test.default"

  ;;

2.0.0)
  role_ref="$execute.steps[2].run.environment.PARAM_MOLECULE_ROLE_TEST"
  playbook_ref="$execute.steps[2].run.environment.PARAM_MOLECULE_PLAYBOOK_TEST"

  begin A01 accepted all "only the six adopted changes"
  expect 0
  begin A02 accepted all "mapping keys reordered, flow style, a comment and changed Orb metadata"
  edit_jq "$candidate" '
    .commands.execute.parameters |= (to_entries | reverse | from_entries)
    | .description = "different Orb metadata" | .examples = {} | .jobs = {}'
  echo '# comparison ignores this comment' >> "$candidate"
  expect 0

  begin B01 baseline source "stored source missing, candidate also invalid"
  rm "$case_root/root/$copy"
  echo '[' > "$candidate"
  expect 21 "the stored copy is missing"
  begin B02 baseline source "stored source cannot be read"
  if [ "$(id -u)" -eq 0 ]; then
    skip "root can read mode 000"
  else
    chmod 000 "$case_root/root/$copy"
    expect 21 "cannot read the stored copy"
    chmod 600 "$case_root/root/$copy"
  fi
  begin B03 baseline source "wrong size, candidate also invalid"
  echo >> "$case_root/root/$copy"
  echo '[' > "$candidate"
  expect 22 "bytes; the record expects"
  begin B04 baseline source "same number of bytes, wrong SHA-256"
  edit_text "$case_root/root/$copy" 'version: 2.1' 'version: 2.2'
  expect 22 "SHA-256"

  begin L01 policy list "list missing"
  rm "$case_root/root/$list"
  expect 23
  begin L02 policy list "list repeats a path at the expense of another"
  edit_record "$case_root/root/$list" '.differences[1] = .differences[3]'
  expect 23
  begin L03 policy list "listed source for a new definition is the other old definition"
  edit_record "$case_root/root/$list" '(.differences[] | select(.path=="parameters.molecule_role_test")).copy_from_baseline = "parameters.molecule-playbook-test"'
  expect 23
  begin L04 policy list "listed before reference disagrees with the published value"
  edit_record "$case_root/root/$list" '(.differences[] | select(.change=="changed")).before.value = "wrong"'
  expect 23
  begin L05 policy list "the expected reference changes only in the test copy of the list"
  edit_record "$case_root/root/$list" '(.differences[] | select(.path | endswith("PARAM_MOLECULE_ROLE_TEST"))).after.value = "different listed reference"'
  expect 40 "$role_ref"

  begin D01 difference "$execute" "one approved reference update omitted"
  edit_jq "$candidate" '.commands.execute.steps[2].run.environment.PARAM_MOLECULE_ROLE_TEST = "<< parameters.molecule-role-test >>"'
  expect 40 "$role_ref"
  begin D02 difference "$execute" "one extra change to the description"
  edit_jq "$candidate" '.commands.execute.description += "."'
  expect 40 "$execute.description"
  begin D03 difference "$execute" "role and playbook environment references swapped"
  edit_jq "$candidate" '.commands.execute.steps[2].run.environment |=
    . + {PARAM_MOLECULE_ROLE_TEST:.PARAM_MOLECULE_PLAYBOOK_TEST, PARAM_MOLECULE_PLAYBOOK_TEST:.PARAM_MOLECULE_ROLE_TEST}'
  expect 40 "$role_ref" "$playbook_ref"

  for kind in role playbook; do
    old="molecule-$kind-test"
    new="molecule_${kind}_test"
    if [ "$kind" = role ]; then env_name=PARAM_MOLECULE_ROLE_TEST; else env_name=PARAM_MOLECULE_PLAYBOOK_TEST; fi
    ref_path="$execute.steps[2].run.environment.$env_name"
    parameter="$execute.parameters.$new"

    begin "W-$kind" difference "$execute" "remove only the spaces inside the $kind reference"
    edit_jq "$candidate" ".commands.execute.steps[2].run.environment.$env_name = \"<<parameters.$new>>\""
    expect 40 "$ref_path"
    begin "N-$kind" difference "$execute" "old $kind parameter present with YAML null"
    edit_jq "$candidate" ".commands.execute.parameters[\"$old\"] = null"
    expect 40 "$execute.parameters.$old"

    begin "B-$kind" difference "$execute" "set the new $kind default to boolean true"
    edit_jq "$candidate" ".commands.execute.parameters.$new.default = true"
    expect 40 "$parameter.default"
    begin "S-$kind" difference "$execute" "set the new $kind default to the string false"
    edit_jq "$candidate" ".commands.execute.parameters.$new.default = \"false\""
    expect 40 "$parameter.default"
    begin "T-$kind" difference "$execute" "change the description of the new $kind definition"
    edit_jq "$candidate" ".commands.execute.parameters.$new.description += \".\""
    expect 40 "$parameter.description"
  done

  begin D04 difference "$execute" "add an unlisted child to a renamed definition"
  edit_jq "$candidate" '.commands.execute.parameters.molecule_role_test.extra = null'
  expect 40 "$execute.parameters.molecule_role_test.extra"
  begin D05 difference "$execute" "custom YAML tag on a scalar inside a renamed definition"
  edit_text "$candidate" $'molecule_role_test:\n                default: false' $'molecule_role_test:\n                default: !custom false'
  expect 40 "$execute.parameters.molecule_role_test.default"

  begin E01 difference executors.default "swap two enum entries in default"
  edit_jq "$candidate" '.executors.default.parameters.resource_class.enum |= [.[1],.[0]] + .[2:]'
  expect 40 'executors.default.parameters.resource_class.enum[0]' 'executors.default.parameters.resource_class.enum[1]'
  begin E02 difference executors.python "change the pinned python image"
  edit_jq "$candidate" '.executors.python.parameters.image.default += "a"'
  expect 40 'executors.python.parameters.image.default'
  begin E03 difference commands.install "remove the final newline from the embedded install script"
  edit_jq "$candidate" '.commands.install.steps[0].run.command |= rtrimstr("\n")'
  expect 40 'commands.install.steps[0].run.command'

  for kind in executors commands; do
    if [ "$kind" = executors ]; then name=python; else name=install; fi
    begin "A-$kind" name "$kind" "add a public name in $kind"
    edit_jq "$candidate" ".$kind.extra = .$kind.$name"
    expect 40 "names.$kind.extra"
    begin "M-$kind" name "$kind" "remove $kind.$name"
    edit_jq "$candidate" "del(.$kind.$name)"
    expect 40 "$kind.$name" "names.$kind.$name"
    begin "R-$kind" name "$kind" "rename $kind.$name, keeping the count"
    edit_jq "$candidate" ".$kind.extra = .$kind.$name | del(.$kind.$name)"
    expect 40 "$kind.$name" "names.$kind.$name" "names.$kind.extra"
  done
  begin J01 name jobs "add one public job with the four definitions and six changes correct"
  edit_jq "$candidate" '.jobs.extra = {executor:"default", steps:["checkout"]}'
  expect 40 'names.jobs.extra'
  begin J02 name jobs "jobs is present as a sequence"
  edit_jq "$candidate" '.jobs = []'
  expect 40 'names.jobs'
  ;;
esac

# --- Result --------------------------------------------------------------------

baseline_after=$(sha256sum "${inputs[@]}")
if [ "$baseline_before" != "$baseline_after" ]; then
  echo "the self-test changed the baseline files of the repository" >&2
  failed=$((failed + 1))
fi
# In CI every case must run. A skipped case is not a pass.
if [ "$purpose" != local ] && [ "$skipped" -ne 0 ]; then
  echo "the self-test skipped $skipped case(s) in CI" >&2
  failed=$((failed + 1))
fi
total=$(wc -l < "$work/cases.jsonl" | tr -d '[:space:]')
if [ "$failed" -eq 0 ]; then
  outcome=passed
else
  outcome=failed
fi
mkdir -p "$evidence_directory"
jq -s --arg target_release "$target_release" --arg baseline_version "$baseline_version" \
  --arg result "$outcome" --arg purpose "$purpose" --arg commit "${CIRCLE_SHA1:-}" \
  --arg job_url "${CIRCLE_BUILD_URL:-}" --argjson failed "$failed" --argjson skipped "$skipped" \
  --arg comparison_sha256 "$(sha256sum "$compare" | cut -d ' ' -f 1)" \
  --arg self_test_sha256 "$(sha256sum "$0" | cut -d ' ' -f 1)" \
  --arg yq_version "$(yq --version 2>&1 | head -n 1)" --arg jq_version "$(jq --version 2>&1 | head -n 1)" \
  '{result: $result, target_release: $target_release, baseline_version: $baseline_version, purpose: $purpose, commit: $commit, job_url: $job_url,
    comparison: ".circleci/compare-baseline.sh", comparison_sha256: $comparison_sha256,
    self_test: ".circleci/test-compare-baseline.sh", self_test_sha256: $self_test_sha256,
    parser: {yaml: $yq_version, json: $jq_version},
    isolation: "Each case used its own temporary copy of the identity record and the stored baseline and its own archive. No file of the repository was changed.",
    cases: length, failed_cases: $failed, skipped_cases: $skipped,
    by_group: (group_by(.group) | map({group: .[0].group, cases: length})),
    results: .}' "$work/cases.jsonl" > "$evidence_directory/$evidence_file"
echo "baseline comparison self-test ($target_release): $outcome ($total cases, $failed failed, $skipped skipped)"
echo "evidence: $evidence_directory/$evidence_file"
[ "$failed" -eq 0 ]
