# Ansible lint Orb

[![CircleCI Build Status](https://circleci.com/gh/circleci-orbs-mamono210/ansible-lint/tree/main.svg?style=shield)](https://circleci.com/gh/circleci-orbs-mamono210/ansible-lint/tree/main)
[![CircleCI Orb Version](https://badges.circleci.com/orbs/orbss/ansible-lint.svg)](https://circleci.com/developer/orbs/orb/orbss/ansible-lint)
[![GitHub License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](https://github.com/circleci-orbs-mamono210/ansible-lint/blob/main/LICENSE)

Run `ansible-lint` against the current working directory in CircleCI. This Orb
provides a Docker executor and an `execute` command, with optional role
installation for repositories that use Molecule requirements.

The examples below target `orbss/ansible-lint@1.0.0`. Confirm that version is
available in the [Orb registry](https://circleci.com/developer/orbs/orb/orbss/ansible-lint)
before updating a consumer. See [CHANGELOG.md](CHANGELOG.md) for release status.

## Usage

Add this to `.circleci/config.yml` in a repository containing Ansible files:

```yaml
version: 2.1

orbs:
  ansible-lint: orbss/ansible-lint@1.0.0

jobs:
  lint:
    executor: ansible-lint/default
    steps:
      - checkout
      - ansible-lint/execute

workflows:
  lint:
    jobs:
      - lint
```

Both command parameters default to `false`. A `molecule/` directory is not
required for normal linting. Lint configuration and file discovery follow
`ansible-lint` in the current working directory; the Orb does not add lint
arguments or install `ansible-lint` into an arbitrary executor.

For an Ansible role repository, replace the command step with:

```yaml
- ansible-lint/execute:
    molecule-role-test: true
```

For a playbook repository with `roles/requirements.yml`, use:

```yaml
- ansible-lint/execute:
    molecule-playbook-test: true
```

These options install roles before linting. They do not run Molecule tests.
The [source example](src/examples/example.yml) shows the role-repository case.

## Public API

The API source is [src/](src/). No reusable jobs are exported.

### Executor: `ansible-lint/default`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `image` | string | The digest reference in [Default image](#default-image) | Docker image providing the tools used by `execute`. |
| `resource_class` | enum: `small`, `medium`, `medium+`, `large` | `small` | CircleCI Docker executor resource class. |

For example, the following job selects the separately tested custom image and
the `medium` resource class. Add it to the `jobs` section of a configuration
declaring the Orb above, then include `lint-custom` in its workflow.

```yaml
lint-custom:
  executor:
    name: ansible-lint/default
    image: ghcr.io/docker-images-mamono210/circleci-executors/ansible-lint@sha256:4ea7fe7ebbe7fd06bd5a7fc61b8931c3303a11c9bd4eb06431a810f5914b8718
    resource_class: medium
  steps:
    - checkout
    - ansible-lint/execute
```

A custom image must provide `ansible-lint`, `ansible`, `ansible-community`,
`ansible-galaxy`, and Bash on `PATH`, together with the tools' runtime
dependencies. Repository-based role installation also needs Git and access to
the referenced repositories. The selected image must run on the executor's
platform. A digest pins its contents; a tag alone can be rebuilt.

The default-image version table below does not describe an image supplied by a
consumer. One alternative `linux/amd64` image was verified in
[custom-image-test #477](https://circleci.com/gh/circleci-orbs-mamono210/ansible-lint/477);
its identity is recorded in [tests/custom-image-lock.json](tests/custom-image-lock.json).
This is not a compatibility guarantee for every custom image.

### Command: `ansible-lint/execute`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `molecule-role-test` | boolean | `false` | Install the current repository at `CIRCLE_SHA1` as an Ansible role. |
| `molecule-playbook-test` | boolean | `false` | Install roles from `roles/requirements.yml`. |

The command performs these steps in order:

1. Display `ansible-lint --version`.
2. Display `ansible --version` and `ansible-community --version`.
3. If `molecule-role-test` is true, run
   `ansible-galaxy install "git+${CIRCLE_REPOSITORY_URL},${CIRCLE_SHA1}"`.
4. If `molecule-playbook-test` is true, run
   `ansible-galaxy install -r roles/requirements.yml`.
5. Install each existing `molecule/*/requirements.yml` with
   `ansible-galaxy install -r`, independently of both flags.
6. Run `ansible-lint` without arguments. Its exit code determines the final
   lint step's success or failure; the Orb does not mask it.

Check out the repository first and supply any requirements files enabled by
the flags. Private role repositories need suitable access from the job.
The current dependency helper may print a `find` message when `molecule/` is
absent. That absence alone does not prevent successful linting; the normal-use
integration test checks a real Ansible file with both flags false.

## Default image

The `image` parameter defaults to this exact reference:

```text
ghcr.io/docker-images-mamono210/circleci-executors/ansible-lint@sha256:3dd0b103851b24ea8796af7126fff4340023a6288293030ae65b01f0446a9fdf
```

| Identity | Recorded value |
| --- | --- |
| Repository | `ghcr.io/docker-images-mamono210/circleci-executors/ansible-lint` |
| Manifest digest | `sha256:3dd0b103851b24ea8796af7126fff4340023a6288293030ae65b01f0446a9fdf` |
| Tag at selection | `26.10.1-py3.14.10` |
| Tag resolved at | `2026-10-29T21:21:47+09:00` |
| Platform | `linux/amd64` (single-platform manifest, not an image index) |

The following versions were measured from that image, not inferred from its tag:

| Component | Measured version | Check command |
| --- | --- | --- |
| Python | `3.14.10` | `python3 --version` |
| Ansible package | `14.5.0` | `ansible-community --version` |
| ansible-core | `2.21.5` | `ansible --version` |
| ansible-lint | `26.10.1` | `ansible-lint --version` |

[image-lock.json](image-lock.json) records the identity and evidence.
The initial measurement at `2026-10-29T21:31:43+09:00` used binaries and libraries
from verified extracted image contents on the host. It was not a Docker run.
That is the measurement retained in the comments in
[src/executors/default.yml](src/executors/default.yml).

The same four commands subsequently ran inside the CircleCI Docker executor in
[role-test #424](https://circleci.com/gh/circleci-orbs-mamono210/ansible-lint/424)
at `2026-10-29T22:32:22+09:00` through `2026-10-29T22:32:25+09:00`.
All returned zero and the versions matched the table. Playbook and resource-class
jobs #425 and #423 agreed. Image identity was also checked against each job's
full reference in its `Spin up environment` log.

To recheck a selected image, pull the exact digest for `linux/amd64`, run these
four commands inside that same image, and compare the outputs with the record.
`ansible --version` reports ansible-core; it does not report the Ansible package
version. YAML source comments are removed by the adopted pack operation, so
use this README and the identity record for version information.

The digest fixes the default image contents for this Orb release. Rebuilding
the same tag or publishing a new image does not change this reference
automatically. External roles, network services, and input files remain outside
that guarantee; the entire execution result is not guaranteed reproducible.

## Compatibility and image updates

From 1.0.0, versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
with the following declared contract:

- Compatibility covers executor and command names, parameter names, types and
  defaults, dependency installation, execution order, and exit-code propagation.
- Changes to lint findings are outside the compatibility guarantee.
- Updating the default image reference is an explicit exception to unchanged
  defaults. It requires a **minor** release when the call and execution contract
  is preserved, or a **major** release when it is not.
- The same rule applies to a new digest for a rebuilt tag, even if displayed
  Python or ansible-lint versions are unchanged. Image updates are never patch
  releases under this policy.
- Other compatible bug fixes that do not update the default image can be patch
  releases. Incompatible public API changes require a major release.

To update the default image:

1. Select and pull a new exact digest and platform. For an image index, identify
   the manifest for the supported platform; a tag name alone is insufficient.
2. Measure all four versions inside that image and retain the commands, outputs,
   platform, full image reference, and confirmation time.
3. In the same change, update the default reference and version comments in
   `src/executors/default.yml`, `image-lock.json`, and this README. Update the
   recorded comparison and negative expectations if the verified results change.
4. Run pack/review and all six integration categories, including negative
   observer self-tests and the checks on the actual pack outputs. Investigate
   changed lint results rather than accepting any nonzero negative result.
5. Record the image change and the tested lint impact in `CHANGELOG.md`, then
   choose minor or major using the policy above. Recheck the final release
   candidate and tag pipeline before publication.

Consumers that need independence from future default-image updates can set
`image` to their own full digest reference.

## Migrating from 0.0.3

For a valid 0.0.3 configuration, change the Orb reference to
`orbss/ansible-lint@1.0.0` after publication. The command/executor names,
parameter names and types, boolean defaults, resource-class choices and default,
and the dependency/lint execution steps are preserved. No parameter rename or
additional migration procedure is required. An explicitly supplied `image`
continues to override the default.

The planned default change is from
`ghcr.io/docker-images-mamono210/circleci-executors/ansible-lint:latest` to the
digest above. This is based on the published 0.0.3 source, retrieved on
`2026-10-29T15:51:51+09:00` (SHA-256
`0f4661df54855162138791c12a11e7045fabb902906babb8053d56605c78a4c5`),
not an assumption that an old Git commit equals a published Orb.

The comparison `latest` resolved at `2026-10-29T21:19:14+09:00` had the same
manifest digest and `linux/amd64` platform as the selected image. Therefore a
separate comparison for image-content differences was omitted using those
recorded identities. This did not reconstruct the image used by historical
0.0.3 runs, and does not establish identical results for every consumer input.
See [tests/image-comparison.json](tests/image-comparison.json).

All six regression categories passed on commit
[`98f08cf`](https://github.com/circleci-orbs-mamono210/ansible-lint/commit/98f08cf4852195ee6b810c03ad3daa1c17cb1f6f):
normal use, role, playbook, negative, resource class, and a different custom image.
Positive fixtures passed; the negative fixture produced exactly the expected
`name[missing]` finding at `playbook.yml:6` with real exit code `2`.
The test-only observer validated that result and 25 observer self-tests passed.
This is evidence for those fixtures, not a claim that all warnings or possible
lint changes have been eliminated. See [tests/README.md](tests/README.md).

## License

[MIT](https://github.com/circleci-orbs-mamono210/ansible-lint/blob/main/LICENSE).
