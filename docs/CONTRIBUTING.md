# Contributing

*Deutsche Version: [CONTRIBUTING.de.md](CONTRIBUTING.de.md)*

Thank you for your interest. The project is privately developed until Phase 7 (first automated daily report). From that point on, this document applies.

## What we welcome

- **Bug reports** on measurement logic, incorrect scores, missed outages.
- **New node proposals.** Include the node URL, operator, and a rough indication of its expected traffic share.
- **Methodology improvements** — argued clearly in an issue before any PR.
- **Translations** of user-facing strings (the dashboard is multilingual; the repository documentation is bilingual DE/EN).
- **Dashboard improvements** — accessibility, internationalisation, performance.

## What is out of scope

- **Steem-core client-side patches** — this repository monitors nodes, it does not fork `steemd`. Propose those changes upstream.
- **Adding write endpoints to the API.** The API is read-only and stays that way.
- **Replacing SQLite** unless the database actually shows stress in production. Premature database migrations have no benefit here.
- **Anything touching the reporter account keys.** Key handling is the author's responsibility.

## Workflow

1. Open an issue describing the problem or proposal. For non-trivial changes, wait for confirmation before coding.
2. Fork, branch, implement, test.
3. Submit a PR. Include a short description, reference the issue, list measurement or score-formula changes separately from plumbing.
4. Expect review within a week. If a change affects published numbers, the review covers methodology implications too.

## Code style

- Python 3.12, type hints on public functions, black formatting, ruff for lint.
- Keep modules small. The project's complexity is in the methodology, not in the plumbing — the code should reflect that.
- Tests for score formula changes are required. A change that alters published numbers without tests is rejected.
- Comments should explain why, not what. See the root project guidance if in doubt.

## Commit messages

- Subject line in imperative ("Add node X to initial list", not "Added").
- Reference the issue if there is one.
- Body explains the reasoning for non-obvious changes.

## Data and privacy

Never add code that collects user data — see [SECURITY.md](SECURITY.md). This rule has no exceptions and is enforced in review.

## Communication

- Technical discussions: GitHub Issues and PRs.
- Concept-level discussions: Steemit or Discord via @greece-lover.
- Urgent security issues: private channel to @greece-lover.
