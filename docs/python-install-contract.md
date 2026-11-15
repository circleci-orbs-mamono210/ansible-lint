# Contract: `python` executor and `install` command

This document is the detailed contract for the new path planned for
`orbss/ansible-lint@1.1.0`. The new path is the `python` executor, then the
`install` command, then the existing `execute` command. The document also
records the published 1.0.0 definitions that 1.1.0 must keep unchanged.

## 1. Status and scope

| Item | Value |
| --- | --- |
| Status | This file does not record its own adoption. A commit of this file is the adopted contract only when Redmine records its adoption with that commit SHA: #5535 for the first version, or the ticket that changes it later (section 20). Text without such a record is a draft. |
| Target release | `orbss/ansible-lint@1.1.0` (planned, not published) |
| Plan | Redmine project 319, Wiki `110_ロードマップ` version 1, Phase 1 |
| Earlier plan | Redmine project 319, Wiki `100_ロードマップ` version 4 (the base named by `110_ロードマップ`). Version 5 was also checked on 2026-11-15. |
| Baseline | Published `orbss/ansible-lint@1.0.0`, commit `11e4054185ab52907cdb855d37d05694f8ba1318`, publication record #5503 journal 11186 |
| Repository state when drafted | `main` at `11e4054185ab52907cdb855d37d05694f8ba1318` |
| Drafted | 2026-11-15 (JST) |

- The `python` executor and the `install` command do not exist in 1.0.0.
- This document does not show that they are implemented, tested, or published.
- Values marked **TBD** are filled by measurement in the named ticket
  (section 19.3). Until then they are not facts.
- Section 18 shows which decisions come from the plan, which the human chose
  on 2026-11-15, and which were proposed in this document for adoption.

Out of scope: the install implementation, measuring the `cimg/python` digest,
installing every dependency version, fixing private helpers or internal paths,
renaming existing API elements, and editing the formal roadmap without
approval.

## 2. Document roles and precedence

| Source | Role |
| --- | --- |
| This document | Detailed contract of the new path, the 1.0.0 baseline and comparison rule, and the release-type policy of the new path's environment |
| `src/` | API definitions as implemented. Existing elements stay as published in 1.0.0. |
| `README.md` | Usage. It links here and must not define a different contract. |
| `tests/baseline/orbss-ansible-lint-1.0.0.json` | Machine-readable identity of the 1.0.0 baseline that CI uses for 1.1.0 |
| `110_ロードマップ` version 1 | Plan. Its design principle 1 is the source of the baseline values and comparison conditions. This document makes them concrete. |

When this document disagrees with `src/`, README, a ticket, or the roadmap, do
not merge the statements silently. Report the conflicting statements and
resolve them with section 20. A ticket does not override this contract
automatically.

## 3. Terms

| Term | Meaning |
| --- | --- |
| Existing path | `ansible-lint/default` executor, then `ansible-lint/execute` (the 1.0.0 API) |
| New path | `ansible-lint/python` executor, or a direct Docker job with a verified image, then `ansible-lint/install`, then `ansible-lint/execute` |
| Verified image | An image whose exact digest and platform are in the verified image record and passed the verification set of section 7.5 |
| Verified interpreter | The Python interpreter of a verified image, identified by its absolute path and exact version |
| Managed environment | The Python virtual environment that `install` creates and owns |
| Fixed set | The exact versions of ansible-lint, the Ansible package, ansible-core, and all their Python dependencies that `install` installs |
| Exposed commands | The commands from the managed environment that `install` makes available to later steps |
| Contract commit | A commit that contains an adopted version of this document |
| Policy 01, decisions 01 to 08 | 方針01 and 決定01 to 決定08 of `110_ロードマップ` version 1 (section 18.1) |
| Design principle N | 設計原則 N of `110_ロードマップ` version 1 |

## 4. Existing API invariants

1.1.0 keeps the following from 1.0.0 (design principle 1 of
`110_ロードマップ` version 1).

| Existing element | Kept in 1.1.0 |
| --- | --- |
| `default.image` | string. The default stays the GHCR digest reference below. |
| `default.resource_class` | enum `small`, `medium`, `medium+`, `large`. Default `small`. |
| `execute.molecule-role-test` | boolean. Default `false`. |
| `execute.molecule-playbook-test` | boolean. Default `false`. |
| `execute` steps | Version display, the existing dependency installation, and `ansible-lint` without arguments |
| Lint exit code | The final lint step returns the real exit code unchanged. |
| Explicit image | Overriding `default.image` works as in 1.0.0. |
| Descriptions | The descriptions of both elements stay unchanged. New explanations go to README, the new elements, or the Orb description. |

The default image stays this reference:

```text
ghcr.io/docker-images-mamono210/circleci-executors/ansible-lint@sha256:3dd0b103851b24ea8796af7126fff4340023a6288293030ae65b01f0446a9fdf
```

- Adding the new elements does not change the image, PATH, or Python
  environment of the existing path.
- The existing path never requires an `install` step.
- Existing parameter names stay kebab-case. The RC010 review exclusion
  continues for this reason until a later major release.

These invariants apply to the 1.1.0 release. A later release may change an
existing element only under the 1.0.0 compatibility policy in README, for
example a minor release that updates the default GHCR image. Section 5.6
defines how such a change is compared and adopted.

## 5. Baseline comparison

The baseline comparison checks that a release candidate changes published
definitions only as adopted. Sections 5.1 to 5.5 define it for 1.1.0, whose
baseline is the published 1.0.0 and which allows no difference. Section 5.6
defines it for later releases.

### 5.1 Identity of the 1.0.0 baseline

| Item | Value |
| --- | --- |
| Orb version | `orbss/ansible-lint@1.0.0` |
| Registry version ID | `8e93a6ed-6018-4475-8be7-75a6c52693b4` |
| Published at | `2026-11-10T13:48:23.009Z` |
| Git tag | `v1.0.0` (lightweight) |
| Commit | `11e4054185ab52907cdb855d37d05694f8ba1318` |
| Repository tree | `e918a4908e0e37d403e982781092f085cd67b445` |
| Orb source tree (`src`) | `895c9f12cf8f60c2bbfeeca526270b178c9a1852` |
| Source size | 4,033 bytes |
| Source SHA-256 | `d05c1fbad47421bbb239d2fe670039936445c493ebfff78f7fa2073285b124bb` |

These values come from #5503 journal 11186 and `110_ロードマップ` version 1.
According to that journal, the injection and publication packs of tag
pipeline 67 had the same packed SHA-256. These values identify the 1.0.0
publication. They do not show that 1.1.0 is verified or published.

### 5.2 Stored copy

| File | Role |
| --- | --- |
| `tests/baseline/orbss-ansible-lint-1.0.0.yml` | The exact registry source bytes |
| `tests/baseline/orbss-ansible-lint-1.0.0.json` | Identity record, including the expected size and SHA-256 that CI uses |

