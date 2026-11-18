#!/bin/bash
# Compare executors.default and commands.execute of a packed Orb with the
# published baseline (docs/python-install-contract.md, sections 5.3 and 5.4).
# verify-packed-baseline.sh runs this for the actual archives.
# test-compare-baseline.sh runs this same file for isolated inputs.
#
# Usage: compare-baseline.sh <root> <record> <archive> <result>
#   root     directory that holds the identity record and the stored copy
#   record   path of the identity record, relative to root
#   archive  orb-tools workspace archive that holds ./orb.yml; it is only read
#   result   file that receives the result as JSON
#
# Exit status:
#    0  both targets equal the baseline
#   20  the identity record is missing, unreadable, or not usable
#   21  the stored copy is missing or is not a readable regular file
#   22  the size or SHA-256 of the stored copy is not the expected value
#   30  the archive or its ./orb.yml cannot be read
#   31  the packed Orb cannot be parsed, or its meaning depends on the parser
#   40  a target differs from the baseline
#   50  the check itself cannot work (tools, or the verified baseline)
#
# Only mapping key order and comments are ignored. Quoting and block or flow
# style disappear when YAML is parsed. Everything else is compared for every
# node: the set of keys, sequence order and length, the resolved tag, and the
# scalar value. The baseline has no alias, no explicit tag, and no key that is
# not a string, so each of these in a target is reported as a difference.
#
# Only yq operators that old releases have are used (path, tag, is_key, "...").
# The CLI image of orb-tools 12.5.0 carried yq 4.31.2 when this was written.
set -euo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: compare-baseline.sh <root> <record> <archive> <result>" >&2
  exit 50
fi
root=$1
record=$2
archive=$3
result=$4
targets=(executors.default commands.execute)

for tool in yq jq tar sha256sum wc cut; do
  if ! command -v "$tool" > /dev/null; then
    echo "baseline-comparison: internal: required tool not found: $tool" >&2
    exit 50
  fi
done
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT

# Stop before any comparison. The result says that the comparison did not run.
stop() {
  jq -n --argjson status "$1" --arg category "$2" --arg message "$3" \
    '{result:"failed",category:$category,exit_status:$status,message:$message,
      comparison:"not run"}' > "$result"
  echo "baseline-comparison: $2: $3" >&2
  exit "$1"
}

