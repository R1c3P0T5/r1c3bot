# Repository purpose

ricebot is a Discord bot supporting the r1c3p0t5 community.
It serves a single guild and covers two independent domains: a biweekly book club with rotating hosts, and CTF team-ups driven by CTFtime.
Python 3.13 managed with `uv`, deployed as a systemd user service with a local SQLite database.

## Principles

- Prefer the smallest direct change that solves the current task.
- Prefer the fewest moving parts that do the job.
  A helper, a parameter, a constant or a module earns its place by what it saves; when it saves nothing, inline it and say so.
- Architecture serves maintenance and naming serves reading; both are judged by the next person to open the file.
- Report the exact commands run and their observed results.
  Never fabricate test, lint, or runtime results.
- Treat the two domains as independent.
  They share storage and Discord access, nothing else.
- Keep conversation-specific context out of the repository.

## Subagents

Delegate to keep the main session small; the main session still owns design decisions and integration, and subagents return conclusions, not file contents.

- Haiku: searches, lookups, version checks, and edits with no design decision in them.
- Sonnet: scoped implementation, tests, debugging, and review; use Sonnet when unsure.
- Launch independent tasks in parallel, each with a self-contained prompt naming the files, the constraints, the expected output, and the conventions it judges against.

## Layout

- `src/ricebot/`: application code.
  `config.py` is the only module that reads the environment, and `clock.py` the only one that calls `datetime.now()`.
- `src/ricebot/store/`: all SQLite access.
  `db.py` owns the connection and the migration runner, `migrations/` holds numbered SQL files applied in order, and each domain gets one repository module.
  No SQL outside this package.
- `src/ricebot/bookclub/` and `src/ricebot/ctf/`: one package per domain, each holding its pure logic plus a single `cog.py`.
  The two must not import each other.
- `tests/`: pytest suites, named `test_<module>.py`.
- `deploy/`: the systemd user unit, templated with `%h` so it needs no editing.
- `scripts/` holds repository tooling, `.github/workflows/` CI, and `docs/` design notes.

The pure logic modules must not import `discord`; they take data and return data, so they need no gateway to test.
Cogs only translate: Discord events into domain calls, domain results into Discord messages.
The risky logic, such as date arithmetic, rotation and filtering, belongs in the pure modules, never in a cog.

No module's responsibility is "shared": shared code lives at the layer it belongs to, under its own name.
Consider grouping only when such modules exceed four or five, or a third domain appears.

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
A test failing any of the four detects nothing, however much it covers; coverage is a by-product, never the goal.
Name the fault a test is meant to catch before writing it; if you cannot, delete it.

- Derive the oracle independently of the implementation.
  Write expected values as literals, such as `datetime(2026, 10, 23, 12, 0, tzinfo=UTC)`; recomputing the expectation with the code's own expression makes infection impossible.
- Assert on values, not on truthiness, types, or lengths.
  `assert result is not None` and `assert len(rows) > 0` hold for an incorrect state, so they reveal nothing.
- Choose inputs where a wrong answer is possible: the year boundary for `schedule`, an empty, single-member, and all-inactive queue for `rotation`, and `weight == 0` and the exact threshold for CTFtime filtering.
- Do not add a test that reaches the same code, infects the same state, and checks the same output as an existing one.
  Parameterizing over inputs that all take one path adds cases, not detection.
- Do not test a parameter nobody passes; drop the parameter instead.
- A test that needs a mock to run is testing the wrong layer.
  The pure modules need none, and store tests run the real migrations against an in-memory database.
- Assert what ricebot does with discord.py and aiosqlite, never what they do themselves.
- No snapshot or golden tests of message or embed text: they fail on every wording change and get regenerated without being read.
- Cogs have no unit tests; testing them means mocking the gateway.
  Verify interaction flows by hand on a test server and say so in the commit body.

## Repository tooling

Run `uv sync`, then `uv run pre-commit install` once per clone; this installs the pre-commit, commit-msg, and pre-push hooks.
Re-run it after a hook type is added; an existing clone keeps the hooks it has.
`pre-commit` checks only tracked files, so stage new files before `uv run pre-commit run --all-files`.
To run one hook manually: `uv run pre-commit run ruff-format --files <paths>`.

Ruff is configured in `ruff.toml` and is deliberately not a dev dependency: the `ruff-pre-commit` `rev` pins its version, and a second source of truth would let `uv run ruff` and the hook disagree.

The commit-msg hook needs `--no-project`: this project's version derives from git state, so plain `uv run` reinstalls the package on every commit.
`scripts/check_commit_msg.py` is shared with the other personal repositories.
Keep its validation logic in sync with them; formatting and the scope in its failure message follow this repository.

The pre-push hooks check the lockfile and the messages of the commits being pushed, because those two failures are the expensive ones: a stale lockfile breaks everyone's `uv sync --locked`, and a bad message that reaches a shared branch can only be fixed by rewriting published history.
Formatting and build failures stay out of pre-push; a follow-up commit fixes them, and CI catches them anyway.

Never force-add a gitignored path.

CI runs the same pre-commit hooks, so a green local run means a green CI run.
It also validates every commit message in history, so a bad message stays red until the history is rewritten.

## Conventions

- Store UTC; convert to `Asia/Taipei` only for display.
  Nothing below the API boundary should see a naive datetime.
