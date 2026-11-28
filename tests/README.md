# Ansible lint Orb integration tests

The six default-executor jobs below use the public `ansible-lint/execute` from the same commit's
packed Orb, injected by orb-tools 12.5.0. Only production publish receives
`CIRCLECI_ORBS`. No test needs a dev publish or publishing token.

| Job | Local input | Public parameters | Required observation |
| --- | --- | --- | --- |
| `normal-test` | `tests/fixtures/normal/playbook.yml` | Both default to false | Exactly one Ansible file processed, zero failures/warnings, exit 0; no dependency install |
| `role-test` | `test_resources/` | `molecule_role_test: true` | Install this repository at `CIRCLE_SHA1`, then the fixed Molecule dependency; lint succeeds |
| `playbook-test` | `tests/fixtures/playbook/` | `molecule_playbook_test: true` | Install both requirements files, verify both distinct role names/revisions; lint succeeds |
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

## Compile-time checks for the 2.0.0 execute parameters (#5555)

In the `test-deploy` workflow, `validate-execute-config` waits for
`orb-tools/pack` and attaches its workspace. It checks the SHA-256 of
`orb_source.tar.gz` and its `./orb.yml` member against that job's successful
`baseline-publication.json`, including the full candidate commit and pipeline
ID. It parses the member once and embeds its contents under
`orbs.ansible-lint` in each of six independent consumer configs.
Each config has the same `verify` workflow, `consumer` job, default executor,
checkout and `ansible-lint/execute` step. Each supplied argument is true.

| Input artifact | Arguments to `execute` | Expected compiler result |
| --- | --- | --- |
| `role.yml` | `molecule_role_test` | Accepted |
| `playbook.yml` | `molecule_playbook_test` | Accepted |
| `both.yml` | `molecule_role_test`, `molecule_playbook_test` | Accepted |
| `omitted.yml` | Both omitted | Accepted |
| `legacy-role.yml` | `molecule-role-test` | `Unexpected argument(s): molecule-role-test` |
| `legacy-playbook.yml` | `molecule-playbook-test` | `Unexpected argument(s): molecule-playbook-test` |

Each legacy input changes only the spelling of the key in its matching
single-argument positive. The job sends each config to CircleCI's
`POST /api/v3/configs/compile` using anonymous HTTPS. The request supplies
only the config. It compiles the consumer workflow without running its steps.
Both repository jobs run without a context. They use no additional credential
and perform no dev publish.

All four accepted results must include the referenced consumer job, its
expanded run steps and both resolved flag values (omitted flags default to
false). For each legacy input the compiler must report one error
through `verify`, `consumer` and `ansible-lint/execute`, ending with the exact
diagnostic in the table. An accepted legacy key, wrong or additional error,
authentication or transport failure, missing workflow reference, or unprocessed
case fails the job. Inputs and successful expansions are stored under
`execute-config-evidence`. Its `execute-config-summary.json` records per-case
outcomes and diagnostics, input hashes, the pack and validation job URLs,
archive and member hashes, candidate SHA, pipeline ID and authentication mode.
Use that SHA and pipeline ID to locate the setup pack's
`packed-orb-structure/baseline-injection.json` and the continuation pack's
`packed-orb-structure/baseline-publication.json`.

`verify-execute-config-evidence` requires `validate-execute-config` to succeed.
It reads the summary from the same workflow workspace, checks all six outcomes
and the commit and pipeline ID, then logs the upstream and downstream job URLs.
The production publish dependency is tracked separately in #5557.

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
propagation is checked separately in the packed output below.

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
publish requires its own successful pack and the six default-path and fourteen
additional integration jobs, including the negative observer's self-tests. All prerequisite jobs accept tags; production
publish accepts only semantic version tags and excludes all branches.

## v2.0.0 pack jobs and continuation (#5554)

Both pack jobs run the following post-steps in order on their own
`dist/orb_source.tar.gz`. The candidate is the full `CIRCLE_SHA1` checked out
by the job.

1. `verify-packed-orb.sh` checks the final lint command in `./orb.yml`.
2. `test-compare-baseline.sh` runs the 2.0.0 suite from that checkout.
   Every case must pass, including the negative cases. A skipped case fails CI.
