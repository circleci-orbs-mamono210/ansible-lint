# Ansible lint Orb

[![CircleCI Build Status](https://circleci.com/gh/circleci-orbs-mamono210/ansible-lint/tree/main.svg?style=shield)](https://circleci.com/gh/circleci-orbs-mamono210/ansible-lint/tree/main)
[![CircleCI Orb Version](https://badges.circleci.com/orbs/orbss/ansible-lint.svg)](https://circleci.com/developer/orbs/orb/orbss/ansible-lint)
[![GitHub License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](https://github.com/circleci-orbs-mamono210/ansible-lint/blob/main/LICENSE)

Run `ansible-lint` against the current working directory in CircleCI. The Orb
offers two ways to provide the tools:

- the `default` executor, whose pinned image already contains `ansible-lint`
  and Ansible, with the `execute` command; or
- from 1.1.0, the `python` executor with the `install` command, which installs
  a pinned tool set into an Orb-managed environment before `execute` runs.

Both support optional role installation for repositories that use Molecule
requirements.

The examples below target `orbss/ansible-lint@1.1.0`. Confirm that version is
available in the [Orb registry](https://circleci.com/developer/orbs/orb/orbss/ansible-lint)
before updating a consumer. See [CHANGELOG.md](CHANGELOG.md) for release status.

## Usage

### Choosing a path

| | Default executor path | Python executor path |
| --- | --- | --- |
| Steps | `checkout`, `ansible-lint/execute` | `checkout`, `ansible-lint/install`, `ansible-lint/execute` |
| Executor | `ansible-lint/default` | `ansible-lint/python`, or a job that uses the same verified image digest |
| Tools | Preinstalled in the pinned GHCR image | Installed from PyPI by `install` in each job |
| Network access for the tools | Not needed | HTTPS access to PyPI |
| Job time | No installation step | Longer by the time `install` takes |
| Available from | 1.0.0 | 1.1.0 |

Existing users can keep the default executor path. Updating the Orb reference
to 1.1.0 needs no `install` step (see [Updating from 1.0.0](#updating-from-100)).

A job uses one path. Do not add `install` to a job on the `default` executor:
`install` rejects that image (see [Failures](#failures)).

### Default executor path

Add this to `.circleci/config.yml` in a repository containing Ansible files:

```yaml
version: 2.1

orbs:
  ansible-lint: orbss/ansible-lint@1.1.0

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
`ansible-lint` in the current working directory. `execute` does not add lint
arguments and does not install `ansible-lint` into an arbitrary executor: the
executor must already provide the tools. The separate `install` command of the
python executor path installs them, and only on verified images.

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

### Python executor path

Add this to `.circleci/config.yml` instead:

```yaml
version: 2.1

orbs:
  ansible-lint: orbss/ansible-lint@1.1.0

jobs:
  lint-with-install:
    executor: ansible-lint/python
    steps:
      - checkout
      - ansible-lint/install
      - ansible-lint/execute

workflows:
  lint:
    jobs:
      - lint-with-install
```

`install` prepares the tools for the later steps of the same job, and
`execute` then works as in the default executor path. For role and playbook
repositories, pass `molecule-role-test: true` or `molecule-playbook-test: true`
to `execute` as shown above. The [source example](src/examples/lint-with-install.yml)
shows the normal case.

A job can also write the same verified image digest in its own `docker` section
instead of using the executor:

```yaml
jobs:
  lint-with-install:
    docker:
      - image: cimg/python@sha256:1e39aeaaf097598f60e55e42ee57289448a97dea346a9c8f53e3af70b50ac7db
    resource_class: small
    steps:
      - checkout
      - ansible-lint/install
      - ansible-lint/execute
```

Arm resource classes are not supported. Running `install` before `checkout` is
also supported. Each `install` downloads the tool set from PyPI, so the job
needs network access and takes longer; this path does not promise faster jobs.
See [How install works](#how-install-works) for the requirements, effects, and
limits.

## Public API

The API source is [src/](src/). No reusable jobs are exported.

1.1.0 adds the `python` executor and the `install` command. The `default`
executor and the `execute` command are unchanged from 1.0.0. The detailed
contract of the new path is
[docs/python-install-contract.md](docs/python-install-contract.md). That
contract also records the published 1.0.0 `default` and `execute` definitions
that 1.1.0 keeps unchanged. `src/` holds the implemented API definitions, this
README explains usage, and the contract holds the detailed rules of the new
path.

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

### Executor: `ansible-lint/python`

| Parameter | Type | Default | Meaning |
| --- | --- | --- | --- |
| `image` | string | The digest reference in [Python executor image and tool set](#python-executor-image-and-tool-set) | Docker image of the executor. Only verified images are supported. |
| `resource_class` | enum: `small`, `medium`, `medium+`, `large` | `small` | CircleCI Docker executor resource class. |

This is a `cimg/python` Docker executor pinned by digest. It does not contain
`ansible-lint`; run `install` before `execute`. Overriding `image` is possible,
but support covers only the verified images recorded in
[python-image-lock.json](python-image-lock.json). In 1.1.0 that record has one
image: the default. A tag alone does not pin the contents, and an image is not
supported just because a job accepts it, pulls it, or starts.

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

### Command: `ansible-lint/install`

`install` has no parameters. It prepares, in the same job, the tools that a
later `execute` uses:

1. Before it creates anything, it checks the platform, the verified Python
   interpreter, the location of the managed environment, `BASH_ENV`, and that
   no command it would expose already exists on `PATH`.
2. It creates a virtual environment with the verified interpreter and installs
   the pinned tool set from PyPI.
3. It checks the installed distributions and commands, then records the result
   inside the environment.
4. It puts the directory of the exposed commands at the front of `PATH` for
   later run steps.

It does not check out code, install roles or collections, run lint, install
Python or OS packages, cache anything, or carry the environment to another job.
The implementation and the pinned tool set are part of the Orb; a consumer
repository needs no extra file. [How install works](#how-install-works)
describes the details.

## Default image

This section describes the image of the `default` executor. The `python`
executor is described in
[Python executor image and tool set](#python-executor-image-and-tool-set).

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

## Python executor image and tool set

The `image` parameter of the `python` executor defaults to this exact
reference:

```text
cimg/python@sha256:1e39aeaaf097598f60e55e42ee57289448a97dea346a9c8f53e3af70b50ac7db
```

| Identity | Recorded value |
| --- | --- |
| Repository | `docker.io/cimg/python` |
| Manifest digest | `sha256:1e39aeaaf097598f60e55e42ee57289448a97dea346a9c8f53e3af70b50ac7db` (`linux/amd64`) |
| Index digest | `sha256:308765615c69cf91df2ab259dcb91ccc198603cd7cf1b9de0b8a48fd1a3ecc1c` |
| Tag at selection | `3.14.10` |
| Tag resolved at | `2026-11-15T18:41:00+09:00` |
| Verified interpreter | `/home/circleci/.pyenv/versions/3.14.10/bin/python3.14` (Python `3.14.10`) |
| pip of the interpreter | `26.2.2` |

The default pins the `linux/amd64` image manifest; the index digest is kept for
traceability. [python-image-lock.json](python-image-lock.json) records the
identity and the measured prerequisites. They were checked inside the image in
[python-executor-test #602](https://circleci.com/gh/circleci-orbs-mamono210/ansible-lint/602).

`install` installs this pinned tool set:

| Component | Version |
| --- | --- |
| ansible-lint | `26.10.1` |
| Ansible package | `14.5.0` |
| ansible-core | `2.21.5` |
| All distributions, including dependencies | 30, each at an exact version |

[python-install-lock.json](python-install-lock.json) records the complete list,
the exposed commands, and the identifier of the set
(`1fbfcfefef86ba00fcefe9b340e3024e4d4f21e45a13f568c192e4234a389d85`), which
`install` prints. ansible-compat is held at `26.10.0`, the version that
ansible-lint reports in the image of the `default` executor. Downloads use
only `https://pypi.org/simple`.

[image-lock.json](image-lock.json) stays the record of the GHCR image of the
`default` executor. It does not describe this path.

In 1.1.0 the main versions equal those measured in the image of the `default`
executor. Equal versions do not guarantee equal lint results;
[CHANGELOG.md](CHANGELOG.md) lists the measured differences.

## How install works

[docs/python-install-contract.md](docs/python-install-contract.md) has the full
rules. This section summarizes what a job sees.

### Requirements

- Linux on amd64. macOS, Windows, the machine executor, Arm resource classes,
  and other Python versions are not supported.
- Run steps use Bash. Later steps receive the `PATH` change through `BASH_ENV`.
- The verified interpreter at its recorded path and version. `install` never
  installs Python or OS packages and never uses sudo.
- The job user can write the home directory.
- HTTPS access to PyPI and its file host in every job.
- As in 1.0.0, `execute` needs Git and access to the role repositories when
  role installation is enabled.

### Python selection

`install` uses only the verified interpreter, by its absolute path and exact
version. It does not select Python through `python` or `python3` on `PATH`,
pyenv shims, `.python-version`, or `PYENV_VERSION`, and it never changes those
settings. If the interpreter is missing, has another version, or cannot create
a virtual environment, `install` fails. It never falls back to another Python.

### Step order

| Order | Status |
| --- | --- |
| `checkout`, `install`, `execute` | Supported. This is the standard order. |
| `install`, `checkout`, `execute` | Supported |
| `execute` before `install` on the `python` executor | Not supported. `execute` fails at its first missing command, as in 1.0.0. |

### Managed environment

`install` creates its environment in `$HOME/.orbss-ansible-lint`. A job has one
such environment. It is not shared with other jobs, and keeping it through
caches or workspaces is not supported. `install` stops before it creates
anything when that directory would overlap the working directory or an active
virtual environment. A job whose working directory is the home directory is
therefore rejected.

### Commands and PATH

`install` exposes these commands from the managed environment: `ansible`,
`ansible-community`, `ansible-config`, `ansible-console`, `ansible-doc`,
`ansible-galaxy`, `ansible-inventory`, `ansible-lint`, `ansible-playbook`,
`ansible-pull`, `ansible-test`, and `ansible-vault`.

- It appends two lines to the file named by `BASH_ENV`: a comment and an
  `export` that puts `$HOME/.orbss-ansible-lint/bin` at the front of `PATH`.
  Later run steps find the commands there.
- `python`, `python3`, `pip`, and `pip3` resolve as before. `install` changes no
  other environment variable, including `PYTHONPATH`, `VIRTUAL_ENV`, `PIP_*`,
  `PYENV_*`, and `ANSIBLE_*`.
- If one of these commands already resolves on `PATH` outside the managed
  environment, `install` fails instead of shadowing it.
- Steps that use a shell other than Bash, or that reset `PATH`, are outside the
  guarantee.

### pip settings

`install` ignores the consumer's pip configuration: pip configuration files at
every level, a file named by `PIP_CONFIG_FILE`, and all `PIP_*` variables. It
prints the names of the settings it ignored, never their values. Downloads use
only the default PyPI index. The Orb neither sets nor removes the standard proxy
variables, and success is not guaranteed where a proxy, a custom certificate
authority, or a mirror is required. Later steps see the pip settings unchanged.

### Running install again

| Situation | Result |
| --- | --- |
| The environment exists and passes its check | `install` reuses it. Nothing is downloaded or installed. |
| The environment fails its check, for example after another Orb version or a changed distribution | `install` fails with `inconsistent-environment`. It repairs and deletes nothing. |
| The directory exists without a valid record, for example after a failed installation | `install` fails with `foreign-environment`. It changes nothing. |

If a later step changes the managed environment, for example with `pip install`,
`execute` runs on a modified environment that is outside the guarantee, and the
next `install` in the job fails. ansible-lint prints a notice when a newer
release exists and suggests `pip install --upgrade ansible-lint`. The Orb pins
the versions; do not upgrade inside the managed environment.

### Failures

On failure, `install` exits with status 1 and prints these two lines to
standard error:

```text
ansible-lint/install failed [<category>]: <reason>
ansible-lint/install: no command was published by this invocation.
```

| Category | Meaning |
| --- | --- |
| `platform` | The platform is not Linux on amd64. |
| `interpreter` | The verified interpreter is missing or does not match the record. |
| `location` | The managed environment would overlap the working directory or an active virtual environment, or the home directory is unusable. |
| `publish` | `BASH_ENV` is not set, or its file is not writable. |
| `existing-command` | A command that `install` would expose already exists on `PATH`. |
| `permission` | The managed environment location is not writable. |
| `virtual-environment` | The interpreter cannot create a virtual environment with pip. |
| `download-or-install` | Downloading or installing the tool set failed, for example because PyPI is unreachable. |
| `dependency` | The dependency check of the installed set (`pip check`) failed. |
| `distributions` | A new installation does not match the pinned set. |
| `command` | A command is missing or does not run after a new installation. |
| `foreign-environment` | The location exists without a valid record. |
| `inconsistent-environment` | An existing environment fails its check. |

`install` publishes no command on failure, starts no tool from `PATH`, and does
not fall back to tools that the image already provides. If a new installation
fails after the directory was created, the directory stays without a record, so
a later `install` in the same job fails with `foreign-environment`.

`install` on the existing `default` executor is rejected: that image lacks the
verified interpreter and already provides the commands. The contract does not
fix which category is reported; the current implementation reports
`interpreter`. On an unverified image, `install` may succeed, but such an image
is not supported.

### Output

`install` prints the interpreter path and version, the managed environment and
whether it was new or reused, the identifier of the pinned set, the versions of
ansible-lint, the Ansible package, and ansible-core, the exposed commands, and
the names of ignored pip settings.

### Limits

- Every job downloads the tool set from PyPI. This needs network access and
  adds time. Faster jobs are not promised.
- Exact versions do not verify the hashes of downloaded files, and they cannot
  prevent a release from being withdrawn or deleted.
- The image digest fixes the base image, and the exact versions fix the package
  set. External roles, the network, and the input files are outside both, so
  the whole result is not guaranteed to be reproducible.
- Lint findings can differ between tool versions. They are outside the
  compatibility guarantee.

## Compatibility and image updates

From 1.0.0, versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
with the following declared contract:

- Compatibility covers executor and command names, parameter names, types and
  defaults, dependency installation, execution order, and exit-code propagation.
- From 1.1.0, compatibility also covers the `python` executor and the `install`
  command, including the execution contract of `install`: Python selection, the
  managed environment, the exposed commands, pip handling, and failure behavior.
- Changes to lint findings are outside the compatibility guarantee.
- Updating the default image reference is an explicit exception to unchanged
  defaults. It requires a **minor** release when the call and execution contract
  is preserved, or a **major** release when it is not.
- The same rule applies to a new digest for a rebuilt tag, even if displayed
  Python or ansible-lint versions are unchanged. Image updates are never patch
  releases under this policy.
- For the python executor path, the same rule applies to its default image and
  to the pinned tool set of `install`, including dependency-only fixes. Adding
  a verified image without changing a default is a **minor** release.
- Other compatible bug fixes that update neither default environment can be
  patch releases. Incompatible public API changes require a major release.

The default environments of the two paths can be updated independently, in the
same release or in different releases. If the update of one path fails
verification, that path keeps its current default. Every release still runs
the baseline comparison, the six existing integration categories, and the
checks of the python executor path.

To update the default image of the `default` executor:

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

From 1.1.0, such an update also follows
[section 5.6 of the contract](docs/python-install-contract.md#56-comparison-for-releases-after-110):
the candidate is compared with the previous published release after the
intended difference is adopted.

To update the default image or the pinned tool set of the python executor path,
follow [section 14.4 of the contract](docs/python-install-contract.md#144-update-procedure-of-the-new-path).
In outline:

1. Select a new `cimg/python` digest and platform, or new package versions.
2. Measure the prerequisites
   ([section 7.1](docs/python-install-contract.md#71-preconditions)) and fix the
   whole set ([section 12](docs/python-install-contract.md#12-fixed-tool-set)).
3. In the same change, update the defaults and the pinned set in `src/`,
   `python-image-lock.json` or `python-install-lock.json`, this README, and
   `CHANGELOG.md`.
4. Store the baseline of the previous release, have the expected differences
   adopted, and run the comparison and all required checks
   ([section 5.6](docs/python-install-contract.md#56-comparison-for-releases-after-110)).
5. Choose minor or major
   ([section 14.1](docs/python-install-contract.md#141-release-type-of-environment-changes)),
   then recheck the final candidate and the tag pipeline before publication.
6. If the update changes the contract, follow
   [section 20](docs/python-install-contract.md#20-adoption-and-change-control)
   first.

Adding another verified image follows
[section 7.5](docs/python-install-contract.md#75-adding-an-image-to-the-verified-list).

Consumers that need independence from future default-image updates can set
`image` of the `default` executor to their own full digest reference. The
`python` executor supports only verified images; to keep its image and tool
set, keep the Orb reference at the same version.

## Updating from 1.0.0

After 1.1.0 is published, change the Orb reference from
`orbss/ansible-lint@1.0.0` to `orbss/ansible-lint@1.1.0`. No other change is
needed. The `default` and `execute` definitions, the default GHCR image digest,
the execution steps, and exit-code propagation are unchanged; CI compares both
pack outputs of the release with the published 1.0.0 source. Using the python
executor path is optional.

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
