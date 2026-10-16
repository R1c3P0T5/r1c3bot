# Repository purpose

ricebot is a Discord bot supporting the r1c3p0t5 community.
It serves a single guild and covers two independent domains: a biweekly book club (events, rotating hosts, attendees) and CTF team-ups driven by CTFtime (contest announcements, opt-in, per-contest discussion channels).
Python 3.13 managed with `uv`, deployed as a systemd user service with a local SQLite database.

## Principles

- Prefer the smallest direct change that solves the current task.
- Report the exact commands run and their observed results.
  Never fabricate test, lint, or runtime results.
- Treat the two domains as independent.
  They share storage and Discord access, nothing else.
- Keep conversation-specific context out of the repository.

## Subagents

Delegate to subagents to save tokens, keep the main session small, and run independent tasks in parallel.
The main session owns design decisions and integration; subagents return conclusions, not file contents.

- Haiku: searches, lookups, version checks, and edits that involve no design decisions.
- Sonnet: scoped implementation, tests, debugging, and review.
  Use Sonnet when unsure.
- Launch independent tasks in parallel.
  Give each a self-contained prompt stating the files, constraints, and expected output.

## Layout

- `src/ricebot/`: application code.
  `config.py` is the only module that reads the environment, and `clock.py` the only one that calls `datetime.now()`.
- `src/ricebot/store/`: all SQLite access.
  `db.py` owns the connection and the migration runner, `migrations/` holds numbered SQL files applied in order, and each domain gets one repository module.
  No SQL outside this package.
- `src/ricebot/bookclub/` and `src/ricebot/ctf/`: one package per domain, each holding its pure logic plus a single `cog.py`.
  The two must not import each other.
- `tests/`: pytest suites, named `test_<module>.py`.
- `scripts/`: repository tooling.
- `deploy/`: the systemd user unit, templated with `%h` so it needs no editing.
- `.github/workflows/`: CI.
- `docs/`: design notes.

The pure logic modules must not import `discord`.
They take data and return data, so they are testable without mocking the gateway.
Cogs only translate: Discord events into domain calls, domain results into Discord messages.
Put the risky logic, such as date arithmetic, rotation, and filtering, in the pure modules, never in a cog.

No module's responsibility is "shared".
Shared code lives at the layer it belongs to under its own name.
Consider grouping only when shared modules exceed four or five, or a third domain appears.

## Run and test

```sh
uv sync
uv run ricebot
uv run pytest
uv run pytest tests/test_schedule.py
```

Start with the narrowest relevant test, then run the full suite.

## Tests

Judge a test by the RIPR model: it must reach the faulty location, infect the program state, propagate that infection to an observable output, and have an oracle that reveals it.
A test failing any of the four detects nothing, however much it covers.
Name the fault a test is meant to catch before writing it; if you cannot, delete it.
Coverage is a by-product, never the goal.

- Derive the oracle independently of the implementation.
  Write expected values as literals, such as `datetime(2026, 10, 23, 12, 0, tzinfo=UTC)`.
  Recomputing the expectation with the same expression the code uses makes infection impossible, so the test passes with the code's own bug.
- Assert on values, not on truthiness, types, or lengths.
  `assert result is not None` and `assert len(rows) > 0` hold for an incorrect state, so they reveal nothing.
- Choose inputs where a wrong answer is possible: the year boundary for `schedule`, an empty, single-member, and all-inactive queue for `rotation`, and `weight == 0` and the exact threshold for CTFtime filtering.
- Do not add a test that reaches the same code, infects the same state, and checks the same output as an existing one.
  Parameterizing over inputs that all take one path adds cases, not detection.
- A test that needs a mock to run is testing the wrong layer.
  The pure modules need none, and store tests run the real migrations against an in-memory database.
- Assert what ricebot does with discord.py and aiosqlite, never what they do themselves.
- No snapshot or golden tests of message or embed text.
  They fail on every wording change and get regenerated without being read.
- Cogs have no unit tests; testing them means mocking the gateway.
  Verify interaction flows by hand on a test server and say so in the commit body.

## Repository tooling

Run `uv sync`, then `uv run pre-commit install` once per clone; this installs both the pre-commit and commit-msg hooks.
`pre-commit` checks only tracked files, so stage new files before `uv run pre-commit run --all-files`.
To run one hook manually: `uv run pre-commit run ruff-format --files <paths>`.

Ruff is configured in `ruff.toml`, not `pyproject.toml`, and is deliberately not a dev dependency.
Its version is pinned by the `ruff-pre-commit` `rev`, and a second source of truth would let `uv run ruff` and the hook disagree.

