# Contributing to Agentic OS

This page takes a team member from no access to a first merged change.
You do not need to write code to take part. Using the app and reporting
what you find counts, and so does improving a document.

Repository: <https://github.com/ahmadzayan-hub/agentic-os-final-project>
(the old address, `ahmadzayan-hub/11`, redirects here).

## Ways to take part

| You want to… | You need | Start at |
|---|---|---|
| Try the app and report what you find | A GitHub account | [Report a bug or an idea](#report-a-bug-or-an-idea) |
| Fix or improve a document | Write access | [Edit in the browser](#edit-in-the-browser) |
| Run the app on your own computer | Python, Node.js, Git | [Set up locally](#set-up-locally) |
| Change the code | All of the above | [Make a change](#make-a-change) |

## Get access

1. Create a GitHub account if you do not have one, and send your
   **username** to the project owner.
2. Accept the invitation from the email GitHub sends, or from
   <https://github.com/notifications>. It expires after seven days, so
   ask for a new one if you missed it.

The repository is public, so you can read, clone, open issues and
propose changes from a fork without an invitation. The invitation lets
you create branches here and review each other's pull requests.

## Report a bug or an idea

Open **Issues → New issue** and include:

- what you did, step by step, and what you expected
- what happened instead, with a screenshot if it helps
- the language (English or Arabic), and your device and browser

A screenshot must not show an API key, a password, or anyone's personal
details. One issue per problem keeps the discussion and the fix together.

## Edit in the browser

For a typo or a clearer sentence you need no local setup:

1. Open the file on GitHub and press the pencil icon (**Edit this file**).
2. Make the change and press **Commit changes…**
3. Choose **Create a new branch for this commit and start a pull
   request**. Do not commit straight to the default branch.
4. Describe the change in the pull request that opens, and ask a
   teammate to review it.

## Set up locally

You need Python 3.10 or newer, Node.js 20.19+ or 22+, and Git.

```bash
git clone https://github.com/ahmadzayan-hub/agentic-os-final-project.git
cd agentic-os-final-project

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd frontend && npm ci && npm run build && cd ..
python scripts/serve.py
```

Then open <http://localhost:8000>. No API keys, accounts or database are
needed: the app runs fully on your computer, with its data in local files.
The README explains the optional extras: model narration, PostgreSQL and
the background worker.

## Make a change

The default branch is currently `claude/agentic-os-final-project-53j6ql`.
GitHub shows it on the repository's front page, and it is the branch a
fresh clone starts on. Every change reaches it through a pull request.

```bash
git switch claude/agentic-os-final-project-53j6ql
git pull                                    # start from the latest work
git switch -c yourname/short-topic          # e.g. sara/arabic-report-wording

# … edit, then run the checks below …

git add -A
git commit -m "Say what changed and why"
git push -u origin yourname/short-topic
```

GitHub then offers **Compare & pull request**. Fill in the checklist it
shows, ask one teammate to review, and merge once the review is approved
and CI is green. Keep each pull request to one topic: a small one gets
reviewed today, while a large one waits.

If someone else's work lands first, bring it into your branch with
`git pull origin claude/agentic-os-final-project-53j6ql`, resolve any
conflicts, and push again.

## Checks before a pull request

```bash
python -m unittest discover tests     # whole Python suite

cd frontend
npm run typecheck
npm test                              # unit tests
npm run build
npx playwright install chromium       # first time only
npm run e2e                           # end-to-end + accessibility
```

Without a local PostgreSQL the database tests skip. That is expected, and
CI runs them against a real PostgreSQL. CI runs every check above on each
push, plus a dependency audit, so if you cannot run the end-to-end tests
on your machine, say so in the pull request and let CI run them.

## Ground rules

This repository is public. Anything pushed here can be read and copied by
anyone, and stays in the history even after it is deleted.

1. **No secrets.** Never commit API keys, passwords, tokens or a `.env`
   file. `.env` is already ignored, and `.env.example` holds placeholders
   only. If a key does land in a commit, tell the owner at once: deleting
   the line does not remove it from history, so the key has to be revoked
   and replaced.
2. **No personal data or course files.** Keep the course materials out of
   this repository, along with anything containing names, student
   numbers, emails or phone numbers. Put them in a `private/` folder
   inside your clone, which Git ignores, or anywhere outside the clone.
3. **No raw data to a language model.** The app's model only phrases
   facts that were already calculated and checked. It never sees a row of
   the dataset, and changes must keep it that way.
4. **No force-push and no history rewriting.** Do not delete branches
   that are not yours. Undo a mistake with a new commit (`git revert`).
5. **Claims must be true.** A screenshot, test count or score in a
   document must come from something that was actually run.
   `tests/test_docs.py` checks some of these claims automatically.
6. **Decisions get written down.** A change to how the system behaves
   comes with a decision record in `docs/adr/`. Copy the structure of the
   latest one.

## Where things are

| Path | What it holds |
|---|---|
| `main.py`, `agent.py` | The command-line interface and the agent behind it |
| `server/` | The web API, the analytics pipeline (`analytics.py`), runs and storage |
| `frontend/src/` | The React web app; `i18n/` holds the English and Arabic text |
| `tests/`, `frontend/e2e/` | Python tests; browser end-to-end tests |
| `docs/` | Architecture, agent catalogue, known limitations, decision records |
| `examples/` | A custom stage and agent runtimes to copy from |
| `project-progress.md`, `session-logs.md`, `Memory.md` | What is happening now, what each session did, and durable facts |
| `brain/` | The second brain: linked notes, starting at `brain/Home.md`. Open the folder in Obsidian, or read it on GitHub |
| `CLAUDE.md`, `.claude/` | Instructions, hooks and skills for Claude Code sessions |

For how to use the app, see `user_guide.md`. For the design and its
trade-offs, see `docs/ARCHITECTURE.md` and `docs/adr/`. For how the
repository is run day to day, see `docs/PLAYBOOK.md`.

## Working with Claude Code

If you use Claude Code, this repository briefs every session for you. Trust
the folder when Claude Code asks, and keep `python3` on your path. A
SessionStart hook summarises the current focus, the last session's next
steps and the brain's health. Then:

- say **start session** to have Claude orient itself;
- say **wrap up** at the end, so it logs the session, updates the board,
  `Memory.md` and the brain, and commits.

The hooks only read the repository and write to the git-ignored
`.claude/state/`. The one exception is the safety net at session end, which
may append an automatic entry to `session-logs.md`. To turn the hooks off
for yourself alone, put `{"disableAllHooks": true}` in
`.claude/settings.local.json`.

## Getting help

Open an issue and label it **question**, or ask in the team chat with a
link to the file or issue you mean. Questions asked in an issue stay
findable for the next person.
