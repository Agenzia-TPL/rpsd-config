# SKILL: open-source-it-pa — Publish repository as open source (Italian PA guidelines)

**Purpose:** Bring a repository into compliance with the Italian Public
Administration open-source publication requirements defined in CAD Art. 69 and
the Developers Italia guidelines. The skill is self-contained and can be
dropped into any repository.

---

## Modes

This skill supports two invocation modes:

### Implement mode (default)

Run all phases in order, ask the user the mandatory questions, then write and
fix all files to reach compliance.

Invoke by telling the assistant:
> *"Use this skill."* or *"Use this skill in implement mode."*

### Assess mode

Run **Phase 0 and Phase 1 only**. Make **no changes** to any file. Produce a
structured compliance report (see Phase 1a below). Do not ask questions.

Invoke by telling the assistant:
> *"Use this skill in assessment mode."*

The report must contain:

1. **Traffic-light summary** for each requirement category:

   | Category | Status | Notes |
   |---|---|---|
   | Licence file | ✅ / ⚠️ / ❌ | LICENSE present and correct SPDX text? |
   | SPDX headers | ✅ / ⚠️ / ❌ | N of M source files covered |
   | README completeness | ✅ / ⚠️ / ❌ | Which required sections are missing |
   | CONTRIBUTING.md | ✅ / ⚠️ / ❌ | Present? Covers required topics? |
   | publiccode.yml | ✅ / ⚠️ / ❌ | Present? |
   | security.txt | ✅ / ⚠️ / ❌ | Present at `.well-known/security.txt`? |
   | CI gate (SPDX) | ✅ / ⚠️ / ❌ | Header check in CI pipeline? |

2. **Gap details** — for each ⚠️ or ❌, one line describing what is missing
   or incomplete.

3. **Prioritised action list** — what to address first to reach minimum
   compliance for publication, ordered by importance.

---

## Instructions for the AI assistant

Follow every phase below in order. Do not skip phases. Read-only actions
(fetching guidelines, reading existing files) may be parallelised. File writes
must happen after all questions have been answered.

---

### Phase 0 — Read the Italian PA guidelines

Fetch both documents and extract the requirements before doing anything else:

- **Licences:**
  https://docs.italia.it/italia/developers-italia/gl-acquisition-and-reuse-software-for-pa-docs/en/stabile/software-reuse/open-licences-and-selecting-a-licence.html

- **Publishing guide (Annex A):**
  https://docs.italia.it/italia/developers-italia/gl-acquisition-and-reuse-software-for-pa-docs/en/stabile/attachments/annex-A-Guide-to-publishing-software-as-open-source.html

Key rules to extract and apply:
- Which licence is recommended for the software type (application, library,
  SaaS, documentation).
- Mandatory files: `LICENSE`, SPDX headers in every source file, `README.md`
  required sections, `publiccode.yml`.
- Optional files triggered by user choice: `security.txt`, Developers Italia
  registration.

---

### Phase 1 — Explore the repository

Collect the following facts (read-only, run in parallel):

1. **Existing root files:** `LICENSE`, `README.md`, `CONTRIBUTING.md`,
   `publiccode.yml`, `CHANGELOG`, `.well-known/security.txt`.
2. **Project metadata:** language(s), framework, `pyproject.toml` /
   `package.json` / `pom.xml` / etc. — name, version, description, current
   licence field.
3. **Source file inventory:** list every source file that needs an SPDX header
   (`.py`, `.js`, `.ts`, `.java`, `.go`, `.rs`, `.c`, `.cpp`, `.h`, etc.).
   Check a sample to see whether headers already exist.
4. **Existing SPDX headers:** check whether files already carry
   `SPDX-FileCopyrightText` and `SPDX-License-Identifier` lines.
5. **Git remote URL:** used in `publiccode.yml` and `README.md`.
6. **Contributors:** `git log --format="%an <%ae>" | sort -u` — used in
   `AUTHORS` / `publiccode.yml`.

---

### Phase 2 — Ask the user (mandatory questions)

Ask ALL of the following questions before writing any file. Group them in a
single interaction where possible.