3. The very next run step calls `verify-packed-baseline.sh`. It verifies the
   self-test report's release, purpose, commit, job URL and script hashes,
   then calls the tested comparator on this job's archive. The identity record
   selects the published 1.1.0 source and the six differences adopted in #5552.
   The stored size and SHA-256, all four definitions, all six changes and the
   public executor, command and job name sets must match.
4. `verify-packed-install.sh` checks the packed install command and Python image.

| Purpose | Pack job and consumer | Evidence in the job's `packed-orb-structure` artifacts |
| --- | --- | --- |
| `injection` | In `lint-pack`, `orb-tools/continue` requires the setup pack. It injects that pack as `ansible-lint` into `.circleci/test-deploy.yml` and starts `test-deploy`. | `baseline-self-test-2.0.0-injection.json` and `baseline-injection.json` |
| `publication` | In `test-deploy`, the second pack builds its own archive. Production publish requires this pack and the integration jobs and runs on release tags. | `baseline-self-test-2.0.0-publication.json` and `baseline-publication.json` |

For the #5555 and #5557 handoff, match `pipeline_id` and the full `commit`
across the two pack reports. Each `job_url` identifies its own run. In each
report, `self_test.file` and `self_test.report_sha256` identify the preceding
suite result, `candidate.sha256` identifies the actual `./orb.yml`, and
`archive_sha256` identifies its tarball. A passing real comparison has
`category` equal to `adopted-differences`. The accepted changes, public
names and hashes of the baseline and adopted list are retained in the report.
The pipeline's successful `orb-tools/continue` job and the started
`test-deploy` workflow are the evidence of continuation.

The regular continuation calls `ansible-lint/execute` directly or through
its internal `python-path` command. Both use the public names
`molecule_role_test` and `molecule_playbook_test`. The wrapper declares two
boolean parameters with default `false` and forwards each to the matching
public parameter. The role and playbook jobs below show the individual flags.
The old names belong to the 1.1.0 source and examples for that release, the
migration mapping, and inputs that exercise removal or rejection of an old
key. Ticket #5555 covers the configuration-processing tests, and #5556
covers the consumer README, changelog and public examples.

## Historical v1.1.0 baseline comparison (#5538)

This section records the v1.1.0 checks and file names. For that release,
both `orb-tools/pack` jobs compared the actual packed Orb with the
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

### v1.1.0 self-test against v1.0.0

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

## v2.0.0 public API comparison (#5553)

The input to the comparison is the `./orb.yml` member of an Orb source archive.
The 1.1.0 identity record selects the policy adopted in #5552, journal 11411.
Both the record and its two referenced files come from the candidate checkout.
The comparison verifies the stored source's size and SHA-256 before parsing it.
The list supplies the element, path, change type and before/after states.
Each new parameter takes the full definition of the old one, including YAML
tags, child keys and description whitespace. A missing key has a different
state from a present key with a null value. Each candidate reference must
match the listed string including its spaces. Section 23 of the contract
defines the required public name sets for each pack.

Run the v2.0.0 suite from the repository root.

```sh
bash .circleci/test-compare-baseline.sh local /tmp/ansible-lint-pack-evidence 2.0.0
```

This reads the published source and builds a positive fixture by renaming
the two parameter keys and rewriting their two references. It constructs
the fixture independently of the difference list. Each case copies the
inputs to a fresh directory and invokes the same four-argument comparator
that accepts an actual archive.

```sh
bash .circleci/compare-baseline.sh . tests/baseline/orbss-ansible-lint-1.1.0.json \
  "$archive" "$result_json"
```

`$archive` names the input tar.gz and `$result_json` names the output file.
The v1.1.0 self-test is still the default when the third argument is omitted.
Both pack jobs explicitly select 2.0.0 and compare against the 1.1.0 identity record.

### Inputs and expected results

All candidate mutations below start from the six-change positive fixture.
Paths abbreviated to `P` or `E` refer to `commands.execute.parameters` or
`commands.execute.steps[2].run.environment`, respectively. In paired cases
`K` is `role` or `playbook`, and `ENV` is the corresponding
`PARAM_MOLECULE_ROLE_TEST` or `PARAM_MOLECULE_PLAYBOOK_TEST`.