How the copy was obtained:

- On 2026-11-15 the registry source of `orbss/ansible-lint@1.0.0` was
  retrieved with the CircleCI MCP server tool `get_orb_source`.
- The returned string was written as UTF-8 bytes without other changes.
- Its size (4,033 bytes) and SHA-256 matched the recorded values.
- It was not produced by repacking `src/` and was not copied from a CI
  artifact.
- A local parse also found that its `executors.default` and
  `commands.execute` equal `src/` at the tag commit after the script include
  is expanded. This is a supporting observation, not the CI check.

A person can recheck the copy with `sha256sum` and `wc -c`. Any retrieval
method is acceptable when the bytes have the expected size and SHA-256. Tools
that print a source can add or remove a trailing newline, so verify the bytes
before use.

The copy is under `tests/` with the other CI records. It is outside `src/`, so
the pack does not include it. `orb-tools/lint` 12.5.0 lints `src` by default,
so it does not lint the copy. The file name does not match the `orb.yml`
pattern in `.gitignore`.

### 5.3 CI reference and the hash check before each comparison

#5538 implements the comparison for 1.1.0 under these rules. The same rules
apply to the baseline of a later release (section 5.6).

1. CI reads the stored copy from the checkout of the candidate commit. CI does
   not download the baseline during the check.
2. Before every comparison, CI checks the size and SHA-256 of the stored copy
   against the expected values in the identity record. For 1.0.0, those values
   equal #5503 journal 11186 and design principle 1.
3. A missing file, an unreadable file, or a mismatch fails the check. The
   comparison does not run in that case.
4. CI never replaces the stored copy or the expected values automatically.
   A repack by any CLI is never a substitute.
5. A change to the stored copy or the expected values is a contract change
   (section 20).

### 5.4 Comparison targets and equality rule for 1.1.0

Targets:

- `executors.default` and `commands.execute`. No difference from the 1.0.0
  baseline is allowed, including the default image digest.
- From both actual pack outputs: the injection pack of the setup workflow and
  the publication pack of the continuation workflow.
- Each output is read from `./orb.yml` inside that job's
  `dist/orb_source.tar.gz`. It is not repacked.

Equality rule:

- Both sides are parsed with the same YAML parser and schema. #5538 records
  the parser and schema with its evidence.
- Only mapping key order and comments are ignored.
- Everything else must be equal. This includes:
  - the set of keys at every level;
  - sequence order and length;
  - resolved scalar types, for example boolean `false` against string
    `"false"`;
  - scalar values byte for byte, including whitespace and trailing newlines
    in block scalars;
  - descriptions, parameter types, defaults, and enum values;
  - steps, step names, environment maps, and embedded scripts;
  - the default image digest string.
- Quoting and block or flow style disappear when the YAML is parsed, so they
  are not compared as text. A change that alters a parsed value still fails.
- The pack jobs use the default executor of orb-tools 12.5.0, whose CLI image
  tag defaults to `latest`. The text form of pack output can therefore change
  between runs. The parsed comparison is designed for this.
- The hash of the whole Orb is not required to match the baseline. 1.1.0 adds
  elements and changes Orb metadata.
- Other parts of the Orb are not compared with the baseline: the Orb
  description, `display`, examples, and the new elements.
