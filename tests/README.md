# Integration tests for issue #5501

All six CircleCI jobs use the public `ansible-lint/execute` from the same commit's
packed Orb, injected by orb-tools 12.5.0. Only production publish receives
`CIRCLECI_ORBS`. No test needs a dev publish or publishing token.

| Job | Local input | Public parameters | Required observation |
| --- | --- | --- | --- |
| `normal-test` | `tests/fixtures/normal/playbook.yml` | Both default to false | Exactly one Ansible file processed, zero failures/warnings, exit 0; no dependency install |
| `role-test` | `test_resources/` | `molecule-role-test: true` | Install this repository at `CIRCLE_SHA1`, then the fixed Molecule dependency; lint succeeds |
| `playbook-test` | `tests/fixtures/playbook/` | `molecule-playbook-test: true` | Install both requirements files, verify both distinct role names/revisions; lint succeeds |
| `negative-test` | `tests/fixtures/negative/playbook.yml` | Both default to false | Real exit 2, exactly one `name[missing]` at `playbook.yml:6`; only the separately recorded notices below may accompany it |
| `resource-class-test` | Playbook fixture | Playbook flag, executor `resource_class: medium` | Same dependency assertions and successful lint in the explicit resource class |
| `custom-image-test` | Playbook fixture | Playbook flag, explicit separate image digest | Required executables/versions, both dependency installs and successful lint |

Checkout is kept at `/tmp/ansible-lint-orb-source`; each job copies only its fixture
into an initially empty `/tmp/ansible-lint-case`. The normal and negative cases
contain only `playbook.yml`, with no `molecule/`, role requirements or inherited
repository lint configuration. The existing role fixture uses lowercase `true`
so it also passes without the repository-level `truthy: disable` setting.
The playbook test no longer clones an external WordPress repository.

The playbook fixture carries `.ansible-lint` with `project_dir: .`. This keeps
its lint project/cache rooted at the fixture even when CI runs outside a Git
checkout. Without a marker, ansible-lint discovers the filesystem root and may
lint external installed roles as project input. Dependency installation, version
checks and Ansible syntax loading remain enabled; no lint rule is skipped.
Setup checks the discovered playbook project root before execute.

## Dependency observations

`integration-test.py` wraps `ansible-galaxy` only inside the test job, forwards its
arguments/environment/status unchanged and records its calls. Required install
calls must precede the final linter invocation. The linter's read-only
`collection list --format=json` query is distinguished from installation.
Installed `.galaxy_install_info` versions and actual Git archive revisions are
checked. Both playbook dependency aliases point to the fixed epel commit
`747af654d2a2e05c1cfabce9c0b79b2a1eae3650`; using two names proves both paths.
The role case additionally checks the current repository's archive at the actual
`CIRCLE_SHA1`. GitHub/network availability remains a dependency.

Positive tests capture the real linter without changing its arguments or
return code. They require one `--version` and one no-argument lint call, successful
statuses, and a nonzero processed-file count. Normal use requires exactly one
processed/encountered file. This supplements the public execute step's success.

## Negative observer and self-tests

`negative-test.py prepare` resolves the real executable before adding its wrapper
to PATH through `BASH_ENV`. Every job gets a new evidence directory/run identifier.
The real executable inherits the caller's environment; the observer adds no
linter options or output-format/lint environment overrides. Version requests are
forwarded with their status; unexpected arguments fail. The no-argument call
records raw stdout/stderr/status. Only the exact expected exit and complete
output in `negative-expected.json` produce wrapper exit 0.

The expected real result for the pinned default image is exit 2 and one
`name[missing]` violation on line 6 of `playbook.yml`. Every nonblank output line
must match the expected multiset for its stream. The stdout lines identify the
rule, message, file, line and task. The stderr lines are the fatal-count notice,
ignore-documentation hint, summary heading, one rule-count row and exact final
failure/file/profile summary. The exact two-line Python 3.14.10 HTTP-304 cleanup warning observed in CI #454
is separately classified when present once. ansible-lint's schema updater treats
HTTP 304 as unchanged; Python warns while closing that response during garbage
collection. The original output is retained and `verification.json` records the
notice ID, count and text.