| Case | Input | Expected result or mismatch path |
| --- | --- | --- |
| A01 | Apply only the two renames and the two reference updates. | Exit 0. Four definitions, six actual differences with matching before/after states and all three name sets. |
| A02 | Reorder mapping keys, use flow style, add a comment, change Orb metadata/examples and express the zero public jobs as an empty mapping. | Same result as A01. |
| B01 / B02 | Remove the baseline source / make it unreadable. B01 also has invalid candidate YAML. | Exit 21, `baseline-missing`. The message identifies the missing file or read failure. B02 requires a non-root user. |
| B03 / B04 | Append a newline / change a byte without changing the file size. B03 also has invalid candidate YAML. | Exit 22, `baseline-mismatch`. The message identifies the size or SHA-256 failure before candidate parsing. |
| L01 / L02 | Remove the list / replace one row with a duplicate. | Exit 23, `expected-differences`. |
| L03 / L04 | In the list, copy the other old definition for the new role key / give the wrong before value for a reference. | Exit 23 for a list inconsistent with the verified source. |
| L05 | Change only the expected role reference in the test copy of the list. | Exit 40 at `E.PARAM_MOLECULE_ROLE_TEST`. |
| D01 | Omit the role reference update. | `E.PARAM_MOLECULE_ROLE_TEST` |
| D02 | Also change the command description. | `commands.execute.description` |
| D03 | Swap the two new environment references. | Both `E.PARAM_MOLECULE_ROLE_TEST` and `E.PARAM_MOLECULE_PLAYBOOK_TEST` |
| W-role / W-playbook | Remove just the spaces in one reference, e.g. `<<parameters.molecule_role_test>>`. | `E.ENV` for the changed side |
| N-role / N-playbook | Leave one old key present with YAML `null`. | `P.molecule-K-test` |
| B-role / B-playbook | Set one new default to boolean `true`. | `P.molecule_K_test.default` |
| S-role / S-playbook | Set one new default to the string `"false"`. | `P.molecule_K_test.default` |
| T-role / T-playbook | Change one new parameter's description. | `P.molecule_K_test.description` |
| D04 / D05 | Add a child to the new role definition / give its default a custom YAML tag. | `P.molecule_role_test.extra` / `P.molecule_role_test.default` |
| E01 | Swap the first two resource class enum values in the default executor. | `executors.default.parameters.resource_class.enum[0]` and `[1]` |
| E02 | Change the python executor's pinned image. | `executors.python.parameters.image.default` |
| E03 | Remove the final newline from the embedded install script. | `commands.install.steps[0].run.command` |
| A-executors / A-commands | Copy a definition to a new public name in its kind. | Added name `executors.extra` / `commands.extra` |
| M-executors / M-commands | Remove the python executor / install command. | Missing name and definition `executors.python` / `commands.install` |
| R-executors / R-commands | Move that definition to `extra` in the same kind. | Both the missing and added names, plus the missing original definition |
| J01 | Add `jobs.extra` while all four definitions and six approved differences remain correct. | Added public name `jobs.extra` |
| J02 | Supply a sequence for the jobs section. | Invalid kind `jobs` |

Every candidate mismatch in the table returns exit 40. A missing or
unreadable identity record returns 20. The self-test writes
`baseline-self-test-2.0.0-<purpose>.json` to the requested evidence directory.
It checks the exact paths for each case. In the self-test results a `names.`
prefix distinguishes membership diagnostics from definition paths.

In the comparator result, `targets[].differences` compares the candidate
with the published source. `targets[].listed_differences_match` records whether
the observed paths, change types and full before/after states match the list
for that element. `targets[].mismatches` compares the candidate with the
expected result of applying the list. In each mismatch, `baseline` describes
the expected YAML node and `candidate` describes the observed node.
`public_names` reports both sets and added/missing names by kind.
`expected_differences` identifies the list by path, SHA-256 and entry count.
`policy_sha256` identifies the copy of `.circleci/baseline-policy.jq` used.
A positive result has category `adopted-differences`.

## Required checks of the new path (#5539)

The new path is the `python` executor, then `ansible-lint/install`, then
`ansible-lint/execute`. #5536 and #5537 each left one minimal job on `main`.
#5539 keeps both jobs with their conditions and adds twelve jobs.

