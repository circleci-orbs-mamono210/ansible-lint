# Compile the 2.0.0 list against the verified, published baseline.
# Paths in the list are data. No expression from the list is executed.
def parts:
  if type == "string" and
     test("^[A-Za-z_][A-Za-z0-9_-]*(\\[[0-9]+\\])*(\\.[A-Za-z_][A-Za-z0-9_-]*(\\[[0-9]+\\])*)*$")
  then [scan("[A-Za-z_][A-Za-z0-9_-]*|[0-9]+") |
        if test("^[0-9]+$") then tonumber else . end]
  else error("invalid policy path: \(.)") end;

def state($doc; $path):
  ($doc | getpath($path[:-1])) as $parent
  | if ($parent | type) != "object" then error("expected a mapping at \($path[:-1])")
    elif ($parent | has($path[-1])) then {present:true, value:$parent[$path[-1]]}
    else {present:false} end;

def compile_entry($base; $targets):
  . as $e
  | ($e.element | parts) as $element
  | ($element + ($e.path | parts)) as $p
  | if ($targets | index($e.element)) == null or $e.release_type != "major"
       or ($e.reason | type) != "string" or ($e.reason | length) == 0
       or state($base; $p) != $e.before
    then error("invalid element, release, reason or before value at \($p)") else . end
  | . + {parts:$p}
  | if .change == "missing" and .before.present and .after == {present:false} then .
    elif .change == "added" and .before == {present:false} then
      ($element + (.copy_from_baseline | parts)) as $src
      | state($base; $src) as $source
      | if $source.present and ($source.value | type) == "object" and $source == .after
        then . + {copy_parts:$src}
        else error("new definition differs from its baseline source at \($p)") end
    elif .change == "changed" and (.before.value | type) == "string" and
         (.after.value | type) == "string" and .after == {present:true, value:.after.value}
         and .before != .after then .
    else error("invalid presence, value or change type at \($p)") end;

. as $base | $record[0] as $r | $list[0] as $l
| if ($list | length) != 1 or $l.baseline != ($r.orb + "@" + $r.version)
     or $l.target != ($r.orb + "@2.0.0") or $l.baseline_source != $r.stored_copy.path
     or ($l.differences | type) != "array"
  then error("expected one difference list for this baseline and 2.0.0") else . end
| [$l.differences[] | compile_entry($base; $r.ci_reference.comparison_targets)] as $rows
| if ($rows | map(.change) | sort) != ["added","added","changed","changed","missing","missing"]
     or ($rows | unique_by(.parts) | length) != 6
  then error("expected six distinct paths: two removals, two additions and two references")
  else . end
| if ($rows | map(select(.change == "missing").parts) | sort) !=
     ($rows | map(select(.change == "added").copy_parts) | sort)
  then error("each new definition must copy one removed definition") else . end
| (reduce ["executors","commands","jobs"][] as $k ({};
     .[$k] = (if ($base | has($k)) then ($base[$k] | keys) else [] end))) as $names
| [$names | to_entries[] | .key as $kind | .value[] | $kind + "." + .] as $targets
| if $names != $r.ci_reference.public_names or ($targets | sort) != ($r.ci_reference.comparison_targets | sort)
  then error("identity record disagrees with baseline public names")
  else {entries:$rows, public_names:$names} end