#### Q1 — Legal name of the copyright holder (REQUIRED)

Ask: *"What is the full legal name of the copyright holder (the organisation
that owns the intellectual property)? This will appear in the LICENSE file,
SPDX headers, and README."*

Do not accept a short name or abbreviation; the Italian PA guidelines require
the full institutional name (e.g. "AGENZIA TPL BACINO CITTA' METROPOLITANA
MILANO, MONZA E BRIANZA, LODI, PAVIA"). If the user provides a short form, ask
for confirmation that it is the legally complete name.

#### Q2 — Developers Italia registration

Ask: *"Should I prepare the `publiccode.yml` file required for registration on
Developers Italia, or do you want to defer that to a later phase?"*

Options:
- **Yes, create publiccode.yml now** — generate the file with all mandatory
  fields filled from the repository metadata and the user's answers.
- **Defer to later** — skip `publiccode.yml`; note the omission in the output
  summary.

#### Q3 — Security contact (security.txt)

Ask: *"The Italian PA guidelines recommend a `security.txt` file at
`/.well-known/security.txt` for web applications. Should I create it, or
skip it for now?"*

Options:
- **Create security.txt** — ask for the security contact e-mail address, then
  create the file.
- **Skip for now** — omit the file; note the omission in the output summary.

#### Q4 — Licence confirmation

Based on the repository type detected in Phase 1, propose the correct licence
following the guidelines:

| Repository type | Recommended licence |
|---|---|
| General application / service | EUPL-1.2 |
| SaaS / software accessed over a network | AGPL-3.0-or-later |
| Library or SDK | EUPL-1.2 or BSD-3-Clause |
| Documentation only | CC-BY-4.0 |

If the project metadata already specifies a licence, confirm it matches the
recommendation. If it does not, propose the correct one and ask for
confirmation before proceeding.

---

### Phase 3 — Determine the copyright year

Use the earliest commit year from `git log --reverse --format="%ad"
--date=format:"%Y" | head -1` as the start year. If the start year differs
from the current year, format as `YYYY–YYYY` (e.g. `2024–2026`). If they are
the same, use `YYYY`.

---

### Phase 4 — Write or update files

Execute the following steps in order. For each file:
- If the file does not exist, **create** it.
- If the file exists, **update** only the parts that need updating; preserve
  existing content that is already correct.

#### 4a. `LICENSE`

Create or replace with the full, unmodified licence text fetched from
`https://spdx.org/licenses/{SPDX-ID}.html` (e.g. `EUPL-1.2`). Place it in
the repository root.

#### 4b. SPDX headers in source files

Use the `check_headers.sh` script bundled in this skill to add headers in one
step:

```bash
bash ai-skills/open-source-it-pa/scripts/check_headers.sh \
  --fix \
  --copyright "{year} {LEGAL NAME OF COPYRIGHT HOLDER}" \
  --license {SPDX-ID} \
  --ext py,sh,js,ts,go \   # adjust to the repo's languages
  src/
```

The script:
- Uses the correct comment character per file extension (see its lookup table).
- Inserts headers after the shebang line (`#!`) for shell scripts.
- Skips auto-generated paths (`.git/`, `.venv/`, `dist/`, `build/`, etc.).
- Is a no-op on files that already have both SPDX tags.

Do not add headers to:
- Auto-generated files (e.g. `migrations/`, `dist/`, `build/`, `*.pb.go`,
  `*.generated.*`)
- Third-party files bundled in the repository
- Binary files

#### 4c. `README.md`

Create or expand to include **all** of the following sections required by the
Italian PA guidelines. Preserve and integrate any useful existing content.

Required sections (in this order, adapt headings as needed):

1. **Title** — repository name and a one-sentence descriptive subtitle.
2. **Description** — non-technical explanation of what the software does,
   its context, and its intended users. This section must be intelligible to
   a non-technical reader.
3. **Screenshots** — include if the software has a UI; otherwise omit.
4. **Repository structure** — annotated directory tree showing main
   components.
5. **Prerequisites** — all runtime and build-time dependencies with version
   constraints.
6. **Installation** — step-by-step instructions for development, Docker, and
   production deployment.
7. **Configuration** — table of all environment variables or configuration
   parameters.
8. **Project status** — one of: `alpha`, `beta`, `stable`. Include known
   limitations or issues.
9. **Copyright** — full legal name of the copyright holder (from Q1).
10. **Licence** — name and SPDX identifier, with a link to the `LICENSE` file.
11. **Maintainer** — organisation name and how to reach them (GitHub Issues
    link is acceptable).

#### 4d. `CONTRIBUTING.md`

Create or update with:
- How to report bugs (issue tracker link).
- How to submit changes (fork → branch → PR workflow).
- Coding standards (style, linting, type hints, line length).
- How to run tests.
- Statement that contributions are accepted under the same licence.
- Requirement to add SPDX headers to any new source file.

#### 4e. `publiccode.yml` *(only if the user chose "Yes" in Q2)*

Create the file in the repository root following the
[publiccode.yml standard](https://github.com/publiccodeyml/publiccode.yml).
Populate at minimum:

```yaml
publiccodeYmlVersion: "0.4"
name: {project name}
url: {git remote URL}
releaseDate: {today's date, YYYY-MM-DD}
softwareVersion: {version from project metadata}
developmentStatus: {development | beta | stable}
softwareType: standalone/backend   # adjust as appropriate
platforms:
  - web                            # adjust as appropriate
categories:
  - {most relevant category}       # see publiccode.yml category list
description:
  it:
    shortDescription: {≤150 chars, Italian}
    longDescription: {≥500 chars, Italian}
  en:
    shortDescription: {≤150 chars, English}
    longDescription: {≥500 chars, English}
legal:
  license: {SPDX-ID}
  repoOwner: {LEGAL NAME OF COPYRIGHT HOLDER}
  mainCopyrightOwner: {LEGAL NAME OF COPYRIGHT HOLDER}
maintenance:
  type: internal
  contacts:
    - name: {maintainer name or organisation}
```

Ask the user for any fields that cannot be determined from the repository
(e.g. Italian description, category).

#### 4f. `.well-known/security.txt` *(only if the user chose "Create" in Q3)*

Create the file following the [RFC 9116](https://www.rfc-editor.org/rfc/rfc9116)
format:

```
Contact: mailto:{security email}
Expires: {one year from today, RFC 3339 format}
Preferred-Languages: it, en
```

For FastAPI / web-framework projects, also mount the `.well-known/` directory
as a static files route so the file is served at the correct URL.

---

### Phase 5 — Verify

After all writes are complete, verify:

1. `LICENSE` exists in the repository root and contains the correct licence
   text.
2. Run the check script to confirm all source files are covered:
   ```bash
   bash ai-skills/open-source-it-pa/scripts/check_headers.sh --check --ext py,sh src/
   ```
   Must exit 0.
3. `README.md` contains all required sections listed in step 4c.
4. `CONTRIBUTING.md` exists.
5. If `publiccode.yml` was created, validate it is valid YAML and contains at
   minimum the fields listed in step 4e.
6. Run the project's linter (e.g. `uv run ruff check`) to confirm no syntax
   errors were introduced by the header additions.
7. Run the project's test suite (e.g. `uv run pytest`) to confirm no
   regressions.

---

### Phase 6 — Output summary

Print a concise summary listing:
- Files created.
- Files modified.
- Items deferred (Developers Italia registration, security.txt, or anything
  else the user chose to skip).
- Any manual actions the user must take before the repository can be
  considered fully compliant (e.g. completing the Developers Italia
  onboarding, setting up a security alias, etc.).

---

## Notes for portability

- This skill directory (`open-source-it-pa/`) is self-contained. Copy the
  entire directory to any repository's `ai-skills/` folder.
- Scripts live in `scripts/` inside this directory. Run them from the repo
  root using a relative path:
  ```bash
  bash ai-skills/open-source-it-pa/scripts/check_headers.sh --check src/
  ```
- To use it with GitHub Copilot or another assistant, paste the content of
  this file into the assistant's context or reference it explicitly.
- The skill does **not** commit changes. Stage and commit the resulting files
  following the repository's own git policy.