- All fourteen jobs use this commit's packed Orb through inline injection.
- None needs a publishing context or token, and no dev publish is added.
- Production publish requires all fourteen, next to the six jobs of the
  existing path and the pack checks. The filters are the existing ones.
- The six jobs of the existing path, their fixtures, expected values, and
  accepted notices are unchanged. None of them calls `install`.
- These repository tests use the public parameters of `execute`.

### Jobs

Every job checks the repository out to `/tmp/ansible-lint-orb-source` and
copies only its fixture into the empty working directory
`/tmp/ansible-lint-case`, as the jobs of the existing path do.

| Job | Environment | Input and parameters | What the job shows |
| --- | --- | --- | --- |
| `python-executor-test` | `python`, defaults | None | Minimal job of #5536: the default image pulls and starts and has the prerequisites of `install` (P0 to P11) |
| `python-install-test` | `python`, defaults | `tests/fixtures/normal` plus a `.python-version` probe; both flags false; no requirements file | Minimal job of #5537 (T0 to T14), now also T15 and T16. No dependency is installed |
| `python-role-test` | `python`, defaults | `test_resources/`; `molecule_role_test: true` | This repository at `CIRCLE_SHA1` and then the Molecule requirements are installed; lint passes |
| `python-playbook-test` | `python`, defaults | `tests/fixtures/playbook/`; `molecule_playbook_test: true` | Both requirements files are installed, in order; lint passes |
| `python-molecule-test` | `python`, defaults | `test_resources/`; both flags false | Only the Molecule requirements are installed; lint passes |
| `python-negative-test` | `python`, defaults | `tests/fixtures/negative`; both flags false | The real lint ends with 2 and reports exactly the expected violation |
| `python-resource-class-test` | `python`, `resource_class: medium` | Playbook fixture and flag | The container has the memory limit of `medium`; the path works there |
| `python-direct-docker-test` | A `docker` job that names the verified digest itself, `small` | As `python-install-test` | The path works without the `python` executor (contract 7.3, E3) |
| `python-install-first-test` | `python`, defaults | `tests/fixtures/normal`; `install` runs before the checkout | Contract E2: the order install, checkout, execute works |
| `python-reinstall-test` | `python`, defaults | `tests/fixtures/normal`; `install` three times | Second install reuses the environment (F8); a changed distribution and a missing CLI are rejected and not repaired (F7, F11) |
| `python-pip-settings-test` | `python`, defaults; conflicting `PIP_*` variables and pip configuration files | `tests/fixtures/normal` | The settings have no effect; `install` prints their names and no value (F12) |
| `python-failure-test` | `python`, defaults | None | `install` fails as required in seven conditions (table below) |
| `python-explicit-image-test` | `python` with `image: cimg/python:3.13.18` | None | The `image` parameter reaches the job; without the verified interpreter `install` fails (E5, F2) |
| `default-install-test` | Existing `default` executor | None | `install` is rejected there, and the existing tools stay as they were (E7) |

`tests/fixtures/normal` without the probe file is the case `plain` of the
checker. It is the input of `normal-test` on the existing path.

### Checks T0 to T18

`.circleci/check-python-install.py` runs in separate run steps around the
public steps: `before`, `after-install`, and `after-execute`. It runs with the
verified interpreter by its absolute path and `-I`. The case names the
fixture and what `execute` must call (`CASES` in that file).

