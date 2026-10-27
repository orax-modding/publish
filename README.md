# publish

Reusable GitHub workflows and [`publish-hexium.py`](publish-hexium.py) to publish releases to
**Hexium.gg** and **Nexus Mods** from any repository of the `orax-modding` organization.

This repo is the **single source of truth** for two publishing pipelines:

| file (here)                                       | role                                                                   |
| ------------------------------------------------- | ---------------------------------------------------------------------- |
| `.github/workflows/reusable-hexium-upload.yml`    | **reusable** workflow: the whole Hexium pipeline + `publish-hexium.py` |
| `.github/workflows/reusable-nexusmods-upload.yml` | **reusable** workflow: the whole Nexus Mods pipeline                   |
| `publish-hexium.py`                               | the script (always executed from _this_ repo, never copied)            |
| `.github/workflows/upload-hexium.yml`             | local caller (this repo)                                               |
| `.github/workflows/upload-nexusmods.yml`          | local caller (this repo)                                               |

In another project you copy **only the small caller file** (~10 lines): the logic, the script and
its fixes are fetched from here at the version you pin. The templates are in
[§1](#1-publishing-to-hexium-from-another-repo) (Hexium) and
[§2](#2-publishing-to-nexus-mods-from-another-repo) (Nexus Mods).

> `orax-modding/publish` is public: any of your repos (public or private) can call it with no extra
> setup.

---

## Publishing to Hexium from another repo

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
repository = "https://hexium.gg"  # read by publish-hexium.py (and by tcli)
communities = ["valheim"]

[publish.categories]
# https://valheim.hexium.gg/api/experimental/community/valheim/category/
valheim = ["Open Source", "Valheim 1.0"]
```

That's it: the release zip must be named `<repo-name>.zip`, otherwise set the `asset:` input shown
above.

---

## Publishing to Nexus Mods from another repo

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

## Secrets and variables: organization over repository

`orax-modding` is an **organization**, so create them once under \*Settings → Secrets and variables
→ Actions → **Organization\***:

| type     | key                 | scope                        |
| -------- | ------------------- | ---------------------------- |
| secret   | `HEXIUM_API_TOKEN`  | all repos (Hexium API token) |
| secret   | `NEXUSMODS_API_KEY` | all repos                    |
| variable | `HEXIUM_TEAM`       | all repos (same Hexium team) |

From the CLI: `gh secret set HEXIUM_API_TOKEN --org orax-modding` (needs the `admin:org` scope:
`gh auth refresh -s admin:org`).

Precedence: **repository variable > organization variable**, so keep `NEXUSMODS_MOD_ID` /
`NEXUSMODS_FILE_ID` at the repository level (every mod has its own) and the tokens at the
organization level.

Callers must forward the secret **by name** (the `secrets:` block in both examples above).
`secrets: inherit` only propagates secrets between workflows of the **same organization**, while
each consumer lives in its own organization: GitHub would then silently deliver an empty secret and
the upload fails with "no API token found".

---

## Checklist for each new project

1. **Zip name**: `<repo-name>.zip` is expected by default → otherwise pass the `asset:` input.
2. **Hexium**: `hexium.toml` (namespace, communities, categories) + the `HEXIUM_API_TOKEN` secret
   available (organization).
3. **Nexus**: `NEXUSMODS_MOD_ID` + `NEXUSMODS_FILE_ID` repository variables.
4. **Default branch**: the caller file must live on it (otherwise `release` triggers never fire).
5. **Permissions**: keep `permissions: contents: read` in the caller (the ceiling passed down to the
   master workflow, required by `gh release download`).
6. **Manual run / dry run**: _Actions → Upload to Hexium.gg_ or _Upload to Nexus Mods_ → _Run
   workflow_ with an existing tag (both callers expose that button). This is also the way to retry a
   failed upload after fixing the configuration — no release to re-publish. The tag must point at a
   published release carrying the asset.

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
