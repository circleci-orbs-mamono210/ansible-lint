# Integration tests for issue #5501

All six CircleCI jobs use the public `ansible-lint/execute` from the same commit's
packed Orb, injected by orb-tools 12.5.0. Only production publish receives
`CIRCLECI_ORBS`. No test needs a dev publish or publishing token.

| Job | Local input | Public parameters | Required observation |
| --- | --- | --- | --- |
| `normal-test` | `tests/fixtures/normal/playbook.yml` | Both default to false | Exactly one Ansible file processed, zero failures/warnings, exit 0; no dependency install |
| `role-test` | `test_resources/` | `molecule-role-test: true` | Install this repository at `CIRCLE_SHA1`, then the fixed Molecule dependency; lint succeeds |
| `playbook-test` | `tests/fixtures/playbook/` | `molecule-playbook-test: true` | Install both requirements files, verify both distinct role names/revisions; lint succeeds |
| `negative-test` | `tests/fixtures/negative/playbook.yml` | Both default to false | Real exit 2, exactly one `name[missing]` at `playbook.yml:6`; no other diagnostics |
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
notice ID, count and text. Both complete output forms (with/without this notice)
are checked. Other HTTP statuses, warnings, partial/repeated notices, extra
errors or files are rejected. No warning suppression or linter environment
change is used.
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
