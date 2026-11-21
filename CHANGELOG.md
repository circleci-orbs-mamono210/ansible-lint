# Changelog

Notable changes are recorded here using the categories from
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
From 1.0.0, releases use [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
with the compatibility and image-update policy in [README.md](README.md).

## [Unreleased]

### Added

- A `python` executor: a `cimg/python` Docker executor pinned by digest
  (`sha256:1e39aeaaf097598f60e55e42ee57289448a97dea346a9c8f53e3af70b50ac7db`,
  `linux/amd64`, tag `3.14.10` at selection), with the `image` and
  `resource_class` parameters. It contains no `ansible-lint`.
- An `install` command without parameters. It installs a pinned tool set from
  PyPI into `$HOME/.orbss-ansible-lint` with the verified Python 3.14.10:
  ansible-lint 26.10.1, Ansible package 14.5.0, and ansible-core 2.21.5, with
  30 distributions in total at exact versions. After checking the result, it
  exposes the `ansible*` commands to later steps of the same job through
  `BASH_ENV`. It supports verified images only and ignores the consumer's pip
  settings.
- The contract of the new path in
  [docs/python-install-contract.md](docs/python-install-contract.md), with the
  records [python-image-lock.json](python-image-lock.json) and
  [python-install-lock.json](python-install-lock.json).
- A source example of the python executor path.
- CI checks of the new path, including the failure cases of `install`, and
  checks that both actual pack outputs contain this commit's `install` command
  and keep the `default` and `execute` definitions equal to the published 1.0.0
  source.

### Changed

- README explains both paths, the new API, how `install` works, and the update
  procedure of each path, including the release types of the new path.
- The Orb description presents both paths. The source example of the default
  executor references `orbss/ansible-lint@1.1.0`.

### Verification scope

The `default` executor, the `execute` command, and the default GHCR image digest
are unchanged. CI found no difference from the published 1.0.0 source in either
pack output. Existing configurations need no `install` step. The release adds
the python executor path and keeps the existing contract, so it is a minor
release.

On commit [`5e542f7`](https://github.com/circleci-orbs-mamono210/ansible-lint/commit/5e542f78e0a08529ea8302582a3bb1661c248882),
both paths produced the same lint results for the same fixtures, settings, and
fixed role revision: the normal, role, playbook, resource-class, and negative
cases. Their main versions are also equal: Python 3.14.10, Ansible package
14.5.0, ansible-core 2.21.5, and ansible-lint 26.10.1. Equal versions do not
guarantee equal results for other inputs. Output other than the lint results
differed:

- ansible-lint prints a notice when a newer release exists. It suggests
  `pip install --upgrade ansible-lint` on the python executor path and
  `pip3 install --user --upgrade ansible-lint` on the default executor path.
  The Orb pins the versions, so the notice is not an instruction for Orb users.
- An HTTP 304 cleanup `ResourceWarning` appeared in all six jobs of the default
  executor path and in none of the lint runs of the python executor path. The
  cause was not investigated.

The python executor path downloads the tool set from PyPI in every job, so it
needs network access and takes longer. Faster jobs are not promised. Exact
versions do not verify the hashes of downloaded files or keep releases
available, and the whole result is not guaranteed to be reproducible. The final
release candidate is checked again before publication.

## [1.0.0] - 2026-11-10

### Added

- Documentation of the public executor/command API, migration from 0.0.3,
  compatibility guarantees, and the image verification/update procedure.
- Image identity and measured version records in `image-lock.json`.
- Normal-use, negative, and custom-image integration tests, alongside the role,
  playbook, and resource-class cases. Negative capture and invocation checking
  have 42 self-tests, including rejection of unexpected success, wrong exit
  codes, mismatched or mixed diagnostics, and missing invocation evidence.
- Checks on the actual injection and publication pack outputs to verify that
  the final `ansible-lint` command does not modify its exit code.

### Changed

- The default image reference in the published 0.0.3 source was
  `ghcr.io/docker-images-mamono210/circleci-executors/ansible-lint:latest`.
  The 1.0.0 default pins the same repository to
  `sha256:3dd0b103851b24ea8796af7126fff4340023a6288293030ae65b01f0446a9fdf`
  for `linux/amd64`. The tag at selection was `26.10.1-py3.14.10`.
- The selected image measured **Python 3.14.10**, **Ansible package 14.5.0**,
  **ansible-core 2.21.5**, and **ansible-lint 26.10.1**. Initial extracted-image
  measurement was at `2026-10-29T21:31:43+09:00`; CircleCI container checks
  confirmed these values at `2026-10-29T22:32:22+09:00` through
  `2026-10-29T22:32:25+09:00`. See [README.md](README.md#default-image).
- CI uses `circleci/orb-tools@12.5.0` and inline injection of the candidate Orb.
  Integration tests no longer require a prior dev publish or an Orb publishing
  token. Production publishing retains its own authentication and requires
  successful pack checks and all six integration cases.
- Playbook/resource-class test inputs are repository-managed fixtures instead
  of an external `wordpress_install` clone. External test role references are
  fixed to a commit; external services are still needed to retrieve them.
- The 1.0.0 compatibility declaration covers the call and execution contract,
  including dependency installation and exit-code propagation. Lint findings
  are outside that guarantee. Default-image updates, including same-tag
  rebuilds, require minor or major releases; they are not patch releases.

### Fixed

- Public parameter descriptions and Orb metadata now explain the execution
  requirements and pinned default image.
- The source example uses `ansible-lint/default` and references
  `orbss/ansible-lint@1.0.0`.
- The playbook fixture explicitly sets its project directory so validation is
  confined to that fixture. Negative verification records the exact observed
  HTTP 304 cleanup and decimal-literal warning lines, plus the bounded
  new-release announcement format. The expected failure, complete lint output,
  notice counts and rejection of other output remain mandatory. The decimal
  warning's internal call site is unconfirmed; see [tests/README.md](tests/README.md).
- The build badge and LICENSE link use `main`. The MIT copyright holder is
  `mamono210` instead of the placeholder.

### Verification scope

Published 0.0.3 source was obtained at `2026-10-29T15:51:51+09:00`, SHA-256
`0f4661df54855162138791c12a11e7045fabb902906babb8053d56605c78a4c5`.
Source comparison confirms that the public call and execution contract is
preserved apart from the planned default-image reference change.

The comparison `latest` resolved at `2026-10-29T21:19:14+09:00` had the same
digest and platform as the selected image. Only the separate image-difference
comparison was omitted on that basis; the six regression categories remained
required. This is not a reconstruction of historical 0.0.3 environments or a
claim of no lint impact on untested inputs.

On [`98f08cf`](https://github.com/circleci-orbs-mamono210/ansible-lint/commit/98f08cf4852195ee6b810c03ad3daa1c17cb1f6f),
all six categories and both pack checks passed. Positive fixtures passed, and
the negative fixture produced exit code `2` and exactly one `name[missing]`
finding at `playbook.yml:6`; all 25 observer self-tests passed. The test-only
observer's success does not mean that a failed CircleCI step was executed.
See [tests/README.md](tests/README.md) and
[tests/image-comparison.json](tests/image-comparison.json).

## 0.0.3 - Release date unconfirmed

### Added

- The executor's `resource_class` parameter, with `small`, `medium`, `medium+`,
  and `large` choices and a default of `small`.

This difference is present between published 0.0.2 and 0.0.3 source and matches
the implementation recorded in ticket #3251 and
[`5ff9685`](https://github.com/circleci-orbs-mamono210/ansible-lint/commit/5ff968563211cbad65e4178a7cdbd780d0949d8b).
That correspondence does not establish a release date or exact release commit.

## 0.0.2 - Release date unconfirmed

### Fixed

- Forward `molecule-playbook-test` to the dependency installation script through
  `PARAM_MOLECULE_PLAYBOOK_TEST`.

This difference is present between published 0.0.1 and 0.0.2 source and matches
ticket #3247 and
[`9079416`](https://github.com/circleci-orbs-mamono210/ansible-lint/commit/9079416ca61ed7ca1b9196063bd6020b5ec54fd9).
The exact release commit and publication date are unconfirmed.

## 0.0.1 - Release date unconfirmed

### Added

- Ansible lint execution with a Docker executor and Molecule-related role
  installation support. The original implementation is recorded in ticket
  #3209 and
  [`1d1a72c`](https://github.com/circleci-orbs-mamono210/ansible-lint/commit/1d1a72c4d5c9ac19294a8357d5e837dc35ab9775).

Published 0.0.1 source contains the initial command and image parameter.
Its playbook flag was not yet forwarded to the script; that was fixed in 0.0.2.
The exact release commit and publication date are unconfirmed.

The historical entries use published source differences and the corresponding
implementation history. No historical tag or compare link is assumed.

[Unreleased]: https://github.com/circleci-orbs-mamono210/ansible-lint/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/circleci-orbs-mamono210/ansible-lint/tree/v1.0.0