| Check | Step | Requirement |
| --- | --- | --- |
| T0 | before | The checkout is this pipeline's revision |
| T1 | before | The fixed information in `src/scripts/install.sh` equals `python-install-lock.json` and names the verified interpreter |
| T2 | before | Clean job: no managed environment, no `ansible*` command on PATH, no publishing token, empty working directory |
| T15 | before | The container has the memory limit of the configured resource class |
| T3 | after-install | The state record is complete and names this Orb, the fixed set, and the interpreter |
| T4 | after-install | The managed environment is outside the working directory and the checkout |
| T5 | after-install | The installed distributions equal the fixed set plus the recorded bootstrap distributions |
| T6 | after-install | Every exposed command resolves to the command directory of the managed environment, which holds nothing else |
| T7 | after-install | The four direct commands run from the managed environment and report the recorded versions |
| T8 | after-install or after-execute | A traced lint starts only recorded run-time CLIs, and each resolves inside the managed environment |
| T9 | after-install | `python`, `python3`, `pip`, and `pip3` resolve as before `install` |
| T10 | after-install | `install` changed only PATH for later steps: one export line in `BASH_ENV` |
| T11 | after-install | The working directory, its `.python-version`, and the pyenv version file are unchanged |
| T16 | after-install | In the home directory `install` added only the managed environment and changed nothing else |
| T12 | after-execute | The real `execute` made exactly the expected calls in order, each through the managed environment |
| T13 | after-execute | The final lint processed the real files with no violation, or failed with exactly the expected violation (case `negative`) |
| T14 | after-execute | The fixture, the state record, and the installed distributions are unchanged |
| T17 | after-execute | Exactly the expected roles are installed at the pinned revisions, from the expected repositories and commits |
| T18 | after-execute | Case `negative` only: the expected result equals the one of the existing path |

Notes:

- T8 runs after `install` where the lint must pass without dependencies
  (`normal`, `plain`). In the other cases it runs after `execute`, because the
  roles must exist first, and in the case `negative` it must end with 2.
- T15 compares the memory limit that the container shows
  (`/sys/fs/cgroup`). The CPU quota is recorded and not compared, because
  CircleCI can grant more than the cores of the class.
- T16 compares every entry below the home directory before and after
  `install`: kind, and size and modification time of files. In
  `python-install-first-test` nothing of this repository exists before
  `install`, and the checkout that follows adds `~/.ssh`. Two inline steps
  therefore list the home directory with `find`, directly before and directly
  after `install`, and T16 compares these two lists.
- T17 reads `meta/.galaxy_install_info` and the Git archive record of
  `record-evidence.py`, as `integration-test.py` does on the existing path.
  In the cases `plain` and `negative` it requires that no role was installed
  and no archive was fetched. The case `normal` has no T17; there T12 already
  requires that `execute` made no dependency call.
- From the case `plain` on, the checker sets `ANSIBLE_ROLES_PATH` after
  `install`, as the jobs of the existing path do. The case `normal` stays as
  #5537 measured it and sets no such variable.

### From the minimal jobs to the required checks

This table maps every condition of #5536 C4 and #5537 C7 to what carries it
now. Neither minimal job was removed or merged, and no condition was changed.

| Condition | Carried by | Input | Expected result |
| --- | --- | --- | --- |
| #5536 C4, P0: checkout is the candidate commit | `python-executor-test` (unchanged); T0 in the ten jobs with T checks; `revision` in the three other jobs | — | `HEAD` equals `CIRCLE_SHA1` |
| P1: the executor pins the recorded digest | `python-executor-test`; both pack jobs (`verify-packed-install.sh`) | `python-image-lock.json` | Source and packed default image equal the record; the direct Docker job names the same reference |
| P2: platform | `python-executor-test` | — | linux/amd64 |
| P3, P4: Bash and Git | `python-executor-test`; every new-path job uses both | — | Both are on PATH and run |
| P5, P6: interpreter path and version | `python-executor-test`; T1, T3, T5 in ten jobs | — | Python 3.14.10 at the recorded path |
| P7, P8: pip and virtual environment | `python-executor-test`; every successful `install` | — | A virtual environment with pip is created |
| P9: no `ansible*` command on PATH | `python-executor-test`; T2; `clean-start` | — | None |
| P10: home writable without sudo | `python-executor-test`; T4 and T16 | — | `install` writes only `~/.orbss-ansible-lint` |
| P11: `.python-version` does not change the interpreter | `python-executor-test`; `python-install-test` and `python-direct-docker-test` (probe file; T5, T9, T11) | Probe file | The verified interpreter is used |
| #5536 C4: publish requires the job; filters; no context or token | `.circleci/test-deploy.yml`: `requires` of `orb-tools/publish`, `filters: *filters` | — | Unchanged for this job; the twelve new jobs are connected the same way |
| #5537 C7, T0 to T14 | `python-install-test`, same case and conditions | `tests/fixtures/normal` plus probe | All pass; 1 file processed of 2 encountered |
| T0 to T14 with other inputs | `python-role-test`, `python-playbook-test`, `python-molecule-test`, `python-negative-test`, `python-resource-class-test`, `python-direct-docker-test`, `python-install-first-test`, `python-reinstall-test`, `python-pip-settings-test` | Table "Jobs" | All pass with the expectations of the case |
| #5537 C7: clean job | T2 in ten jobs; `clean-start`; `image` checks | — | No environment, no `ansible*` command, no token |
| #5537 C7: separate run steps, real `execute` | Same step layout in every job that runs `execute` | — | T6, T7, T12 |
| #5537 C7: real Ansible file, no violation | T13 in nine jobs; exact violation in `python-negative-test` | Table "Jobs" | T13 |
| #5537 C7: publish requires the job; filters; no context or token | As for #5536 C4 | — | As above |

