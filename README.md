# publish

Reusable GitHub workflows and [`publish-hexium-thunderstore.py`](publish-hexium-thunderstore.py) to publish releases to
**Hexium.gg**, **Thunderstore.io** and **Nexus Mods** from any repository of the `orax-modding`
organization.

This repo is the **single source of truth** for three publishing pipelines:

| file (here)                                          | role                                                                              |
| ---------------------------------------------------- | --------------------------------------------------------------------------------- |
| `.github/workflows/reusable-hexium-upload.yml`       | **reusable** workflow: the whole Hexium pipeline + `publish-hexium-thunderstore.py` |
| `.github/workflows/reusable-thunderstore-upload.yml` | **reusable** workflow: the Thunderstore pipeline (same script)                    |
| `.github/workflows/reusable-nexusmods-upload.yml`    | **reusable** workflow: the whole Nexus Mods pipeline                              |
| `publish-hexium-thunderstore.py`                     | the script (always executed from _this_ repo, never copied)                       |
| `.github/workflows/upload-hexium.yml`                | local caller (this repo)                                                 |
| `.github/workflows/upload-thunderstore.yml`          | local caller (this repo)                                                 |
| `.github/workflows/upload-nexusmods.yml`             | local caller (this repo)                                                 |

In another project you copy **only the small caller file** (~10 lines): the logic, the script and
its fixes are fetched from here at the version you pin. The templates are in
[§1](#1-publishing-to-hexium-from-another-repo) (Hexium),
[§2](#2-publishing-to-nexus-mods-from-another-repo) (Nexus Mods) and
[§3](#3-publishing-to-thunderstore-from-another-repo) (Thunderstore).

> `orax-modding/publish` is public: any of your repos (public or private) can call it with no extra
> setup.

---

## 1. Publishing to Hexium from another repo

### The file to create — `.github/workflows/upload-hexium.yml`

```yaml
name: Upload to Hexium.gg

on:
    release:
        types: [published]
    workflow_dispatch:
        inputs:
            tag:
                description: 'Release tag to publish (e.g. v1.2.3)'
                required: true
                default: 'v1.2.3'

permissions:
    contents: read

jobs:
    upload:
        uses: orax-modding/publish/.github/workflows/reusable-hexium-upload.yml@v0.1
        with:
            tag:
                ${{ github.event_name == 'workflow_dispatch' && inputs.tag ||
                github.event.release.tag_name }}
            # team: my-namespace       # optional; falls back to [package] namespace in hexium.toml
            # asset: my-mod.zip        # optional; defaults to <repo-name>.zip
            # config: hexium.toml      # optional; defaults to hexium.toml when present
        secrets:
            HEXIUM_API_TOKEN: ${{ secrets.HEXIUM_API_TOKEN }}
```

### The `hexium.toml` file to create at the repo root

The script reads it **from the calling repo** (namespace, communities, categories):

```toml
[package]
namespace = "my-namespace"        # Hexium author/team (author_name)

[publish]
repository = "https://hexium.gg"  # read by publish-hexium-thunderstore.py (and by tcli)
communities = ["valheim"]

[publish.categories]
# https://valheim.hexium.gg/api/experimental/community/valheim/category/
valheim = ["Open Source", "Valheim 1.0"]
```

That's it: the release zip must be named `<repo-name>.zip`, otherwise set the `asset:` input shown
above.

---

## 2. Publishing to Nexus Mods from another repo

### The file to create — `.github/workflows/upload-nexusmods.yml`

```yaml
name: Upload to Nexus Mods

on:
    release:
        types: [published]
    workflow_dispatch:
        inputs:
            tag:
                description: 'Release tag to publish (e.g. v1.2.3)'
                required: true
                default: 'v1.2.3'

permissions:
    contents: read

jobs:
    upload:
        uses: orax-modding/publish/.github/workflows/reusable-nexusmods-upload.yml@v0.1
        with:
            # workflow_dispatch input when run manually, release tag otherwise.
            tag:
                ${{ github.event_name == 'workflow_dispatch' && inputs.tag ||
                github.event.release.tag_name }}
            mod_id: ${{ vars.NEXUSMODS_MOD_ID }}
            file_id: ${{ vars.NEXUSMODS_FILE_ID }}
            # display_name: my-mod.zip # optional; defaults to <repo-name>.zip
        secrets:
            NEXUSMODS_API_KEY: ${{ secrets.NEXUSMODS_API_KEY }}
```

### The variables to create in that repo

_Settings → Secrets and variables → Actions → Repository_:

| type     | key                 | value                                            |
| -------- | ------------------- | ------------------------------------------------ |
| variable | `NEXUSMODS_MOD_ID`  | mod ID on Nexus (**unique per project**)         |
| variable | `NEXUSMODS_FILE_ID` | master file ID on Nexus (**unique per project**) |

No script and no `hexium.toml` to copy for Nexus-only projects. The changelog sent to Nexus is the
**body of the release** being published.

---

## 3. Publishing to Thunderstore from another repo

Thunderstore implements the same experimental submission API as Hexium, so this pipeline runs the
**very same `publish-hexium-thunderstore.py`**: only the URL, the config file and the token secret differ.

### The file to create — `.github/workflows/upload-thunderstore.yml`

```yaml
name: Upload to Thunderstore.io

on:
    release:
        types: [published]
    workflow_dispatch:
        inputs:
            tag:
                description: 'Release tag to publish (e.g. v1.2.3)'
                required: true
                default: 'v1.2.3'

permissions:
    contents: read

jobs:
    upload:
        uses: orax-modding/publish/.github/workflows/reusable-thunderstore-upload.yml@v0.1
        with:
            # workflow_dispatch input when run manually, release tag otherwise.
            tag:
                ${{ github.event_name == 'workflow_dispatch' && inputs.tag ||
                github.event.release.tag_name }}
            # team: my-namespace     # optional; falls back to [package] namespace
            # asset: my-mod.zip      # optional; defaults to <repo-name>.zip
            # communities: valheim   # optional; falls back to [publish] communities
            # config: thunderstore.toml  # optional; that is the default
        secrets:
            THUNDERSTORE_API_TOKEN: ${{ secrets.THUNDERSTORE_API_TOKEN }}
```

### The `thunderstore.toml` file to create at the repo root

The script reads it **from the calling repo** (namespace, communities, categories). A project that
publishes to both stores simply keeps `hexium.toml` **and** `thunderstore.toml` side by side — each
workflow picks its own file, so the categories of one store are never sent to the other:

```toml
[package]
namespace = "my-namespace"          # Thunderstore author (author_name)

[publish]
repository = "https://thunderstore.io"
communities = ["valheim"]

[publish.categories]
# https://thunderstore.io/api/experimental/community/valheim/category/
valheim = ["Mods"]
```

Categories are checked online before every upload, so a name that does not exist on Thunderstore
stops the run with the list of the valid ones.

Two inputs help on a first run: `dry_run: true` uploads the zip and then aborts instead of
submitting — the token and the whole upload path are exercised, nothing is published — and `asset:`
names a release asset other than `<repo-name>.zip`.

The token is created on Thunderstore under _account settings → API tokens_. The `config:` input
defaults to `thunderstore.toml`, so the file must exist on every project keeping that default; pass
`config: ''` together with `communities:` for a project that keeps no config file at all.

---

## Secrets and variables: organization over repository

`orax-modding` is an **organization**, so create them once under \*Settings → Secrets and variables
→ Actions → **Organization\***:

| type     | key                    | scope                              |
| -------- | ---------------------- | ---------------------------------- |
| secret   | `HEXIUM_API_TOKEN`     | all repos (Hexium API token)       |
| secret   | `THUNDERSTORE_API_TOKEN` | all repos (Thunderstore API token) |
| secret   | `NEXUSMODS_API_KEY`    | all repos                          |
| variable | `HEXIUM_TEAM`          | all repos (same Hexium team)       |
| variable | `THUNDERSTORE_TEAM`    | all repos (same Thunderstore team) |

From the CLI: `gh secret set <SECRET_NAME> --org orax-modding` (needs the `admin:org` scope:
`gh auth refresh -s admin:org`).

Precedence: **repository variable > organization variable**, so keep `NEXUSMODS_MOD_ID` /
`NEXUSMODS_FILE_ID` at the repository level (every mod has its own) and the tokens at the
organization level.

Callers must forward the secret **by name** (the `secrets:` block in every example above).
`secrets: inherit` only propagates secrets between workflows of the **same organization**, while
each consumer lives in its own organization: GitHub would then silently deliver an empty secret and
the upload fails with "no API token found".

---

## Checklist for each new project

1. **Zip name**: `<repo-name>.zip` is expected by default → otherwise pass the `asset:` input.
2. **Hexium**: `hexium.toml` (namespace, communities, categories) + the `HEXIUM_API_TOKEN` secret
   available (organization).
3. **Thunderstore**: `thunderstore.toml` (namespace, communities, categories) + the
   `THUNDERSTORE_API_TOKEN` secret available (organization).
4. **Nexus**: `NEXUSMODS_MOD_ID` + `NEXUSMODS_FILE_ID` repository variables.
5. **Default branch**: the caller file must live on it (otherwise `release` triggers never fire).
6. **Permissions**: keep `permissions: contents: read` in the caller (the ceiling passed down to the
   master workflow, required by `gh release download`).
7. **Manual run / dry run**: _Actions → Upload to Hexium.gg_, _Upload to Thunderstore.io_ or _Upload
   to Nexus Mods_ → _Run workflow_ with an existing tag (every caller exposes that button). This is
   also the way to retry a failed upload after fixing the configuration — no release to re-publish.
   The tag must point at a published release carrying the asset.

---

## Limits to know

- A job that calls a reusable workflow (`uses:`) **cannot** have its own `steps`/`runs-on`: if you
  need to chain other steps (changelog, release notes…), keep those steps in the calling repo and
  share only steps — that is the **composite action** case (coming if needed).
- The `github` context inside the master workflow is the **calling repo**'s:
  `github.event.repository.name`, `github.event.release.tag_name`, etc. stay those of the project
  that triggered it.
- `workflow_call` never triggers anything by itself: the caller carries the events (`release`,
  `workflow_dispatch`).
- The script is fetched with `actions/checkout` from `orax-modding/publish` with
  `ref: ${{ inputs.tools_ref }}` (default `v0.1`): each caller can pin a different version during a
  gradual migration.