- The final release candidate repeats the comparison (#5541). Results from
  another commit are not reused.

### 5.5 When a difference appears in 1.1.0

Any difference in the two targets fails the publication condition of 1.1.0.
If a difference seems necessary, stop. Show the human the difference and its
conflict with section 4. The plan, this contract, and the release type are
then reviewed. Such a change is not released as a compatible 1.1.0 addition.

### 5.6 Comparison for releases after 1.1.0

The 1.0.0 baseline and the no-difference rule apply to 1.1.0 only. A later
release may change published definitions within the compatibility policy,
for example the default image of either path (section 14). Each later release
is compared as follows.

1. **Baseline**: the published source of the version that the release
   follows, normally the latest published version. For example, a 1.2.0
   candidate is compared with the published 1.1.0 source.
2. **Storage and hash check**: the baseline is stored and identified as in
   section 5.2. Its size and SHA-256 come from the publication record of that
   version, for example the record of #5541 for 1.1.0. Section 5.3 applies,
   including the check before every comparison.
3. **Targets**: every executor, command, and job in the baseline. After 1.1.0
   these are the executors `default` and `python` and the commands `execute`
   and `install`. Examples and Orb metadata are not compared.
4. **Equality**: the rule of section 5.4.
5. **Expected differences**: before the comparison, the human adopts a list of
   the differences that the release intends. Each entry gives the element,
   the path inside it, the old and new values, the reason, and the release
   type under section 14.1 and README. The list is stored in the repository
   next to the baseline. Its file name is chosen when it is first needed.
6. **Result**: the comparison passes only when every difference found is in
   the adopted list and every listed difference is found.
7. **Adoption**: the new baseline files and the list are recorded in Redmine
   with the commit that contains them, as in section 20. CI uses the list in
   the candidate commit. A release is not published until Redmine records the
   adoption of that list.

Example: a minor release that updates only the default GHCR image lists one
difference, `executors.default.parameters.image.default`, with the old and new
digest references. Any other difference fails the comparison.

A difference that breaks the call or execution contract needs a major
release. Changing the rules of this section is a contract change
(section 20).

## 6. New public elements

### 6.1 Executor `python`

The `python` executor is a Docker executor that uses a CircleCI `cimg/python`
image pinned by digest (decision 02).

| Parameter | Type | Default |
| --- | --- | --- |
| `image` | string | The verified `cimg/python` digest reference, in the form `cimg/python@sha256:<digest>`. The exact value is **TBD** by #5536. |
| `resource_class` | enum `small`, `medium`, `medium+`, `large` | `small` |

- `resource_class` has the same type, values, default, and spelling as
  `default.resource_class`.
- 1.1.0 adds no other parameters.
- The executor does not install ansible-lint or any other tool when a job
  starts.
- The executor does not detect a Python change caused by checkout. `install`
  selects Python (section 8.1).
- The definition file is `src/executors/python.yml`. The file name follows
  the element name.
- `image` and `resource_class` use the same spelling as the existing
  `default` executor. This exception does not extend to other parameter
  additions (design principle 5).

Overriding `image` is possible. Support covers only verified images
(section 7.4).

### 6.2 Command `install`

- 1.1.0 gives `install` no public parameters (decision 04). No test-only
  parameter is added.
- Responsibility: prepare, in the same job, the tools that a later `execute`
  uses. `install` creates the managed environment with the verified
  interpreter, installs the fixed set, verifies the result, and then exposes
  the commands.
- Not its responsibility: checkout, installing roles or collections, running
  lint, installing Python or OS packages, caching, and carrying the
  environment to another job.
- The implementation and the fixed set are part of the published Orb.
  A consumer repository needs no extra file.
- The definition file is `src/commands/install.yml`. Script layout is chosen
  by #5537.
- A user who needs other versions can prepare their own environment and use
  `execute`. Such environments are outside this contract.

### 6.3 Description policy

#5536 and #5537 write the final wording. README explains details (#5540).

| Element | The description must state | The description must not state |
| --- | --- | --- |
| `python` executor | It is a `cimg/python` Docker executor pinned by digest. It does not contain ansible-lint. Run `install` before `execute`. | That tools are preinstalled. That any image works. |
| `python.image` | The default is a verified digest. Overriding is possible, but support is limited to verified images. A tag alone does not pin content. | That an overridden image is supported. |
| `python.resource_class` | The same meaning as `default.resource_class`: the CircleCI resource class of this Docker executor. | Anything beyond that meaning. |
| `install` | It installs the pinned tool set into an Orb-managed environment for later steps of the same job. It requires the verified Python. It has no parameters. It needs network access to PyPI. | Faster jobs. Reproducible results in general. Support for unverified images. |
| `default`, `execute` | Unchanged | Unchanged |

### 6.4 Planned usage

The following is a planned configuration, not a published example. The
standard order is checkout, then `install`, then `execute`.

```yaml
version: 2.1

orbs:
  ansible-lint: orbss/ansible-lint@1.1.0

jobs:
  lint:
    executor: ansible-lint/python
    steps:
      - checkout
      - ansible-lint/install
      - ansible-lint/execute

workflows:
  lint:
    jobs:
      - lint
```

Role and playbook settings are passed to `execute` as in 1.0.0. A job uses one
path. Existing users can keep `default` and `execute` after updating to 1.1.0.

## 7. Supported environment

### 7.1 Preconditions

#5536 measures each precondition for the verified image and records the
result.

| Precondition | Requirement | Who checks |
| --- | --- | --- |
| OS and architecture | Linux on amd64 (x86_64) | #5536 records the platform. `install` checks it at run time. |
| Shell | Run steps use Bash. Later steps receive the PATH change through `BASH_ENV`. | #5536 |
| Python | The verified interpreter, with the absolute path and exact version from the verified image record. The first candidate is Python 3.14.10. | #5536 measures. `install` checks it (section 8.1). |
| Virtual environments | The verified interpreter can create a virtual environment with pip available. | #5536 measures. `install` checks it. |
| Permissions | The job user can write the managed environment location without sudo. | #5536 and #5537 |
| Network | HTTPS access to the default PyPI index and its file host | Needed by each `install` run |
| Git and role sources | Needed by `execute` for role installation from repositories, as in 1.0.0 | Existing behavior |

Not supported: macOS, Windows, the machine executor, Arm, and other Python
lines. `install` never installs Python or OS packages and never needs sudo.

### 7.2 Verified images

- A verified image is identified by its full digest reference and platform,
  not by a tag.
- For an image index, the record keeps the index digest and the digest of the
  `linux/amd64` manifest.
- Each entry records: repository, the reference used, manifest digest, index
  digest if any, platform, tag at selection, resolution time, verified
  interpreter path and version, pip version, Bash and Git availability, the
  virtual environment check, and evidence (commit and job URLs).
- #5536 creates the record file and chooses its name. It is separate from
  `image-lock.json`, which stays the record of the existing GHCR image.
- At 1.1.0 the list is expected to have one entry: the default image of
  `python`. Other images are added only under section 7.5.

### 7.3 Direct Docker jobs with the same digest

A job may write the exact verified digest reference in its own `docker`
section (decision 03). Such a job is supported like the `python` executor.

```yaml
jobs:
  lint:
    docker:
      - image: cimg/python@sha256:<verified digest, TBD by #5536>
    steps:
      - checkout
      - ansible-lint/install
      - ansible-lint/execute
```

Arm resource classes are not supported.

### 7.4 Overriding `image`

- Overriding `python.image` stays possible.
- Support covers only images in the verified record.
- An image is not supported just because the configuration is accepted, the
  image is pulled, or the job starts.
- An unverified image is never described as supported.

### 7.5 Adding an image to the verified list

All of the following must pass on a candidate Orb. The evidence records the
commit, image reference, platform, versions, and job URLs.

1. The precondition measurements of section 7.1 in that image.
2. Checkout, `install`, and `execute` in a `python` executor job that uses the
   image.
3. The same steps in a direct Docker job with the same digest.
4. Python selection after checkout (section 8.1) and command resolution in a
   separate run step (section 10).
5. The image-dependent failure cases that section 13 marks as measured.
6. The normal, role, playbook, and negative cases of the new path from the
   Phase 4 table of `110_ロードマップ` version 1.

An image used only to check that an override reaches the job (setting
reflection and start-up) is not added to the list. Adding an image without
changing any default is a minor release (section 14.1).

## 8. Python selection, step order, and unsupported images

### 8.1 Explicit Python selection

This section implements decision 06.

- `install` uses only the verified interpreter. Its absolute path and exact
  version come from the fixed information of the Orb for the verified image.
- `install` does not select Python by command lookup (`python` or `python3`
  on PATH), pyenv shims, `.python-version`, `PYENV_VERSION`, or similar
  version-manager settings.
- According to `110_ロードマップ` version 1, `cimg/python` places Python with
  pyenv. #5536 and #5537 measure the effect of `.python-version` on the
  adopted image.
- Before creating the managed environment, `install` checks that the path
  exists and is executable, that it reports the exact recorded version, and
  that it can create a virtual environment.
- If a check fails, `install` exits non-zero. It publishes nothing and does
  not fall back to another Python.
- `install` never writes, deletes, or changes `.python-version`, pyenv
  settings, or other version-manager configuration.

### 8.2 Step order

| Order | Status |
| --- | --- |
| checkout, `install`, `execute` | Supported. This is the standard order. |
| `install`, checkout, `execute` | Supported. `install` must not read from or write to the working directory, and the managed environment is outside the checkout. #5539 measures this order. |
| `execute` before `install` on `python` | Not a supported order. `execute` keeps its 1.0.0 behavior, so its first missing command fails. No new handling is added. |

Calling `install` more than once in a job is covered by section 9.3.

### 8.3 Decision table for images and order

Classes:

- **Supported**: guaranteed and verified.
- **Rejected**: `install` exits non-zero before it publishes any command.
- **Unsupported, not rejected**: `install` cannot detect the condition. It may
  run, but nothing is guaranteed, and documentation calls it unsupported.

Before it creates the managed environment, `install` also checks for tools
that are already present. If any command that `install` would expose already
resolves on PATH outside the managed environment, `install` fails. It does
not shadow tools that the image or the user already provides. A consistent
re-invocation (section 9.3) is not affected, because its commands resolve
inside the managed environment. A test observer that wraps an exposed command
is therefore set up after `install`.

| ID | Condition | Class | Expected result | Evidence |
| --- | --- | --- | --- | --- |
| E1 | `python` executor with its default image; checkout, `install`, `execute` | Supported | `install` succeeds. `execute` uses the managed environment. The lint result follows the `execute` contract. | #5536 (pull and start), #5537 (minimal CI), #5539 |
| E2 | As E1, with `install` before checkout | Supported | Same as E1 | #5539 measures |
| E3 | Direct Docker job with the same verified digest; checkout, `install`, `execute` | Supported | Same as E1 | #5539 measures |
| E4 | `python` executor whose `image` is another image in the verified record | Supported only after section 7.5 | Same as E1 | Section 7.5 for that image |
| E5 | Image without the verified interpreter: the path is missing or the version differs | Rejected | `install` exits non-zero before creating the environment. Nothing is published. | #5537 structural check; #5539 measures |
| E6 | Image that already provides a command of the exposed set on PATH | Rejected | `install` exits non-zero. Existing tools and PATH stay unchanged. Success is never reported through the existing tools. | #5537 structural check; #5539 measures with E7 |
| E7 | Existing `default` executor (GHCR digest) with `install` | Rejected, through E6 and possibly E5 | As E6 | #5539 measures. If `install` does not fail there, that is a contract mismatch handled under section 20.3. |
| E8 | Unverified image that has the verified interpreter at the same path and version and none of the exposed commands | Unsupported, not rejected | `install` may succeed. Nothing is guaranteed. It is never documented as supported. | #5540 documents it |
| E9 | Platform other than Linux on amd64 | Rejected | `install` exits non-zero before creating the environment. | #5537 structural check |
| E10 | Verified interpreter present but unable to create a virtual environment | Rejected | `install` exits non-zero. Nothing is published. | #5537 structural check; measured if reproducible |
| E11 | `execute` before `install` on `python` | Not a supported order | 1.0.0 behavior: the first missing command fails. | No new test |

## 9. Managed environment

### 9.1 Location and ownership

- Each job has at most one managed environment, in a directory dedicated to
  this Orb.
- It is outside the working directory and any checkout, outside system
  Python, and not inside an existing virtual environment.
- The job user can write it without sudo. The exact path is a private detail
  chosen by #5537. README tells users where it is (#5540).
- `install` creates the environment only when the target path does not exist.
- `install` writes a state record inside the environment. The record holds at
  least the Orb identifier, a fixed-set identifier (for example a SHA-256 of
  the fixed information), the interpreter path and version, and a completion
  marker written last. Its format is private.
- A directory is managed and complete only when the record exists, is
  well-formed, and has the completion marker.

### 9.2 Lifetime

- The managed environment exists for one job.
- It is not shared with other jobs. It is not saved to or restored from a
  cache.
- Persisting it through caches or workspaces is unsupported.

### 9.3 Environment check and states at each invocation

The environment check has three parts. It is the only definition of a
correct managed environment. `install` uses it after a new installation and
whenever it finds an existing environment.

1. **Record**: the state record is well-formed, has the completion marker,
   and matches the current fixed-set identifier and the verified interpreter
   (path and version).
2. **Distributions**: the complete set of installed distributions, by name
   and version, equals the expected set. The expected set is the fixed set
   plus each bootstrap distribution recorded for the verified interpreter that
   the fixed set does not pin, for example the pip created with the
   environment. Nothing may be missing, extra, or of another version.
3. **Commands**: every exposed command and every required CLI (section 10.4)
   exists in the managed environment and runs.

After a new installation, `install` checks parts 2 and 3 first. It writes the
state record, with the completion marker last, only after both pass.

| State | Detected when | `install` does | Changes allowed | Effect on later steps | Evidence |
| --- | --- | --- | --- | --- | --- |
| S0 Absent | The target path does not exist. | Creates the environment and installs the fixed set. Checks parts 2 and 3, writes the state record, then publishes. | Creates only the environment and its record. | Exposed commands are published only after the check passes. | #5537 minimal CI; #5539 |
| S1 Consistent | A well-formed state record exists, and all three parts of the check pass. | Reuses the environment. No download or reinstall. | None | Command resolution stays the same. Whether the PATH entry is written again is an implementation detail. | #5539 measures |
| S2 Inconsistent | A well-formed state record exists, but a part of the check fails. Examples: another Orb version, fixed set, or interpreter in the record; no completion marker; added, removed, or changed distributions; a missing command; a broken interpreter. | Stops with a non-zero exit. | None. No repair and no deletion. | Nothing new is published. | #5539 measures a mismatch and a missing CLI |
| S3 Foreign | The target path exists without a well-formed state record. | Stops with a non-zero exit. | None | Nothing is published. | #5539 measures |
| S4 Changed by the user | A later step modified the managed environment, for example with pip. | Nothing until `install` runs again. Then the state is S2. | None | `execute` then runs on a modified environment, outside the guarantee. | #5540 documents it; the S2 measurement covers the next invocation |

If `install` fails after creating directories, it may remove only what it
created in the same invocation. If it leaves them, the record has no
completion marker, so the next invocation stops as S2.

### 9.4 What `install` never changes

- System Python, version-manager settings, the user's virtual environments,
  or any content it did not create.
- Files in the working directory or a checkout.
- A third-party environment, even when it looks similar.

`install` never uses sudo and never installs OS packages.

### 9.5 Output

`install` prints at least the following, without secret values:

- the selected interpreter path and version;
- the managed environment location and the fixed-set identifier;
- the versions of ansible-lint, the Ansible package, and ansible-core;
- the exposed command list;
- the names of ignored pip settings (section 11).

## 10. Command exposure and effects on later steps

### 10.1 Exposed commands

The human chose this scope on 2026-11-15.

- `install` exposes only executables in the managed environment whose names
  start with `ansible` and that the fixed set provides.
- The scope includes `ansible-lint`, `ansible`, `ansible-community`, and
  `ansible-galaxy`, which `execute` uses directly. It also includes other
  Ansible CLIs of the fixed set, such as `ansible-playbook` and
  `ansible-config`.
- `install` does not expose `python`, `python3`, `pip`, `pip3`, or other
  console scripts of dependencies.
- `install` uses a dedicated directory that holds only links or wrappers for
  the exposed commands. Later run steps get that directory at the front of
  PATH through `BASH_ENV`. #5537 chooses the details.
- #5537 records the exact command list for the adopted versions in the fixed
  information. README documents it (#5540).

### 10.2 When commands are published

- Only after S0 succeeds, including verification, or after S1 is confirmed.
- Never on failure. After a failed `install`, later steps resolve commands as
  they did before.

### 10.3 Effects on python, pip, and other commands

- Later run steps resolve `python`, `python3`, `pip`, and `pip3` as before
  `install`.
- The exposed commands resolve to the managed environment. Because of
  section 8.3, `install` never shadows a command that existed before it ran.
- `install` changes no environment variable of later steps other than PATH.
  This includes `PYTHONPATH`, `VIRTUAL_ENV`, `PIP_*`, `PYENV_*`, and
  `ANSIBLE_*`.
- Steps that use a shell other than Bash, or that reset PATH, are outside the
  guarantee.
- If a later step installs packages into the managed environment, the state
  becomes S4.

### 10.4 Required Ansible CLIs

This section implements design principle 3.

- `execute` uses `ansible-lint`, `ansible`, `ansible-community`, and
  `ansible-galaxy` directly. Installing ansible-lint alone is not enough.
- #5537 investigates whether the adopted ansible-lint starts other CLIs at run
  time, for example as subprocesses. It records each such CLI and where it
  resolves. If there are none, it records the basis for that conclusion.
- Every required CLI must resolve inside the managed environment through the
  exposed set.
- If a required CLI does not start with `ansible`, or cannot be exposed under
  section 10.1, stop. This needs a contract change (section 20). Do not widen
  the exposure silently.
- #5539 measures in a separate run step that the four direct commands and
  every required CLI resolve to the managed environment, and that `python`
  and `pip` resolve as before.
- `ansible --version` reports ansible-core. `ansible-community --version`
  reports the Ansible package. They are recorded separately.

## 11. pip configuration and environment variables

The human chose this policy on 2026-11-15.

`install` does not apply the consumer's pip configuration. pip configuration
files at every level, including a file named by `PIP_CONFIG_FILE`, and all
`PIP_*` environment variables have no effect on `install`.

| Category | Examples | Handling |
| --- | --- | --- |
| Source | Index URL, extra index, find-links, trusted host | Not applied. Downloads use the default PyPI index only. |
| Network | pip proxy and certificate settings in configuration files or `PIP_*` | Not applied. The Orb neither sets nor removes general process environment variables such as the standard proxy variables. Whether pip uses those is pip's own behavior. Success is not guaranteed where a proxy, a custom CA, or a mirror is required. |
| Dependency constraints | Constraints or requirements files, upgrade strategy, pre-releases, no-deps, binary or source selection, build isolation | Not applied. Only the fixed set (section 12) decides what is installed. |
| Destination | Target, prefix, root, user installs | Not applied. Packages go only into the managed environment. |
| Other behavior | Cache directory, verbosity, version check, timeout, retries, keyring | Not applied. |

- #5537 chooses the mechanism, for example pip's isolated mode, and verifies
  that it covers every category above.
- When `PIP_*` variables or pip configuration files are present, `install`
  prints their names and states that they were ignored. It never prints their
  values, because values can contain credentials.
- After installation, the environment check of section 9.3 must pass. Its
  distribution part accepts only the fixed set and the recorded bootstrap
  distributions. A missing, extra, or different version fails `install`, and
  nothing is published.
- `install` does not upgrade bootstrap tools unless the fixed set pins them.
- #5539 measures this policy. It runs `install` with conflicting pip settings,
  for example a `PIP_INDEX_URL` that points to an unreachable host, a pip
  configuration file with another index, and a destination setting. The
  expected result is that `install` still installs the fixed set into the
  managed environment and logs only the setting names.
- 1.1.0 has no public parameter for pip settings (decision 04).

Sources, constraints, and destination are fixed, and the installed result is
checked. No undefined way remains to override the exact versions.

## 12. Fixed tool set

This section implements decision 05 and design principle 4.

- First candidates: Python 3.14.10, Ansible package 14.5.0, ansible-core
  2.21.5, and ansible-lint 26.10.1. These are the measured versions of the
  existing GHCR image. They do not show that a matching `cimg/python` image
  exists or that installation succeeds.
- #5537 installs the first candidates on the selected image and resolves all
  Python dependencies. It then fixes the exact versions of the whole set and
  records the installed list with evidence.
- The fixed information is part of the published Orb. #5537 chooses its
  format and internal location. No file is needed in the consumer repository.
- If the first candidates do not work, show the human the difference and the
  reason. After adoption, update this contract (section 20). Never adopt
  other versions silently.

Limits:

- The image digest fixes the base environment. The exact versions fix the
  package set. These are separate responsibilities.
- Exact versions do not verify the hashes of downloaded files. They do not
  prevent a release from being withdrawn or deleted.
- Hash pinning may be deferred. README states this limit (#5540).
- The whole result, including external roles, the network, and inputs, is
  not guaranteed to be reproducible.

## 13. Failure conditions and verification method

On any failure, `install`:

- exits non-zero and does not hide the original error;
- publishes no command;
- does not fall back to tools already on PATH;
- deletes nothing it did not create in the same invocation;
- prints a message that names the failure category, without secret values.

Verification methods:

- **Measured**: CI reproduces the condition under control and observes the
  failure.
- **Structural**: the behavior is traced in the source and in the actual pack.

No test-only public parameter is added. The success of a test observer is not
evidence that CircleCI ran a failing step. If a reproduction method does not
work, the test is redesigned. A required measurement is never skipped.

| ID | Condition | Required behavior | Method | Owner |
| --- | --- | --- | --- | --- |
| F1 | Platform is not Linux on amd64 | Non-zero exit before creating the environment | Structural | #5537 |
| F2 | Verified interpreter missing or of another version | Non-zero exit. No fallback. | Structural; measured with an image chosen by #5539 that lacks the verified interpreter and provides none of the exposed commands (E5) | #5537, #5539 |
| F3 | A command of the exposed set already exists on PATH outside the managed environment | Non-zero exit. Existing tools and PATH unchanged. No success through existing tools. | Measured on the existing `default` image (E7) | #5537, #5539 |
| F4 | The interpreter cannot create a virtual environment, or pip is missing | Non-zero exit | Structural; measured if reproducible | #5537, #5539 |
| F5 | The managed location is not writable | Non-zero exit | Measured, by denying write access in a test job | #5539 |
| F6 | The target path exists without a valid record (S3) | Non-zero exit. No change. | Measured | #5539 |
| F7 | Inconsistent managed environment (S2), including a removed required CLI | Non-zero exit. No change. | Measured | #5539 |
| F8 | Consistent re-invocation (S1) | Success. No reinstall. Same resolution. | Measured | #5539 |
| F9 | Download or installation fails because the package index is unreachable | Non-zero exit. Nothing published. | Measured with a CI-only network condition that makes the index unreachable inside the test job, without using pip configuration. #5539 records which production code runs unchanged and what is replaced. | #5539 |
| F10 | Dependency resolution fails, a release is withdrawn, or the network fails in another way | As F9 | Structural. F9 is the representative measurement. | #5537, #5539 |
| F11 | Installed distributions differ from the expected set of section 9.3 | Non-zero exit. Nothing published. | Structural; measured through F7 | #5537, #5539 |
| F12 | Pip settings of the consumer are present | Settings ignored. Names logged, values not. | Measured (section 11) | #5539 |
| F13 | Normal success | Commands published only after verification. A later step resolves them to the managed environment. | Measured | #5537 minimal CI, #5539 |

## 14. Version policy and maintenance after release

### 14.1 Release type of environment changes

This section implements decision 07.

| Change | Release type |
| --- | --- |
| The new path's default image (`python.image` default) or fixed set changes, and the call and execution contract is kept | minor |
| The same kind of change that does not keep the contract | major |
| Any change of the default package set, including dependency-only bug fixes | Never patch. minor or major by the rows above. |
| A bug fix of the Orb itself that changes neither default environment and keeps the contract | patch |
| Adding a verified image without changing any default (section 7.5) | minor |
| The existing path's default image | The 1.0.0 policy in README applies unchanged: minor or major, never patch. The change is compared and adopted under section 5.6. |

### 14.2 Human decision: independent updates

The human made this decision on 2026-11-15.

- The default environments of the two paths may be updated independently.
  After 1.1.0, neither path must match the other.
- Decision 05 aligns only the first candidates. It creates no obligation to
  keep the paths aligned.
- If the update of one path fails verification, that path keeps its current
  default. The update of the other path may be released without it.
- Independence does not relax release gates. Every release still needs the
  baseline comparison that applies to it (section 5.4 for 1.1.0, section 5.6
  for later releases), the six existing integration categories, and the
  checks of the new path.
- In a later release, an updated default appears in the comparison only as
  an adopted expected difference (section 5.6). The definitions of the path
  that is not updated must stay equal to the baseline.
- Updating both paths in one release is allowed. Each path is verified on its
  own.

### 14.3 Result differences and documentation

- Different tool versions can produce different lint findings for the same
  input. Lint findings are outside the compatibility guarantee, as in 1.0.0.
- README lists the default image identity and versions of each path
  separately. #5540 sets this up. Each release that changes a default
  environment updates it in the same change.
- The CHANGELOG entry of such a release states which path changed, the old
  and new versions, the release type, and the tested lint impact. If the paths
  now have different versions, the entry says so.
- Result differences between the paths are compared with the same fixtures,
  settings, and fixed external dependencies (Phase 4 of `110_ロードマップ`
  version 1). Version, environment, and result differences are recorded.
  Identical versions do not imply identical results.
- `image-lock.json` stays the record of the existing GHCR image. The new path
  has its own record (section 7.2).

### 14.4 Update procedure of the new path

#5540 adds the entry point to the "Compatibility and image updates" section
of README. The outline is:

1. Select a new `cimg/python` digest and platform, or new package versions.
2. Measure the preconditions (section 7.1) and fix the whole set (section 12).
3. In the same change, update the defaults and fixed information in `src/`,
   the verified image record, README, and CHANGELOG.
4. Store the baseline of the previous release and have the human adopt the
   expected differences (section 5.6). Then run the baseline comparison and
   all required checks.
5. Choose minor or major by section 14.1. Recheck the final candidate and the
   tag pipeline before publication.
6. If the update changes this contract, follow section 20 first.

After 1.1.0, an update of the existing path's default image follows the
README procedure of 1.0.0 and also section 5.6. #5540 adds this to README.

## 15. Changes from the 1.0.0 contract

- Added public elements: the `python` executor and the `install` command.
- Unchanged: `default`, `execute`, the default GHCR digest, the descriptions,
  the execution steps, and exit-code propagation (section 4).
- README of 1.0.0 says that the Orb does not install ansible-lint into an
  arbitrary executor. That statement describes `execute`. `install` is a
  separate command that users choose explicitly, and its support is limited
  to verified images. #5540 updates README accordingly.
- From 1.1.0 the compatibility guarantee also covers the new elements: names,
  types, defaults, and the execution contract (Python selection, managed
  environment, exposure scope, pip handling, and failure behavior). Lint
  findings stay outside the guarantee.
- The release-type policy extends to the environment of the new path
  (section 14.1).
- Existing users can keep `default` and `execute` when updating to 1.1.0.
  No `install` step is required.

## 16. Contract-sensitive impact

| Impact | Handling in this contract |
| --- | --- |
| Public API and configuration | Adds `python` (`image`, `resource_class`) and `install` (no parameters). The existing API and defaults are kept. |
| Error model | Failure conditions of `install` (section 13): non-zero exit and no publication |
| Environment boundary | Managed environment ownership (section 9), exposure (section 10), pip isolation (section 11) |
| Backward compatibility | Baseline comparison (section 5): with the 1.0.0 baseline and no difference for 1.1.0, then with the previous release and adopted expected differences. The existing regression tests stay required. |
| Release contract | Release types (section 14.1), independent updates (section 14.2), publication conditions (section 19) |

The invariants of the existing API are not relaxed.

## 17. Relationship to the 1.0.0 roadmap

`110_ロードマップ` version 1, design principle 5, sets the boundary against the
later plans of `100_ロードマップ` version 4. Version 5 of `100_ロードマップ` was
checked on 2026-11-15.

| Topic | Section of version 4 | Boundary and reason | State in version 5 |
| --- | --- | --- | --- |
| Timing of `install` | 「2.1.0 以降: 機能追加(互換)」 | `install` moves forward to an independent 1.1.0 command. Later candidates stop listing it as new. | Reflected: the first `install` moves to 1.1.0. |
| Use of `cimg/python` | Decision items of 「2.0.0: 正常化 release(breaking)」 | 1.1.0 adds a separate `python` executor. Replacing `default` is not decided. | Reflected: the 2.0.0 item asks whether to replace `default` with the new path. |
| Order of parameter additions | End of 「2.1.0 以降: 機能追加(互換)」 | Only `image` and `resource_class` of the new executor are an exception, with the same spelling as `default`. `execute` gets no new parameter. | Reflected |
| Alignment with yamllint | Start of 「2.1.0 以降: 機能追加(互換)」 | `python` and `install` are adopted. Full alignment with yamllint is not a 1.1.0 condition. The general policy for future features remains. | Reflected |
| Order of later releases | 「順序の推奨」 | 1.1.0 comes after 1.0.0. Renaming and removing the RC010 exclusion stay with a later major. The timing of 2.0.0 and replacing `default` are separate decisions. | Reflected |
| Consumer migration | 「利用側リポジトリの移行(別案件)」 | 1.0.0 users can keep the existing path in 1.1.0. The new path is chosen explicitly. Bulk migration is a separate project. | Reflected |
| Precondition of `ansible-community` | Decision items of 「2.0.0: 正常化 release(breaking)」 | Plain `cimg/python` and the environment after `install` are different. Whether version display works after installing the Ansible package is verified. Neither removal of the display nor a fix of earlier failures is asserted. | Reflected in the 2.0.0 decision item |
| Ongoing maintenance | 「継続的な保守」 | The digest and package set of the new path are maintained separately. Release types follow decision 07. The synchronization policy is decided in Phase 1. | Reflected. The decision is section 14.2 (independent updates). |
| Redmine follow-up | 「Redmine 側」 | The 1.1.0 Version and `110_ロードマップ` are added. Closing the 1.0.0 Version and creating 2.0.0 need separate approval. | Reflected |
| 1.0.0 Phases 1 to 6 | Each Phase and the Release Boundary | Not renumbered or reused. The Phases of `110_ロードマップ` belong to 1.1.0 only. | Unchanged |

Version 5 reflects all ten boundaries. This contract proposes no further change
to `100_ロードマップ`. Version 5 still says, under 「継続的な保守」, that the
human decides the synchronization policy in 1.1.0 Phase 1. After this document
is adopted, the human may choose to point that line to section 14.2. Such an
edit needs a concrete proposal and approval. It is not made automatically.

## 18. Plan decisions and Phase 1 decisions

### 18.1 Decisions adopted in the plan

| ID | Content | Section |
| --- | --- | --- |
| 方針01 | Keep `default`, `execute`, and the GHCR digest. Add the new path as an explicit choice. | 4, 5, 15 |
| 決定01 | The detailed contract is a new repository document. The human adopts it and the commit is identified. | This document, 20 |
| 決定02 | Adopt `python`, `install`, `image`, and `resource_class`. Full alignment with yamllint is not a release condition. | 6 |
| 決定03 | `install` can be used in a direct Docker job with the same verified image. Arbitrary images are not guaranteed. | 7.3, 7.4 |
| 決定04 | `install` has no public parameters. Pip handling is defined in Phase 1. No test-only parameters. | 6.2, 11, 13 |
| 決定05 | The first candidates are the versions of the existing GHCR image, measured on `cimg/python`. Changes are shown to the human with reasons. | 12, 19.3 |
| 決定06 | Select the verified Python explicitly. Fail if it cannot be identified or used. | 8.1, 13 |
| 決定07 | Environment changes are minor when the contract is kept and major otherwise. Never patch. | 14.1 |
| 決定08 | 1.1.0 details are in `110_ロードマップ`. `100_ロードマップ` keeps the 1.0.0 Phases and organizes later plans. | 17 |

### 18.2 Decisions of Phase 1

All items are adopted together with this document (section 20). The human may
change any proposal before adoption.

| Item | Decision | Basis |
| --- | --- | --- |
| Version alignment after release | Independent updates allowed (section 14.2) | Human decision, 2026-11-15 |
| Exposure scope | Only `ansible*` commands. `python` and `pip` unchanged. (section 10) | Human decision, 2026-11-15 |
| Consumer pip settings | Not applied. Names logged, values not. (section 11) | Human decision, 2026-11-15 |
| `install` before checkout | Supported and measured (section 8.2) | Proposed in this document |
| Unverified images and the existing `default` | Rejected when detectable; otherwise unsupported. Existing tools are never shadowed. (section 8.3) | Proposed in this document, following decision 06 |
| Adding an image to the verified list | Full verification set (section 7.5) | Proposed in this document |
| Managed environment states | S0 to S4 (section 9.3) | Proposed in this document |
| Baseline placement and CI reference | Sections 5.2 and 5.3 | Proposed in this document |
| Comparison for releases after 1.1.0 | Previous published release as the baseline, with expected differences adopted by the human (section 5.6) | Proposed in this document |
| Name and place of this document | `docs/python-install-contract.md` | Proposed in this document |
| Release type of a verified-image addition | minor (section 14.1) | Proposed in this document |

## 19. Responsibilities of later tickets

### 19.1 Ticket split

| Ticket | Phase | Responsibility | Main sections | Hands over |
| --- | --- | --- | --- | --- |
| #5536 | 2 | `python` executor. Select and record the `cimg/python` digest. Measure the preconditions and the interpreter. Minimal CI that pulls and starts the default configuration, kept on `main` and required by production publish. | 6.1, 7.1, 7.2, 8.1, 19.3 | Image identity, interpreter record, minimal CI job and its success conditions, to #5537 and #5539 |
| #5537 | 3 | `install`: fixed set, managed environment, exposure, pip isolation, and failure handling. Minimal CI from `install` to the real `execute`, kept on `main` and required by production publish. Structural checks of failure handling. | 6.2, 8 to 13 | Fixed information, command list, required CLIs, structural trace, and the list of measurements still required, to #5539 |
| #5538 | 4 (existing API comparison) | Baseline hash check and comparison for both actual packs, with self-tests. Keep the exit-code check. Required by continue and by production publish. | 5 | Baseline hash, commit, packs, and results, to #5539 and #5541 |
| #5539 | 4 (old and new verification) | Expand the minimal CI into required checks while keeping their success conditions. New-path checks, failure measurements (section 13), executor settings, direct Docker job, and publication gates. Minimal fixes of contract mismatches found by measurement. | 7 to 14, 19.2 | Verified configurations, results, and result differences, to #5540 and #5541 |
| #5540 | 5 | README, CHANGELOG, and examples aligned with this contract and the results. Entry point of the update procedure. | 6.3, 10, 11, 12, 14 | Documentation, to #5541 |
| #5541 | 6 | Final candidate checks, publication, and registry read-back | 5.4, 14, 19 | Release record |

### 19.2 Minimal CI and its expansion

- #5536 and #5537 each leave a minimal CI job on `main`. It uses inline
  injection of the candidate Orb.
- Each ticket connects its job to production publish as a success
  prerequisite and keeps the existing tag and branch conditions.
- Neither adds a dev publish, and tests need no publishing context or token.
- Minimal CI of #5536: the default configuration of `python` pulls and starts,
  and the preconditions are confirmed.
- Minimal CI of #5537: in a clean job, `install` runs. Separate run steps
  show that the four direct commands and the real `execute` use the managed
  environment. The input is a repository fixture with a real Ansible file, and
  lint finds no violation.
- #5539 expands and merges these jobs into required checks. It keeps a table
  that maps the conditions of #5536 C4 and #5537 C7 to the expanded jobs,
  inputs, and expected results. It does not weaken them or drop publication
  prerequisites.
- Minimal checks alone never make a candidate publishable.
- #5538 connects its comparison of the injection pack to continue and its
  comparison of the publication pack to production publish.

### 19.3 Values filled by measurement

| Value | Filled by | Recorded in | First candidate |
| --- | --- | --- | --- |
| `cimg/python` digest, tag at selection, platform, index and manifest mapping, resolution time | #5536 | Verified image record; section 6.1 of this document | The image for Python 3.14.10 |
| Interpreter path and version, pip version, virtual environment check, Bash, Git | #5536 | Verified image record | Python 3.14.10 |
| Default value of `python.image` | #5536 | `src/executors/python.yml`; section 6.1 | The digest above |
| Fixed set, including all transitive dependencies | #5537 | Fixed information in the Orb; its record | ansible-lint 26.10.1, Ansible package 14.5.0, ansible-core 2.21.5 |
| Bootstrap distributions of the verified interpreter | #5537 | Fixed information | None |
| Required run-time CLIs of the adopted ansible-lint | #5537 | Its record; README | None |
| Exposed command list | #5537 | Fixed information; README | None |
| Managed environment location and state record format | #5537 | Implementation; README states the location | None |
| How failure cases are reproduced | #5539 | `tests/README.md` and evidence | None |

If a value cannot meet this contract, stop. Show the human the difference, the
reason, and the options. After adoption, update this document and record the
new contract commit (section 20).

## 20. Adoption and change control

### 20.1 Adoption

1. The human reviews this document and the baseline files.
2. The human commits them, or approves a commit.
3. Adoption is recorded in #5535 with the commit SHA (the contract commit) and
   the date. That Redmine record is a separate write and needs explicit
   approval.
4. Later tickets reference the contract commit, not whatever `main` is at the
   time.

This document does not contain its own commit SHA. It also does not state
whether it is adopted, so adoption needs no further edit of this file.

### 20.2 Filling measured values

- #5536 and #5537 replace the TBD values with measured values in a contract
  update commit, with evidence.
- Every update of this document needs human adoption, recorded in Redmine
  with the new contract commit.
- Later tickets then switch to the new contract commit.

### 20.3 Changes

A change is needed when, for example:

- a first candidate is unavailable or does not work;
- a precondition fails on the selected image;
- a required CLI falls outside the exposure scope;
- the pip isolation mechanism does not cover a category;
- a measured failure behaves differently from section 13;
- the 1.1.0 comparison of section 5.4 would need a difference;
- the rules of section 5.6 would need to change;
- a guarantee, the existing API, a prerequisite, or a required condition
  would change.

Procedure:

1. Stop the affected work.
2. Show the human the difference, the reason, the options, and the impact.
3. After the human adopts a change, update this document.
4. Record the new contract commit in Redmine.
5. Later tickets switch to it and re-run the affected checks.

Evidence for an older contract is not evidence for a newer one.
Implementation, tests, and README must not drift from this document.

### 20.4 What adoption does not approve

Adopting this contract does not approve Redmine updates, roadmap edits, CI
runs, tags, or publication. Each needs its own approval.

## 21. Traceability

### 21.1 Phase 1 deliverables of `110_ロードマップ` version 1

| No. | Deliverable | Section |
| --- | --- | --- |
| 1 | 決定01 to 決定08 and 方針01; names, types, default policy, and descriptions of the new executor, command, and parameters | 6, 18.1 |
| 2 | Identity of the published 1.0.0 source, the stored copy, its location, the CI reference, the SHA-256 check before each comparison, and the comparison scope and equality rule | 5 |
| 3 | OS, architecture, shell, and Python conditions; how verified images are identified; the direct Docker job; responsibility for image overrides | 7.1 to 7.4 |
| 4 | Handling of `install` on unverified images and on the existing `default` | 8.3 |
| 5 | Conditions to add an image to the verified list; setting reflection versus full verification | 7.5 |
| 6 | Explicit Python selection and failure (決定06); whether `install` before checkout is supported | 8.1, 8.2 |
| 7 | What `install` installs; ownership, lifetime, re-invocation, and inconsistency of the managed environment; no unconditional overwrite or deletion | 9, 12 |
| 8 | Exposure scope, effects on `python` and `pip`, user changes to the managed environment, verification of required Ansible CLIs | 10, 9.3 |
| 9 | Consumer pip settings and environment variables; source, network, constraints, and destination against the exact-version policy | 11 |
| 10 | Failure conditions; measured and structural verification; no test-only public parameter | 13 |
| 11 | Update units and release types (決定07); sections of the existing roadmap and reasons; minimal checks of Phases 2 and 3 against the publication conditions of Phase 4 | 14.1, 17, 19.2 |
| 12 | Version alignment of both paths after release (human decision), failure of one path, result differences, README and CHANGELOG duties | 5.6, 14.2, 14.3 |

### 21.2 Tasks and completion conditions of #5535

| #5535 task | Section |
| --- | --- |
| 1. Document placement and roles; README reference; 方針01 and 決定01 to 決定08; difference from 1.0.0; boundaries against `100_ロードマップ` | 2, 15, 17, 18.1, README "Public API" |
| 2. Published 1.0.0 comparison source | 5 |
| 3. Types, defaults, and descriptions; environment preconditions; direct Docker job; image overrides | 6, 7 |
| 4. Python selection, step order, unverified images, and the verified list | 7.5, 8 |
| 5. Managed environment and PATH | 9, 10 |
| 6. pip settings, failure conditions, and verification split | 11, 13 |
| 7. Release types and alignment after release | 5.6, 14 |
| 8. Adoption, contract commit, measured values, and the ticket split | 19, 20 |

| Condition | Where to check |
| --- | --- |
| C1 | Sections 4, 6, 15, 17, 18, and 21.1; the README reference |
| C2 | Section 5 and `tests/baseline/` |
| C3 | Sections 7 and 8.3 (E1 to E11) |
| C4 | Sections 9.3 (S0 to S4) and 10 |
| C5 | Sections 11, 13, and 19 |
| C6 | Sections 5.6 and 14 |
| C7 | Sections 19.3 and 20. The adoption record and the commit are added in Redmine after the human adopts this document. |

## 22. References

Redmine, project 319:

- #5503 journal 11186: publication record of v1.0.0
- #5535 to #5541: tickets of 1.1.0
- Wiki `110_ロードマップ` version 1
- Wiki `100_ロードマップ` versions 4 and 5

Repository at `11e4054185ab52907cdb855d37d05694f8ba1318`:

- [README.md](../README.md)
- [src/executors/default.yml](../src/executors/default.yml)
- [src/commands/execute.yml](../src/commands/execute.yml)
- [src/scripts/install-molecule-test-roles.sh](../src/scripts/install-molecule-test-roles.sh)
- [.circleci/config.yml](../.circleci/config.yml)
- [.circleci/test-deploy.yml](../.circleci/test-deploy.yml)
- [.circleci/verify-packed-orb.sh](../.circleci/verify-packed-orb.sh)
- [tests/README.md](../tests/README.md)
- [image-lock.json](../image-lock.json)

Other sources:

- `circleci/orb-tools@12.5.0` source, read from the registry on 2026-11-15.
  Its `lint` job lints `src` by default, and its default executor uses the
  CLI image tag `latest`.
- The external technical sources listed in `110_ロードマップ` version 1:
  [cimg-python at commit c208a670dca565ed60f73c276136680fe3ec8b00](https://github.com/CircleCI-Public/cimg-python/tree/c208a670dca565ed60f73c276136680fe3ec8b00),
  [Ansible Lint: Installing](https://docs.ansible.com/projects/lint/installing/),
  [Installing Ansible](https://docs.ansible.com/projects/ansible/latest/installation_guide/intro_installation.html),
  and [CircleCI: Set an environment variable](https://circleci.com/docs/guides/security/set-environment-variable/).
  This document relies on the roadmap's summary of them and does not
  re-verify their content.