Differences from the minimal job of #5537 that add conditions: T15 and T16
also run in `python-install-test`. Nothing was taken away.

### Failure cases and what the test replaces

CircleCI ends a job at the first failed step. A failing `ansible-lint/install`
therefore cannot be followed by a step that inspects the result. For the
conditions in which `install` must fail, and where its output has to be read,
`.circleci/check-install-script.py` starts the production script itself:

```text
/bin/bash -eo pipefail /tmp/ansible-lint-orb-source/src/scripts/install.sh
```

- This is the script of the candidate commit, unchanged, in the shell that
  CircleCI uses for a run step. Both pack jobs show that the packed command
  equals this file (`verify-packed-install.sh`).
- It is **not** the public step. A passing scenario is no evidence that
  CircleCI ran a failing step. Wherever `install` is expected to succeed, the
  jobs use the public step.
- Each scenario changes only what the table names. pip, its command line, and
  the index URL are those of production in every scenario.

Every failing scenario requires: exit 1; one failure line with the expected
category; the line that no command was published; `BASH_ENV` unchanged; the
exposed commands resolve as before; no success message.

| Scenario (job) | Contract | Set up by the test | Expected category |
| --- | --- | --- | --- |
| `existing-command` (failure) | E6, F3 | A directory with an executable named `ansible-lint` first on PATH of the script's process | `existing-command`; the tool is neither started nor changed |
| `not-writable` (failure) | F5 | Mode 0555 on the home directory during the run | `permission` |
| `location` (failure) | F14 | The home directory as current directory | `location` |
| `no-bash-env` (failure) | F15 | `BASH_ENV` removed from the script's process | `publish` |
| `no-venv` (failure) | F4 | The `ensurepip` module of the verified interpreter hidden during the run | `virtual-environment` |
| `index-unreachable` (failure) | F9 | Standard proxy variables point to `127.0.0.1:9`; no pip setting | `download-or-install`; a directory without state record is left |
| `foreign` (failure) | F6 (S3) | Nothing: the directory left by the scenario before | `foreign-environment`; nothing changed or deleted |
| `changed-distribution` (reinstall) | F7, F11 (S2) | The version in the metadata of one installed distribution | `inconsistent-environment`; nothing repaired |
| `missing-cli` (reinstall) | F7 (S2) | `ansible-config` moved out of the command directory | `inconsistent-environment`; nothing repaired |
| `unverified-image` (explicit image) | E5, F2 | Nothing: the image has no interpreter at the verified path | `interpreter` |
| `default-executor` (default) | E7 | Nothing: the existing default image | `interpreter` or `existing-command`; the four tools print the same versions afterwards |

Scenarios that expect success: `reinstalled` compares the environment after
the second **public** `install` with the first (F8). `consistent` runs the
script once more to read its output. `pip-settings` reads the output for the
names of the ignored settings and requires that no test value appears (F12).

The script checks the interpreter before it looks for existing commands. On
the existing default image the interpreter path is missing, so the expected
category of `default-executor` is `interpreter`. The evidence records the
category (`rejected_by`). F3 itself is measured by `existing-command`.

`no-venv` moves the module directory aside and puts it back. A directory of
an image layer cannot be renamed on the overlay file system of a container,
so it is copied with its modification times and the original is removed; the
evidence names the method. If the module cannot be hidden, the scenario
fails. F4 is never reported as measured without a run.

### Measured and structural