relative_path() {
  case "$1" in
    ''|/*|..|../*|*/..|*/../*) return 1 ;;
    *) return 0 ;;
  esac
}

# 1. The identity record. It is copied once, and only the copy is used.
relative_path "$record" || stop 20 baseline-record "the record path must stay inside the root: $record"
if [ ! -f "$root/$record" ] || ! cp "$root/$record" "$temporary/record.json" 2> /dev/null; then
  stop 20 baseline-record "the identity record is missing or unreadable: $record"
fi
jq -e '
  (type == "object") and
  (.orb | type == "string") and
  (.version | type == "string") and
  (.expected | type == "object") and
  (.expected.size_bytes | type == "number" and . >= 0 and . == floor) and
  (.expected.sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
  (.stored_copy | type == "object") and
  (.stored_copy.path | type == "string") and
  (.ci_reference.comparison_targets == $ARGS.positional)
' "$temporary/record.json" --args "${targets[@]}" > /dev/null 2>&1 \
  || stop 20 baseline-record "the identity record is not valid JSON, lacks a required value, or names other targets: $record"
copy_path=$(jq -r '.stored_copy.path' "$temporary/record.json")
relative_path "$copy_path" || stop 20 baseline-record "the stored copy path must stay inside the root: $copy_path"

# 2. The stored copy. Its size and SHA-256 are checked before it is parsed.
if [ ! -f "$root/$copy_path" ] || ! cp "$root/$copy_path" "$temporary/baseline.yml" 2> /dev/null; then
  stop 21 baseline-missing "the stored copy is missing or is not a readable regular file: $copy_path"
fi
expected_size=$(jq -r '.expected.size_bytes' "$temporary/record.json")
expected_sha256=$(jq -r '.expected.sha256' "$temporary/record.json")
actual_size=$(wc -c < "$temporary/baseline.yml" | tr -d '[:space:]')
actual_sha256=$(sha256sum < "$temporary/baseline.yml" | cut -d ' ' -f 1)
if [ "$actual_size" != "$expected_size" ]; then
  stop 22 baseline-mismatch "the stored copy has $actual_size bytes; the record expects $expected_size"
fi
if [ "$actual_sha256" != "$expected_sha256" ]; then
  stop 22 baseline-mismatch "the stored copy has SHA-256 $actual_sha256; the record expects $expected_sha256"
fi
jq -e '(.stored_copy.size_bytes == .expected.size_bytes) and (.stored_copy.sha256 == .expected.sha256)' \
  "$temporary/record.json" > /dev/null \
  || stop 22 baseline-mismatch "the record describes its stored copy with values other than the expected ones"

# 3. The packed Orb, read from the archive without changing or repacking it.
if [ ! -f "$archive" ]; then
  stop 30 candidate-archive "the archive is missing: $archive"
fi
if ! tar -xOzf "$archive" ./orb.yml > "$temporary/candidate.yml" 2> /dev/null || [ ! -s "$temporary/candidate.yml" ]; then
  stop 30 candidate-archive "the archive has no readable ./orb.yml: $archive"
fi

# 4. Both sides are parsed by the same commands.
#    <side>.json            the document as JSON
#    <side>.nodes.<n>.json  every node of target n: path, resolved tag, and
#                           whether the node is a mapping key
# Returns 1 when the text cannot be parsed and 2 when a mapping key is repeated.
parse() {
  local side=$1 index expression
  yq -o=json '.' "$temporary/$side.yml" > "$temporary/$side.json" 2> "$temporary/$side.error" || return 1
  jq -e -s 'length == 1 and (.[0] | type == "object")' "$temporary/$side.json" > /dev/null 2>> "$temporary/$side.error" || return 1
  # yq writes a repeated key twice, and jq would keep only the last one.
  jq -c -n --stream '
    [inputs | if length == 2 then .[0] else .[0][:-1] end]
    | group_by(.) | map(select(length > 1) | .[0])
  ' "$temporary/$side.json" > "$temporary/$side.repeated.json" 2>> "$temporary/$side.error" || return 1
  [ "$(cat "$temporary/$side.repeated.json")" = '[]' ] || return 2
  for index in "${!targets[@]}"; do
    # A target that the document does not hold has no node at all.
    if jq -e --arg target "${targets[$index]}" '
      reduce ($target | split("."))[] as $key ({value: ., held: true};
        if .held and (.value | type) == "object" and (.value | has($key))
        then {value: .value[$key], held: true}
        else {value: null, held: false} end)
      | .held' "$temporary/$side.json" > /dev/null 2>> "$temporary/$side.error"; then
      expression="[.${targets[$index]} | ... | {\"p\": path, \"t\": tag, \"key\": is_key}]"
      yq -o=json "$expression" "$temporary/$side.yml" > "$temporary/$side.nodes.$index.json" 2>> "$temporary/$side.error" || return 1
    else
      echo '[]' > "$temporary/$side.nodes.$index.json"
    fi
  done
}

status=0
parse baseline || status=$?
if [ "$status" -ne 0 ]; then
  stop 50 internal "the verified baseline cannot be parsed: $(head -c 400 "$temporary/baseline.error")"
fi
parse candidate || status=$?
if [ "$status" -eq 2 ]; then
  stop 31 candidate-parse "the packed Orb repeats a mapping key, so its meaning depends on the parser: $(cat "$temporary/candidate.repeated.json")"
elif [ "$status" -ne 0 ]; then
  stop 31 candidate-parse "the packed Orb cannot be parsed: $(head -c 400 "$temporary/candidate.error")"
fi

# 5. Compare every node of each target.
read -r -d '' program <<'JQ' || true
def get($document; $path):
  reduce $path[] as $key ($document;
    if type == "object" then .[$key | tostring]
    elif type == "array" and ($key | type) == "number" then .[$key]
    else null end);

# One entry for each node. The entry of a value that is not a mapping or a
# sequence carries its value. An alias has the tag "".
def table($document; $nodes):
  $nodes | map(. as $node | {
    key: ([$node.p, $node.key] | tojson),
    value: {p: $node.p, key: $node.key, t: $node.t,
            v: (if $node.key or $node.t == "!!map" or $node.t == "!!seq" then null
                else get($document; $node.p) end)}
  }) | from_entries;

def show:
  reduce .[] as $key ("";
    if ($key | type) == "number" then . + "[\($key)]"
    elif . == "" then ($key | tostring)
    else . + "." + ($key | tostring) end);

def node: if . == null then null else {tag: .t, value: .v} end;

def differences($baseline; $candidate):
  ([$baseline[], $candidate[]] | map(.p) | unique) as $paths
  | [ $paths[] as $path
      | $baseline[[$path, false] | tojson] as $old
      | $candidate[[$path, false] | tojson] as $new
      | ($baseline[[$path, true] | tojson] | if . == null then null else .t end) as $old_key
      | ($candidate[[$path, true] | tojson] | if . == null then null else .t end) as $new_key
      | if $old != null and $new == null then
          {path: $path, change: "missing", baseline: ($old | node)}
        elif $old == null and $new != null then
          {path: $path, change: "added", candidate: ($new | node)}
        elif ($old | node) != ($new | node) or $old_key != $new_key then
          {path: $path, change: "changed",
           baseline: ($old | node), candidate: ($new | node),
           baseline_key_tag: $old_key, candidate_key_tag: $new_key}
        else empty end ]
  | . as $all
  # Report a missing or added subtree once, at its root.
  | map(select(
      . as $entry
      | .change == "changed" or
        (any($all[];
           .change == $entry.change and
           (.path | length) < ($entry.path | length) and
           .path == $entry.path[:(.path | length)]) | not)))
  | map(.path |= show);

def canonical: [.[]] | sort_by(.p, .key);

[ range(0; $ARGS.positional | length) as $index
  | ($ARGS.positional[$index] | split(".")) as $path
  | table($baseline_document[0]; $baseline_nodes[0][$index]) as $old
  | table($candidate_document[0]; $candidate_nodes[0][$index]) as $new
  | {path: $ARGS.positional[$index],
     baseline_nodes: ($old | length),
     candidate_nodes: ($new | length),
     baseline_listed: ($baseline_nodes[0][$index] | length),
     candidate_listed: ($candidate_nodes[0][$index] | length),
     baseline_root: ($old[[$path, false] | tojson] | node),
     json_equal: (get($baseline_document[0]; $path) == get($candidate_document[0]; $path)),
     baseline_canonical: ($old | canonical),
     candidate_canonical: ($new | canonical),
     differences: differences($old; $new)} ]
JQ
baseline_node_files=()
candidate_node_files=()
for index in "${!targets[@]}"; do
  baseline_node_files+=("$temporary/baseline.nodes.$index.json")
  candidate_node_files+=("$temporary/candidate.nodes.$index.json")
done
jq -s '.' "${baseline_node_files[@]}" > "$temporary/baseline.nodes.json"
jq -s '.' "${candidate_node_files[@]}" > "$temporary/candidate.nodes.json"
jq -n --slurpfile baseline_document "$temporary/baseline.json" \
  --slurpfile candidate_document "$temporary/candidate.json" \
  --slurpfile baseline_nodes "$temporary/baseline.nodes.json" \
  --slurpfile candidate_nodes "$temporary/candidate.nodes.json" \
  "$program" --args "${targets[@]}" > "$temporary/comparison.json" \
  || stop 50 internal "the comparison program failed"

# The check must not pass because a listing is empty or lost a node. The JSON
# equality is a second, independent reading of the same documents.
jq -e '
  all(.[];
    (.baseline_root == {tag: "!!map", value: null}) and
    (.baseline_nodes > 1) and
    (.baseline_nodes == .baseline_listed) and
    (.candidate_nodes == .candidate_listed) and
    ((.differences | length) > 0 or .json_equal))
' "$temporary/comparison.json" > /dev/null \
  || stop 50 internal "the node listing and the JSON reading of the documents disagree"

hash_of() {
  jq -c -S "$1" "$temporary/comparison.json" | sha256sum | cut -d ' ' -f 1
}
hashes='[]'
for index in "${!targets[@]}"; do
  hashes=$(jq -c --arg baseline "$(hash_of ".[$index].baseline_canonical")" \
    --arg candidate "$(hash_of ".[$index].candidate_canonical")" \
    '. + [{baseline: $baseline, candidate: $candidate}]' <<< "$hashes")
done

different=$(jq '[.[].differences | length] | add' "$temporary/comparison.json")
if [ "$different" -eq 0 ]; then
  outcome=passed
  category=equal
  exit_status=0
else
  outcome=failed
  category=difference
  exit_status=40
fi
jq -n --arg outcome "$outcome" --arg category "$category" --argjson status "$exit_status" \
  --slurpfile comparison "$temporary/comparison.json" --slurpfile record "$temporary/record.json" \
  --argjson hashes "$hashes" --arg record_path "$record" \
  --arg record_sha256 "$(sha256sum < "$temporary/record.json" | cut -d ' ' -f 1)" \
  --arg copy_path "$copy_path" --argjson copy_size "$actual_size" --arg copy_sha256 "$actual_sha256" \
  --argjson candidate_size "$(wc -c < "$temporary/candidate.yml" | tr -d '[:space:]')" \
  --arg candidate_sha256 "$(sha256sum < "$temporary/candidate.yml" | cut -d ' ' -f 1)" \
  --arg yq_version "$(yq --version 2>&1 | head -n 1)" --arg jq_version "$(jq --version 2>&1 | head -n 1)" \
  '{result: $outcome, category: $category, exit_status: $status, comparison: "run",
    baseline: {orb: $record[0].orb, version: $record[0].version,
      record: $record_path, record_sha256: $record_sha256,
      stored_copy: $copy_path, size_bytes: $copy_size, sha256: $copy_sha256,
      hash_check: "The size and SHA-256 equalled the expected values of the record before the stored copy was parsed."},
    candidate: {member: "./orb.yml", size_bytes: $candidate_size, sha256: $candidate_sha256},
    parser: {yaml: $yq_version, json: $jq_version,
      schema: "Each side is read twice by the same yq: as JSON (yq -o=json) and as a list of every node with the tag that yq resolved (path, tag, is_key). The comparison uses the tags as resolved; no schema is applied afterwards.",
      same_commands_for_both_sides: true},
    ignored: ["mapping key order", "comments"],
    not_compared_as_text: ["quoting", "block or flow style"],
    targets: [range(0; $comparison[0] | length) as $index | $comparison[0][$index]
      | {path, baseline_nodes, candidate_nodes, json_equal,
         baseline_definition_sha256: $hashes[$index].baseline,
         candidate_definition_sha256: $hashes[$index].candidate,
         differences}],
    definition_sha256_note: "SHA-256 of the sorted node entries of a target (path, key or value, tag, scalar value) as compact JSON with sorted keys and a final newline. It identifies the parsed definition, not the text."}' \
  > "$result"

if [ "$exit_status" -ne 0 ]; then
  {
    echo "baseline-comparison: difference: $different path(s) differ from the published $(jq -r '.orb + "@" + .version' "$temporary/record.json")"
    jq -r '
      def short: tojson | if length > 300 then .[0:300] + "... (" + (length | tostring) + " characters)" else . end;
      # For two long strings, show where they first differ.
      def first_difference:
        if (.baseline.value | type) == "string" and (.candidate.value | type) == "string"
           and ((.baseline.value | length) > 120 or (.candidate.value | length) > 120) then
          (.baseline.value | explode) as $old | (.candidate.value | explode) as $new
          | first(range(0; [($old | length), ($new | length)] | max) | select($old[.] != $new[.])) as $at
          | ([$at - 30, 0] | max) as $from
          | "    first difference at character \($at): baseline \(.baseline.value[$from:($at + 30)] | tojson), candidate \(.candidate.value[$from:($at + 30)] | tojson)"
        else empty end;
      .targets[].differences[]
      | "  \(.change) \(.path)",
        (if .baseline != null then "    baseline:  \(.baseline.tag) \(.baseline.value | short)" else empty end),
        (if .candidate != null then "    candidate: \(.candidate.tag) \(.candidate.value | short)" else empty end),
        (if .change == "changed" then first_difference else empty end),
        (if .change == "changed" and .baseline_key_tag != .candidate_key_tag
         then "    key tag:   \(.baseline_key_tag) -> \(.candidate_key_tag)" else empty end)
    ' "$result"
  } >&2
fi
exit "$exit_status"