- Boot-time identifiers and secrets come from the environment through `config.py`.
  Values the community adjusts live in the `settings` table so a command can change them without a redeploy.
- The database is the source of truth; a guild event or an announcement is a projection of it.
  Neither can hold whose turn a session counts as or which reminders were sent, so neither can be authoritative for any of it.
  An event edited in the client is therefore overwritten on the next sync, and an event or announcement deleted by hand is recreated.
  This does not contradict leaving state to Discord where Discord holds all of it, such as a reaction list or a channel overwrite.
- Both domains record a scheduled side effect before performing it and delete the record if it fails, so the next loop retries.
  They keep separate tables; keep the two implementations consistent.
- Wrap every `tasks.loop` body in `try`/`except` and attach a `@loop.error` handler.
  The guard covers the whole body, the store reads that drive it included: an uncaught exception stops the loop permanently and nothing restarts it.
- Intents are `guilds`, `members` and `reactions`.
  `members` is privileged, but below 100 guilds it is a Developer Portal toggle; the host rotation reads the role's members, and no unprivileged API returns them.
  Do not add `message_content`: nothing reads message text.

## Versioning

The version derives from git tags through `uv-dynamic-versioning`, not from `pyproject.toml`.
On a tag it is clean (`1.2.0`); past a tag it carries the commit (`1.2.0.post3+ab12c52`), so the version alone identifies the running build.

Numbering follows [Semantic Versioning 2.0.0](https://semver.org/#summary), with deployment as the consumer: an incompatible change is one that needs hands on the host.

- `patch` and `minor`: `git pull && uv sync && systemctl --user restart ricebot`, with new `settings` defaults where a feature adds them.
- `major`: the upgrade needs manual work, such as a migration that cannot run automatically, a new `.env` field, or a new Discord intent or permission granted in the Developer Portal.

## Commits

### Granularity

- One logical change per commit, justifiable on its own.
  Split when the subject needs "and" or the body describes several changes; combine when a commit only makes sense together with the next one.
- Every commit keeps CI green, so `git bisect` works: `uv run pre-commit run --all-files`, `uv lock --check`, `uv run pytest`, and `uv build` must pass.
- Tests go in the same commit as the code they cover.
- Changes to existing code get one commit per type: `fix`, `perf`, `refactor`, `feat`, and `style` never share a commit.
  A refactor must not change behavior; commit it before the change it enables.
- A database migration goes in the same commit as the code that depends on it.

### Messages

Messages follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/#summary) and the [seven rules](https://cbea.ms/git-commit/#seven-rules), narrowed here and enforced by the commit-msg hook.

- Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `build`, `perf`, `style`.
- The scope is the module or domain name (e.g. `ctf`, `bookclub`, `store`); omit it for changes that span modules or the whole repository.
- Subject: lowercase imperative phrase, no trailing punctuation.
  The type prefix is why the header is neither capitalized nor held to 50 characters; the limit here is 72.
- Use the body for context, what changed, and why, without narrating the diff file by file.
  Wrap body text at 72 characters.
- Standalone URLs and machine-readable footers may exceed 72 characters.
- Do not add AI co-author signatures or session trailers.

## Writing conventions

These rules apply to names, code comments, documentation, and the shape of the code.

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

- Name things after the domain concept, and give one concept one name across every layer.
- Read a name cold and ask what a developer takes it to mean first.
  A wrong first impression is renamed; a thin one is left to the docstring.
- Omit context the location already gives: `store/ctf.py`, not `store/ctf_store.py`; `ctf/ctftime.py`, not `ctf/ctftime_client.py`.
- Modules are one lowercase word (`clock`, `rotation`, `schedule`, `settings`, `ctftime`); use `snake_case` with two words only when one is ambiguous.
- Classes use `PascalCase`; functions, variables, and modules use `snake_case`; module-level constants use `UPPER_SNAKE_CASE`.
- Prefix a helper with `_` when it is private to its module.

### Comments

- Explain why, invariants, and non-obvious constraints; do not restate what the code says.
  What a name says, a comment need not repeat; what a name cannot say, the docstring carries.
- State the fact and stop.
  Do not contrast what the code does with what it does not ("X rather than Y", "not A but B"), and do not add a clause to patch the clause before it.
- A stale comment is worse than none: it gets used as a premise.
- Keep a comment to one line, two when the constraint needs it.
  The reasoning that led there belongs in the commit body, not beside the code.
- Record the Discord or CTFtime behavior a workaround exists for, so the workaround is not removed as dead weight.
- Give public functions and classes a docstring whose first line is a summary.
  Omit it when the name and signature already say everything.
- Use `#` comments inside function bodies.

### Shape

- Break a long run of statements into paragraphs, one per stage, separated by a blank line.
  A blank line says a stage ended and cannot go stale, so prefer it to a comment that says the same.
- Head a paragraph with one line of comment only where its purpose is not evident from the calls it makes.
- A function whose every paragraph needs a heading is doing too much; split the function instead.

### Documentation

- Keep information dense: merge overlapping concepts, and do not end with a summary that restates the document.
- Use independent, unnumbered H2 sections unless the material has an intrinsic sequence.
- Verify the relevant section of a source before citing it, and link it directly.
- Keep source titles and quotations in their original language; explanatory prose may be Chinese.