| Kind | Items |
| --- | --- |
| Measured through the public step | F8 (second install), F12, F13, E2, E3, non-default resource class |
| Measured through the production script | E5/F2 (missing path), E6/F3, E7, F4, F5, F6, F7, F9, F11, and in addition F14, F15 |
| Structural only | F1 (platform); F2 for an interpreter of another version at the same path; F10 (dependency resolution, withdrawn release, other network failures). F9 is the one representative measurement of an unreachable index |

### Executor settings and images

- Default and `medium`: T15 in the default jobs and in
  `python-resource-class-test`. CircleCI's record of each job names the class
  as well.
- Explicit image: `python-explicit-image-test` passes
  `image: cimg/python:3.13.18`. The check requires that the verified
  interpreter path is absent, which the default image cannot satisfy. Match
  the reference to the job's "Spin up environment" log.
- That image is **not** a verified image. It is named by a tag, shows only
  that the parameter is applied and that `install` refuses the image, and is
  not added to `python-image-lock.json`. The verified list still holds one
  image.
- Direct Docker job: both pack jobs require that
  `python-direct-docker-test` names exactly the reference of
  `python-image-lock.json`.

### Comparison with the existing path

Both paths use the same fixtures, flags, and pinned role revision
(`747af654d2a2e05c1cfabce9c0b79b2a1eae3650`).

| Existing path | New path | Compared |
| --- | --- | --- |
| `normal-test` | `python-install-first-test`, `python-reinstall-test`, `python-pip-settings-test` (case `plain`) | Exit code, lint summary, no dependency call |
| `role-test` | `python-role-test` | Calls and their order, installed revisions, lint summary |
| `playbook-test` | `python-playbook-test` | As above |
| `negative-test` | `python-negative-test` | Exit code, violation, every output line (T18 enforces equal expectations) |
| `resource-class-test` | `python-resource-class-test` | As `playbook-test` |
| `custom-image-test` | None | The new path has one verified image |
| None | `python-molecule-test` | The existing path has no job with both flags false and Molecule requirements |

Known differences, which are not lint results:

- Location of Python: `/usr/local` in the GHCR image,
  `/home/circleci/.pyenv/versions/3.14.10` on the new path. A notice that
  names a file of the Python installation differs in this prefix only.
- Release notice of ansible-lint: `pip install --upgrade ansible-lint` in a
  virtual environment, `pip3 install --user --upgrade ansible-lint` on the
  existing path (`tests/python-negative-expected.json`).
- `python-install-test` has the probe file, so lint reports 1 file processed
  of 2 encountered, and it sets no `ANSIBLE_ROLES_PATH`. Without that variable
  and without a project marker, ansible-lint 26.10.1 uses `/` as project
  directory and prints warnings about `/.ansible` for a user that cannot
  write there. With the variable it uses the cache in the home directory, as
  in the other jobs and on the existing path.

The installed versions and the lint summaries of both paths are taken from
the evidence of one pipeline and recorded in #5539. No job compares two jobs.

### Planned usage and these jobs

The planned usage of `110_ロードマップ` version 1 and contract 6.4 is
`executor: ansible-lint/python` with the steps `checkout`,
`ansible-lint/install`, `ansible-lint/execute`.

- `python-install-test` runs these steps in this order, without parameters.
- `python-role-test` and `python-playbook-test` pass the flags to `execute`.
- `python-direct-docker-test` is the same job with the image written in the
  job.

Two differences from a consumer job: the checkout goes to another directory
and a fixture is copied in, because the root of this repository is not a lint
input; and check steps stand between the public steps. The check steps add
observers for `execute` only after `install`.

### Evidence

| Artifact | Jobs | Content |
| --- | --- | --- |
| `python-executor-evidence` | `python-executor-test` | P0 to P11 |
| `python-install-evidence` | Ten jobs with T checks | `python-install.json`: case, commit, job URL, every check with its observation; the three phase files |
| `install-script-evidence` | Reinstall, pip settings, failure, explicit image, default | One file for each scenario: what the test set up, exit code, output, failure line, checks |
| `packed-orb-structure` | Both pack jobs | `install-<purpose>.json`: packed command, fixed set, default image of `python`, and the reference of the direct Docker job |

The final release candidate repeats all of these jobs (#5541). Results of
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
