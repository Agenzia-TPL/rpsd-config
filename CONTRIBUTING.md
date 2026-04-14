# Contributing to rpsd-config

Thank you for your interest in contributing to `rpsd-config`. This document
describes how to report bugs, submit changes, run the test suite, and follow
the coding standards used in this project.

## Reporting Bugs

Please open an issue on the
[GitHub issue tracker](https://github.com/Agenzia-TPL/rpsd-config/issues).

Include in your report:
- A clear description of the problem and the expected behaviour.
- Steps to reproduce the issue.
- The version of `rpsd-config` you are using (`git rev-parse HEAD` or the
  release tag).
- Relevant log output or error messages.

For security vulnerabilities, **do not** open a public issue. Contact the
maintainers directly via the GitHub issue tracker with the "security" label,
or reach out through the contact information in the repository.

## Submitting Changes

1. **Fork** the repository on GitHub and create a new branch from `main`:

   ```bash
   git checkout -b feature/my-change
   ```

2. Make your changes. Keep each commit focused on a single concern.

3. Ensure your changes pass all checks (see Running Tests and Linting below).

4. Push your branch and open a **Pull Request** against `main`. Describe what
   the PR changes and why.

5. A maintainer will review your PR. Please be responsive to review feedback.

## Coding Standards

- **Language:** Python ≥ 3.13. All code, comments, docstrings, and log
  messages must be written in English.
- **Formatter / linter:** [Ruff](https://docs.astral.sh/ruff/), configured in
  `pyproject.toml`. Line length is 88 characters.
- **Import style:** isort-compatible (enforced by Ruff rule `I`).
- **Naming:** follow PEP 8 and the Ruff `N` rule set.
- **Type annotations:** use them for all new public functions and methods.
- **Django conventions:** follow Django project structure conventions. Admin
  proxy apps are separated from the core domain app (`exchange_agreement`).

Run the linter before committing:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

## Running Tests

Install dev dependencies and run the full test suite:

```bash
uv sync
uv run pytest
```

Run only fast (non-integration) tests:

```bash
uv run pytest -m "not integration"
```

Run tests in parallel:

```bash
uv run pytest -n auto
```

The test suite requires a running PostGIS database. When using the devcontainer
or `docker compose up`, the database is started automatically.

## SPDX Headers

Every new source file you add must include SPDX copyright and licence headers
as the first lines of the file:

```python
# SPDX-FileCopyrightText: <year> AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
```

Use the bundled script to check or fix headers in bulk:

```bash
# Check
bash ai-skills/open-source-it-pa/scripts/check_headers.sh --check --ext py src/

# Fix (add missing headers)
bash ai-skills/open-source-it-pa/scripts/check_headers.sh \
  --fix \
  --copyright "<year> AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA" \
  --license EUPL-1.2 \
  --ext py \
  src/
```

The CI pipeline enforces this check on every push.

## Contributor License Agreement (CLA)

By opening a pull request you certify the following — no separate signature
is required; submitting the PR constitutes acceptance:

1. **Right to submit** — You have the right to submit the contribution under
   the project licence (EUPL-1.2). If you are contributing on behalf of an
   employer or under a work-for-hire agreement, you confirm that your employer
   or the relevant rights holder has authorised you to do so.

2. **Original work** — Your contribution is your original work, or you have
   the necessary rights to submit it (for example, you hold the copyright or
   have a licence that permits sublicensing).

3. **Relicensing grant** — You grant the project maintainer
   (AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI,
   PAVIA) the right to redistribute your contributions under any
   OSI-approved open source licence, including future versions of EUPL or
   compatible licences such as AGPL-3.0-or-later, without needing to obtain
   your retroactive consent.

This lightweight CLA preserves the maintainer's ability to relicense future
versions of the software — for example, switching from EUPL-1.2 to
AGPL-3.0-or-later — which may be necessary to strengthen copyleft protection
against SaaS reuse by third parties, as anticipated by Italian PA guidelines
for software that may be accessed over a network.

The current project licence is the **European Union Public Licence v. 1.2
(EUPL-1.2)**. See the [LICENSE](LICENSE) file for the full licence text.