The commit-msg hook needs `--no-project`: this project's version derives from git state, so plain `uv run` reinstalls the package on every commit.
`scripts/check_commit_msg.py` is shared with the other personal repositories.
Keep its validation logic in sync with them, but let formatting follow this repository's Ruff config and the example in its failure message name a scope that exists here.

Never force-add a gitignored path.

CI runs the same pre-commit hooks, so a green local run means a green CI run.
It also validates every commit message in history, which means a bad message stays red until the history is rewritten.

## Conventions

- Store UTC; convert to `Asia/Taipei` only for display.
  Nothing below the API boundary should see a naive datetime.
- Boot-time identifiers and secrets come from the environment through `config.py`.
  Values the community adjusts live in the `settings` table so a command can change them without a redeploy.
- Both domains record a scheduled side effect before performing it and delete the record if it fails, so the next loop retries.
  They keep separate tables; keep the two implementations consistent.
- Wrap every `tasks.loop` body in `try`/`except` and attach a `@loop.error` handler.
  An uncaught exception stops the loop permanently and does not restart it.
- Intents are `guilds` and `reactions` only.
  Do not add `message_content`: it is privileged, needs Developer Portal approval, and nothing reads message text.

## Versioning

The version derives from git tags through `uv-dynamic-versioning`; it is not written in `pyproject.toml`.
On a tag the version is clean (`1.2.0`); past a tag it carries the commit (`1.2.0.post3+ab12c52`), so the version alone identifies the running build.

Semantic versioning applies, with deployment as the consumer.

- `patch`: bug fixes.
  `git pull && uv sync && systemctl --user restart ricebot`.
- `minor`: new commands or features.
  Same deployment, possibly new `settings` defaults.
- `major`: the upgrade needs manual work, such as a migration that cannot run automatically, a new `.env` field, or a new Discord intent or permission granted in the Developer Portal.

## Commits

### Granularity

- One logical change per commit, justifiable on its own.
  Split when the subject needs "and" or the body describes several changes; combine when a commit only makes sense together with the next one.
- Every commit keeps CI green, so `git bisect` works: `uv run pre-commit run --all-files`, `uv lock --check`, and `uv build` must pass.
  `uv run pytest` joins that list with the first test; it exits 5 while `tests/` is empty.
- Tests go in the same commit as the code they cover.
- Changes to existing code get one commit per type: `fix`, `perf`, `refactor`, `feat`, and `style` never share a commit.
  A refactor must not change behavior; commit it before the change it enables.
- A database migration goes in the same commit as the code that depends on it.

### Messages

- Use `type(scope): subject`.
  The scope is the module or domain name (e.g. `ctf`, `bookclub`, `store`); omit it for changes that span modules or the whole repository.
- Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `build`, `perf`, `style`.
- Subject: lowercase imperative phrase, no trailing punctuation.
  The header must not exceed 72 characters.
- Separate an optional body from the header with a blank line.
- Use the body for context, what changed, and why.
  Do not narrate the diff file by file.
  Wrap body text at 72 characters.
- Standalone URLs and machine-readable footers may exceed 72 characters.
- Do not add AI co-author signatures or session trailers.

## Writing conventions

These rules apply to names, code comments, and documentation.

- Be concise and direct.
  Say it once; omit what the context already makes clear.
- Prefer plain wording.
  Keep precise, searchable English technical terms where a translation would be less clear.
- Use full-width punctuation in Chinese prose.
  Insert a half-width space between adjacent CJK characters and Latin letters or digits.
  Use half-width punctuation in English prose.
- Write one sentence per line in Markdown.
  A one-line change then produces a one-line diff.

### Naming

- Name things after the domain concept.
  Modules are one lowercase word (`clock`, `rotation`, `schedule`, `settings`, `ctftime`); use `snake_case` with two words only when one is ambiguous.
- Omit context the location already gives: `store/ctf.py`, not `store/ctf_store.py`; `ctf/ctftime.py`, not `ctf/ctftime_client.py`.
- Classes use `PascalCase`; functions, variables, and modules use `snake_case`; module-level constants use `UPPER_SNAKE_CASE`.
- Prefix a helper with `_` when it is private to its module.

### Comments

- Explain why, invariants, and non-obvious constraints; do not restate what the code says.
- Record the Discord or CTFtime behavior a workaround exists for, so the workaround is not removed as dead weight.
- Give public functions and classes a docstring whose first line is a summary.
  Omit it when the name and signature already say everything.
- Use `#` comments inside function bodies.

### Documentation

- Keep information dense.
  Merge overlapping concepts; do not end with a summary that restates the document.
- Use independent, unnumbered H2 sections unless the material has an intrinsic sequence.
- Verify the relevant section of a source before citing it, and link it directly.
- Keep source titles and quotations in their original language; explanatory prose may be Chinese.