CI [#492](https://circleci.com/gh/circleci-orbs-mamono210/ansible-lint/492), on
`85d8f99fa76ad792b99b909736a37c717c9766a3`, retained the same fixture, real exit 2
and one expected finding, but also emitted two additional stderr lines:

- `<unknown>:1: SyntaxWarning: invalid decimal literal`. Only that exact line
  is classified, at most once, alongside the complete expected lint result.
  Its internal emitting call site has not been established; a local run using
  extracted image Python/packages did not reproduce it. This narrow observation
  does not establish that SyntaxWarning generally is harmless.
- The ansible-lint new-release announcement. The observer accepts only the known
  complete format, from the measured `26.10.1` to a newer numeric stable version,
  with the exact `pip3 install --user --upgrade ansible-lint` instruction.
  This records a notice; it never executes that instruction or changes the image.
  A pinned binary can query the latest-release service, so notification text can
  change while the image digest remains fixed.

Each of these three notices is independently optional and recorded with its ID,
count and original normalized text. Every required lint-summary line remains
mandatory. Other HTTP statuses, warning locations/messages, partial/repeated
notices, multiple release announcements, extra errors or files are rejected.
No warning suppression or linter argument/environment change is used.
Only ANSI SGR colours, OSC-8 hyperlink delimiters, blank lines, surrounding
whitespace and display order are normalized. Unknown terminal controls fail.
Counts are retained, so duplicate violations cannot disappear during comparison.

The following step rechecks the raw outputs and demands exactly one version call
and one no-argument lint call, completed records and the current run identifier.
Missing, incomplete, stale or additional invocations fail.

The negative job first runs `.circleci/test-negative-test.py` against these same
implementation files in child processes, substituting only a controlled linter
stub. It verifies unexpected success, other exit codes, incorrect/mixed/unknown
output, missing records and additional calls, plus a passing control and version
status propagation. Stub results are not real-linter evidence.

The real negative run's final CircleCI step succeeds because the observer accepts
the expected failure. It does **not** observe a failed CircleCI step. Product exit
propagation is checked separately in the packed output below. Public `src/` stays
unchanged by this ticket.

## Actual packed output and publish gates

Both setup and continuation `orb-tools/pack` jobs run
`.circleci/verify-packed-orb.sh` in `post-steps`. With orb-tools 12.5.0 the persisted
output is `dist/orb_source.tar.gz`; the original `dist/orb.yml` has been archived
and removed. The check reads `./orb.yml` from that exact archive without changing
it. It does not repack source or reuse another workflow's workspace.

The final execute step must contain only `run`; its attributes may only be
`command` and optional string `name`. Command must be exactly `ansible-lint`.
Pipelines, status masking, background/environment/when/shell/other attributes are
rejected. The check records source commit/tree, archive/packed-file SHA-256,
purpose and job URL. Setup continue requires the successful setup pack. Production
publish requires its own successful pack plus all six integration jobs, including
the negative observer's self-tests. All prerequisite jobs accept tags; production
publish accepts only semantic version tags and excludes all branches.

## Baseline comparison of the existing API (#5538)

Both `orb-tools/pack` jobs also compare the actual packed Orb with the
published `orbss/ansible-lint@1.0.0`. The rule is section 5 of
[the contract](../docs/python-install-contract.md): in 1.1.0,
`executors.default` and `commands.execute` must not differ from 1.0.0. This
check covers the existing API only. It does not show that the new path works.

| File | Role |
| --- | --- |
| `.circleci/compare-baseline.sh` | The comparison. It checks the baseline, reads `./orb.yml` from an archive, and compares both targets. |
| `.circleci/verify-packed-baseline.sh` | Runs the comparison for the actual archive of a pack job and writes the evidence. |
| `.circleci/test-compare-baseline.sh` | Self-test. It runs the same `compare-baseline.sh` with isolated inputs. |

The post-steps of each pack job run in this order. A failed step ends the job.

1. `verify-packed-orb.sh`: the exit-code check of #5501, unchanged.
2. `test-compare-baseline.sh`: the self-test, with the tools of this job.
3. `verify-packed-baseline.sh`: the comparison of the actual archive.
4. `verify-packed-install.sh`: the install check of #5537, unchanged.

### Baseline check before every comparison

The comparison reads the identity record
`tests/baseline/orbss-ansible-lint-1.0.0.json` and the stored copy that it
names from the checkout of the candidate commit. Nothing is downloaded. Each
run first checks the size and SHA-256 of the stored copy against the expected
values of the record. Only a copy that passed is parsed.

The comparison does not run, and the step fails, when:

- the record is missing, is not JSON, lacks a required value, or names
  targets other than `executors.default` and `commands.execute`;
- the stored copy is missing, is not a regular file, or cannot be read;
- the size or SHA-256 differs from the expected value.

No script writes to `tests/baseline/`, changes an expected value, or repacks
`src/` as a substitute.

Limit: CI trusts the record of the candidate commit. If one commit changed
the stored copy and the expected values together, this check alone would not
see it. Such a change is a contract change (contract section 5.3, item 5).
To make it visible, the evidence records the SHA-256 of the record and of the
stored copy and their Git blob IDs. #5541 compares the baseline SHA-256 with
design principle 1 of `110_ロードマップ`.

### What is compared

Both sides are read by the same commands of the same `yq` and `jq` in the same
job: once as JSON (`yq -o=json`) and once as a list of every node with the tag
that `yq` resolved. The evidence records the versions of both tools, and each
step prints them first.

The pack jobs run in `circleci/circleci-cli:latest`, the default image of
orb-tools 12.5.0. Its tools are older than those of a current `cimg/base`:
in the CI run of commit `9003e4d`, its `yq` rejected the `kind` operator. The
comparison therefore uses only `path`, `tag`, `is_key`, and `...`. It was
tested locally with yq 4.30.6, 4.31.2, 4.42.1, and 4.54.3 and with jq 1.6 and
1.7.1. A local test is not the image; the versions that count are those in
the evidence of the job.

For every node of the two targets, the comparison requires the same path, the
same resolved tag, and the same scalar value. This covers the set of keys,
sequence order and length, scalar types such as boolean `false` against
string `"false"`, and every character of descriptions, defaults, enum values,
step names, environment values, the embedded script, and the default image
digest.

Ignored: mapping key order and comments. Quoting and block or flow style
disappear when YAML is parsed, so they are not compared as text.

Converting YAML to JSON loses some information. The comparison therefore also
rejects the following, which a plain JSON comparison would accept. The
baseline has none of them.

- A repeated mapping key anywhere in the packed Orb. Parsers disagree on its
  meaning. Exit status 31.
- An alias, an explicit tag, or a mapping key that is not a plain string
  inside a target. Reported as a difference, exit status 40.

Not compared: the Orb description, `display`, examples, and the new elements.
The hash of the whole Orb is not required to match.

A failed comparison prints every differing path with both values. A missing
or added subtree is reported once, at its root.

| Exit status | Category | Meaning |
| --- | --- | --- |
| 0 | `equal` | Both targets equal the baseline. |
| 20 | `baseline-record` | The identity record cannot be used. |
| 21 | `baseline-missing` | The stored copy is missing or cannot be read. |
| 22 | `baseline-mismatch` | Size or SHA-256 is not the expected value. |
| 30 | `candidate-archive` | The archive or its `./orb.yml` cannot be read. |
| 31 | `candidate-parse` | The packed Orb cannot be parsed, or repeats a mapping key. |
| 40 | `difference` | A target differs from the baseline. |
| 50 | `internal` | The check itself cannot work. |

### Self-test

`test-compare-baseline.sh` gives every case its own temporary directory with a
copy of the identity record, a copy of the stored baseline, and an archive in
the layout of orb-tools (`./` and `./orb.yml`). It changes one of them for the
case and runs the comparison. It never changes `src/` or `tests/baseline/`
and checks at the end that the baseline files of the repository are unchanged.

A case passes only when the comparison ends with the expected exit status and
category, and reports exactly the expected differing paths. The packed Orb of
a case is the baseline with one change. Changes are made in two ways: by
replacing text in the YAML, or by changing the parsed document and writing it
as JSON. Case A02 shows that the JSON form alone is accepted.

Accepted (exit status 0, no differing path):

| Case | Target or changed input | Input for the case | Expected exit status |
| --- | --- | --- | --- |
| A01 | both | the packed Orb has the same bytes as the baseline | 0 |
| A02 | both | every mapping lists its keys in reverse order; written as JSON (flow style, quoted strings) | 0 |
| A03 | both | block-style text with only the order of mapping keys changed in both targets | 0 |
| A04 | both | comment lines and trailing comments added inside both targets | 0 |
| A05 | both | only the quoting of two string scalars changed in the block-style text | 0 |
| A06 | both | new executor and command added; Orb description, display and examples changed | 0 |

The baseline cannot be used (the comparison must not run). In B15 the packed
Orb also differs, and the result must still be 22, not 40.

| Case | Target or changed input | Input for the case | Expected exit status |
| --- | --- | --- | --- |
| B01 | record | the identity record is missing | 20 |
| B02 | record | the identity record is not JSON | 20 |
| B03 | record | the identity record has no expected SHA-256 | 20 |
| B04 | record | the identity record names only one of the two targets | 20 |
| B05 | record | the identity record points to a stored copy outside the root | 20 |
| B06 | stored copy | the stored copy is missing | 21 |
| B07 | stored copy | the stored copy is a directory, not a regular file | 21 |
| B08 | stored copy | the stored copy cannot be read (no read permission) | 21 |
| B09 | stored copy | one character of the stored copy is changed; the size is the same | 22 |
| B10 | stored copy | a newline is added at the end of the stored copy | 22 |
| B11 | stored copy | the stored copy is empty | 22 |
| B12 | record | one digit of the expected SHA-256 is changed | 22 |
| B13 | record | the expected size is changed by one byte | 22 |
| B14 | record | the record describes its stored copy with another SHA-256 than the expected one | 22 |
| B15 | stored copy | the stored copy is changed and the packed Orb differs; the hash check must end the check first | 22 |

B08 needs a user other than root. In CI a skipped case fails the self-test.

The packed Orb cannot be read as one unambiguous document (the comparison
must not run):

| Case | Target or changed input | Input for the case | Expected exit status |
| --- | --- | --- | --- |
| P01 | archive | the archive is missing | 30 |
| P02 | archive | the archive holds no ./orb.yml | 30 |
| P03 | archive | ./orb.yml is empty | 30 |
| P04 | document | ./orb.yml is not YAML | 31 |
| P05 | document | ./orb.yml holds two documents | 31 |
| P06 | document | the top level of ./orb.yml is a sequence | 31 |
| P07 | document | a mapping key is repeated; the last value equals the baseline | 31 |

A target differs (exit status 40). Cases E are `executors.default`, cases X
are `commands.execute`, and cases Y keep the JSON value but change the YAML
node.

| Case | Target | Input for the case | Expected exit status | Expected differing paths |
| --- | --- | --- | --- | --- |
| E01 | executors.default | description: one character added | 40 | `executors.default.description` |
| E02 | executors.default | docker image expression: spaces added inside << >> | 40 | `executors.default.docker[0].image` |
| E03 | executors.default | docker sequence: a second image added | 40 | `executors.default.docker[1]` |
| E04 | executors.default | default GHCR digest: one hexadecimal digit changed | 40 | `executors.default.parameters.image.default` |
| E05 | executors.default | default GHCR image: a tag in place of the digest | 40 | `executors.default.parameters.image.default` |
| E06 | executors.default | parameter type: string changed to enum | 40 | `executors.default.parameters.image.type` |
| E07 | executors.default | parameter description: block scalar \| changed to \|- (final newline removed) | 40 | `executors.default.parameters.image.description` |
| E08 | executors.default | parameter default: small changed to medium | 40 | `executors.default.parameters.resource_class.default` |
| E09 | executors.default | enum order: the first two values swapped | 40 | `executors.default.parameters.resource_class.enum[0]`<br>`executors.default.parameters.resource_class.enum[1]` |
| E10 | executors.default | enum: a value added at the end | 40 | `executors.default.parameters.resource_class.enum[4]` |
| E11 | executors.default | enum: the last value removed | 40 | `executors.default.parameters.resource_class.enum[3]` |
| E12 | executors.default | parameters: a parameter added | 40 | `executors.default.parameters.tag` |
| E13 | executors.default | parameters: a parameter removed | 40 | `executors.default.parameters.resource_class` |
| E14 | executors.default | resource_class: the parameter reference replaced by a fixed value | 40 | `executors.default.resource_class` |
| E15 | executors.default | a key added to the executor | 40 | `executors.default.environment` |
| E16 | executors.default | the executor is removed | 40 | `executors.default` |
| X01 | commands.execute | description: the final newline removed | 40 | `commands.execute.description` |
| X02 | commands.execute | parameter default: false changed to true | 40 | `commands.execute.parameters.molecule-role-test.default` |
| X03 | commands.execute | scalar type: boolean false changed to the string "false" in the text | 40 | `commands.execute.parameters.molecule-playbook-test.default` |
| X04 | commands.execute | parameter type: boolean changed to string | 40 | `commands.execute.parameters.molecule-role-test.type` |
| X05 | commands.execute | parameter description: one character removed | 40 | `commands.execute.parameters.molecule-role-test.description` |
| X06 | commands.execute | parameter name: molecule-role-test renamed to molecule_role_test | 40 | `commands.execute.parameters.molecule-role-test`<br>`commands.execute.parameters.molecule_role_test` |
| X07 | commands.execute | parameters: a parameter added | 40 | `commands.execute.parameters.config` |
| X08 | commands.execute | step order: the first two steps swapped | 40 | `commands.execute.steps[0].run.command`<br>`commands.execute.steps[0].run.name`<br>`commands.execute.steps[1].run.command`<br>`commands.execute.steps[1].run.name` |
| X09 | commands.execute | steps: the second step removed | 40 | `commands.execute.steps[1].run.command`<br>`commands.execute.steps[1].run.environment`<br>`commands.execute.steps[1].run.name`<br>`commands.execute.steps[2].run.command`<br>`commands.execute.steps[2].run.environment`<br>`commands.execute.steps[2].run.name`<br>`commands.execute.steps[3]` |
| X10 | commands.execute | steps: a step added at the end | 40 | `commands.execute.steps[4]` |
| X11 | commands.execute | step name changed | 40 | `commands.execute.steps[0].run.name` |
| X12 | commands.execute | embedded script: one character changed | 40 | `commands.execute.steps[2].run.command` |
| X13 | commands.execute | embedded script: the final newline removed | 40 | `commands.execute.steps[2].run.command` |
| X14 | commands.execute | embedded script: a space added at the end of one line | 40 | `commands.execute.steps[2].run.command` |
| X15 | commands.execute | environment value: spaces removed inside << >> | 40 | `commands.execute.steps[2].run.environment.PARAM_MOLECULE_ROLE_TEST` |
| X16 | commands.execute | environment: a variable added | 40 | `commands.execute.steps[2].run.environment.EXTRA` |
| X17 | commands.execute | final command: ansible-lint changed to ansible-lint \|\| true | 40 | `commands.execute.steps[3].run.command` |
| X18 | commands.execute | final step: the attribute when added | 40 | `commands.execute.steps[3].run.when` |
| X19 | commands.execute | first step: a run step replaced by checkout | 40 | `commands.execute.steps[0]`<br>`commands.execute.steps[0].run` |
| X20 | commands.execute | the command is removed | 40 | `commands.execute` |
| X21 | commands.execute | description: the value removed in the text, which leaves null | 40 | `commands.execute.description` |
| X22 | commands.execute | scalar type: boolean false changed to the number 0 | 40 | `commands.execute.parameters.molecule-role-test.default` |
| Y01 | executors.default | an explicit tag added to an unchanged scalar | 40 | `executors.default.parameters.image.type` |
| Y02 | executors.default | an enum value replaced by an alias of an equal value | 40 | `executors.default.parameters.resource_class.enum[0]` |
| Y03 | executors.default | an explicit tag added to an unchanged mapping key | 40 | `executors.default.description` |
| Y04 | commands.execute | boolean false written as the YAML 1.1 word no, which this parser reads as a string | 40 | `commands.execute.parameters.molecule-playbook-test.default` |

The self-test uses inputs made for the test. It shows that the comparison
detects these differences. It is not evidence about the real packed Orb;
step 3 above is.

### Evidence and gates

Both pack jobs store these files in the artifact `packed-orb-structure`, next
to the files of the other pack checks (`<purpose>` is `injection` or
`publication`):

| File | Content |
| --- | --- |
| `baseline-self-test-<purpose>.json` | Every case with its input, expected result, and actual result; tool versions; SHA-256 of the tested `compare-baseline.sh` |
| `baseline-<purpose>.json` | Commit, source tree, archive and packed-file SHA-256, baseline SHA-256 and Git blob IDs, tool versions, node counts, and a definition SHA-256 of each target on both sides; SHA-256 of the `compare-baseline.sh` that ran |

The two files of one job must name the same `comparison_sha256`. The
definition SHA-256 identifies the parsed definition of a target, not its text.

The checks are post-steps of the existing pack jobs, so the existing gates
apply without a new job or a new `requires` entry. `orb-tools/continue`
requires the setup pack, and production publish requires the continuation
pack. Tag and branch filters are unchanged. No dev publish, publishing
context, or token is added.

The final release candidate repeats the comparison (#5541). Results from
another commit are not reused.

## Images and comparison scope

The default image/version record remains `image-lock.json`. Its recorded
comparison image and selected image have the same manifest digest and
`linux/amd64` platform. `image-comparison.json` records why an additional
image-difference comparison is omitted, using the public 0.0.3 source comparison
from #5500 / journal 11078. Setup checks these identities remain consistent.
This does not reconstruct historical 0.0.3 runtime images, re-resolve `latest`,
or omit the six regressions/public API source comparison.

`custom-image-lock.json` identifies a different verified image for the explicit
image-parameter test: Python 3.14.3, Ansible package 13.4.0, ansible-core 2.20.3,
ansible-lint 26.1.1 on linux/amd64. Its exact digest is set in the CI job.
The version record initially comes from verified extracted image userspace;
the job validates it inside the actual container and records the output. Match
its configured reference to the same job's Spin up environment log before
claiming container identity; configuration alone is not that evidence.

## Evidence and handoff

Each integration job stores `image-and-repository-evidence` and
`integration-evidence`; the negative job also stores `negative-evidence` and its
self-test log. Both pack jobs store `packed-orb-structure`. Record the candidate
commit, job URLs/results, actual image references/platforms, fixture hashes,
installed revisions and both pack checks after the candidate is pushed.

#5502 uses the image comparison scope, local-input migration and test results in
README/CHANGELOG. #5503 verifies the same commit and all gates in the release
candidate/tag pipelines. Documentation of this test design is not a completed
CircleCI run, a Redmine handoff registration or production publication.
