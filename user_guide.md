# Agentic OS — User Guide

This guide covers day-to-day use of Agentic OS in both interfaces: the web
workspace and the command line. For installation and testing, see
`README.md`.

---

## Part 1 — The Web Workspace

### Starting and stopping

```bash
python scripts/serve.py
```

Open <http://localhost:8000>. A session starts automatically, and
**refreshing the page reconnects to the same conversation** — as does
restarting the server, because conversations are stored durably. A new
session begins only when you ask for one or end the current one. Stop the
server with Ctrl+C; use **End session** in the sidebar to close a session
gracefully first (the agent says goodbye and the composer locks).

On your first visit a short onboarding dialog explains the basics — it
appears once and can be dismissed permanently.

### Opening it on a phone

`scripts/serve.py` also prints an address for phones on the same Wi-Fi —
something like `http://192.168.1.20:8000`. Type that into the phone's
browser; no install step is involved.

Two things are worth knowing before you do:

- **Local mode has no login.** Anyone on that network can open the app and
  read or change its saved memory. On a network you do not control, start
  it with `python scripts/serve.py --local-only`, which makes it reachable
  from your own computer only.
- **"Add to Home screen" needs HTTPS** on most phones. The app ships as an
  installable PWA, but a phone will only offer to install it from an
  address served over HTTPS — that is, from a deployment, not from a
  laptop on the local network. Over plain HTTP the app still works in the
  browser; it just is not offered as an icon.

`--port 9000` moves it off port 8000 if something else is already there.
The original `python -m uvicorn server.app:app --port 8000` still works
and does the same thing, minus the address detection.

### The workspace at a glance

- **Header** — product identity, a centered command search (opens the
  palette), live session status (Ready, Working, Offline, Error, or
  Session ended), theme toggle, and help.
- **Sidebar** (desktop) — switches between Workspace, Memory, Activity,
  and Preferences, plus New session and End session. On phones and
  tablets the four views live in a **bottom tab bar**, and the session
  actions open in a drawer from the menu button.
- **Workspace** — a greeting hero with suggested actions when the
  conversation is empty, then your messages and the agent's replies with
  timestamps, a copy button on agent replies, and auto-scroll that pauses
  while you read older messages (a **Latest** button jumps back down).
- **Context panel** (large screens) — session facts and recent activity.

### Sending messages and commands

Type in the composer and press <kbd>Enter</kbd> to send;
<kbd>Shift</kbd>+<kbd>Enter</kbd> adds a line break. Anything starting
with `/` is a command; everything else gets a tone-styled acknowledgement.

You never need to memorize commands:

- Press <kbd>Ctrl</kbd>+<kbd>K</kbd> (or <kbd>⌘</kbd>+<kbd>K</kbd>) to
  open the searchable command palette — picking a command inserts it into
  the composer.
- The help button (?) lists every command with its usage.
- An empty conversation offers suggested starting actions.

If a message fails to send (for example, offline), it is not lost — a
retry option appears, and the status badge shows the connection state.

### Managing memory and your data

Open **Memory** to see everything the agent has saved. Each entry carries
a **category** (General, Profile, Work, Projects, or Preferences) and a
**last-updated date**. You can search entries, filter by category, add new
ones, **edit any entry in place** (text and category), delete a single
entry, or delete everything. The **Data controls** card provides:

- **Export my data** — downloads memory, preferences, history, and the
  transcript as `agentic-os-export.json`.
- **Clear conversation history** — removes this session's history only.
- **Delete all memory** — permanently removes every saved entry.

Destructive actions always require confirmation. Memory is stored in
`data/memory.json` on the machine running the server and persists between
sessions and restarts. Do not store passwords or confidential information.

### Preferences

Open **Preferences** to switch the response tone (Friendly, Concise, or
Formal — replies change immediately), set **your name** (used in the
workspace greeting), choose the **language** (English or العربية — the
interface switches at once, right-to-left in Arabic, and the agent's
replies follow; the same switch sits in the header), and turn
session-history recording on or off. Changes apply to the current session; permanent
defaults are edited in `config.json`. The **Interface** card holds
browser-side settings: theme (Dark, Light, or System) and a reduced-motion
switch.

### Analytics runs

Open **Runs** to turn a goal into a governed analytics pipeline. Choose
the bundled sample sales dataset, upload a CSV file, or paste one (header
row first, up to 2 MB / 50,000 rows), then start the run. Uploading the
same file twice stores it once, and a previous upload can be re-analysed
without sending it again. Twenty-one specialist agents execute in order,
sequenced by **Hermes**, the orchestrator — planning, ingestion, data
contract, profiling, quality scoring, privacy scanning, cleaning, metric
governance, preparation, segment concentration, the four analytics
agents, causal inference, anomaly detection, sensitivity testing,
visualization, provenance, validation, and reporting. Hermes runs the stages, holds the
approval gate, and recovers an interrupted run; it never analyses
anything itself. You can
**Pause**, **Resume**, or **Cancel** at any time. Pausing is
recorded on the server, so it holds across a refresh and applies to a
background worker too, not just the tab you clicked in.

### Defining what a number means

By default a run picks the column it analyses by its name — a column
called `revenue`, or failing that the first numeric column — and the
report says which rule applied. That is a guess, and the report calls it
one: "this run analyses **revenue** because it was chosen by column name.
No definition exists for it."

To replace the guess with a decision, copy `metrics.example.json` to
`metrics.json` and describe your metrics:

```json
{
  "version": 1,
  "metrics": [
    {
      "name": "revenue",
      "title": "Net Revenue",
      "definition": "Invoiced amount after discounts, excluding tax and shipping.",
      "owner": "Finance — Group Controller",
      "certified": true,
      "columns": ["revenue", "net_revenue"],
      "formula": { "multiply": ["unit_price", "units"] }
    }
  ]
}
```

What each part buys you:

- **definition and owner** appear in every report, so the person
  approving it can see whose definition they are publishing. A metric
  marked `certified` must name an owner — certification with nobody
  accountable is a rubber stamp, and the file is rejected with a reason.
- **columns** decides which column the run analyses, replacing the name
  guess. If two of them are in the same dataset, the report names the one
  it analysed and the one it did not.
- **formula** is optional and is the part a document cannot do. Where its
  inputs are in the data, every row is checked: a `revenue` that does not
  equal `unit_price × units` is reported, with the worst rows and the
  size of each gap. One operation only — `sum`, `multiply`, `subtract`,
  `divide` — so anyone can check a row with a calculator.

No glossary ships with the project, because certifying a metric is a
statement about *your* organisation and a default owner would be an
invented one. Runs without a glossary work exactly as before and say
plainly that their measure is undefined. The file is read when the server
starts, so restart it after an edit.

### The four questions, and the one that guards them

The run answers the four questions of business analytics, each with its
own agent and its own report, plus a fifth tab that says what those
answers may be used for. Use the tabs above the report to move between
them:

| Tab | Question | What you get |
| --- | --- | --- |
| **Descriptive** | What happened? | Totals, the typical value, how much things vary, the change across the period, the biggest segment, and records worth a second look |
| **Diagnostic** | Why did it happen? | Which segment moved the number and by how much (the parts add up to the whole), and which columns move together — described as association, because moving together is not proof of cause |
| **Experiment** | Can we claim a cause? | Whether this data is entitled to a causal claim at all. If it records a control and a treatment group, the difference between them as a **range** — because one number implies a precision no sample has — and whether that range is wide enough to include no change. If it does not, a plain no, followed by the experiment that would settle it: how many observations per group, and the smallest change your existing rows could already detect |
| **Predictive** | What will happen? | The next three periods, if the current pattern continues, with the accuracy this method achieved when tested against past periods it had not seen. Too little history and it tells you so instead of guessing |
| **Prescriptive** | What should I do? | The options your data supports, what each is worth, a recommendation, and — stated plainly — the assumption behind the ranking and how close the call was |

Each report opens with one sentence in plain business language. That
sentence is the point: a finding nobody can act on is not a finding. The
technical method for every figure is kept in a table at the bottom of each
report, so anything can be checked without cluttering what you read
first.

A closed or crashed browser loses nothing: runs are stored durably and
resume from where they stopped. By default a run advances while the Runs
view is open; if the person running the server has started a background
worker (`python scripts/worker.py`), runs continue with no browser open.

The finished report shows charts, key metrics, and a findings table where
every claim lists its evidence. Publishing the report into the local
**Obsidian vault** (`vault/` — open it with Obsidian's "Open folder as
vault") always requires your explicit approval; rejecting writes nothing.

### Activity

Open **Activity** for a timestamped timeline of real events — session
started or restored, memory saved, preference changed, history cleared,
requests completed or failed, and connection changes — filterable by
**System, Memory, Preferences, or Errors**, alongside a **Session
health** card showing connection state, whether memory persistence is
active, entry counts, and the time of the last successful response.

Note: memory saved with the CLI's `/remember` command gets the *General*
category; categories are chosen in the web interface.

### Themes and accessibility

- The theme toggle switches light/dark; with no choice made, the app
  follows your system setting. The choice is remembered.
- The entire app works with a keyboard alone: <kbd>Tab</kbd> moves focus
  (a skip-link jumps straight to the composer), dialogs trap focus and
  close with <kbd>Escape</kbd>, and important changes are announced to
  screen readers.
- System reduced-motion settings are respected.

---

## Part 2 — The Command-Line Interface

### Starting and stopping

```bash
python main.py
```

To stop, enter `/exit` — anything typed after it on the same line is
ignored, so `/exit now` also closes the application. Pressing Ctrl+C
(or Ctrl+D) closes it safely as well.

Every line you type after `You:` is sent to the agent. Empty input is
rejected with a gentle reminder — the application never crashes on blank
lines.

---

## Supported Commands (both interfaces)

| Command        | Purpose                                   | Example                        |
| -------------- | ----------------------------------------- | ------------------------------ |
| `/help`        | Displays available commands               | `/help`                        |
| `/remember`    | Saves information                         | `/remember My name is Ahmad`   |
| `/recall`      | Displays all saved information            | `/recall`                      |
| `/forget`      | Removes one saved item, or everything     | `/forget memory_1`, `/forget all` |
| `/set`         | Updates a preference                      | `/set tone concise`            |
| `/preferences` | Displays current preferences              | `/preferences`                 |
| `/history`     | Displays session history                  | `/history`                     |
| `/clear`       | Clears conversation history               | `/clear`                       |
| `/exit`        | Ends the session                          | `/exit`                        |

Command names are case-insensitive (`/HELP` works), but saved information
and preference values keep the exact text you typed. The `/history`
command itself is not added to the history it displays — it shows only
the requests that came before it.

## How Preferences Work

| Preference     | Default    | Effect                                                  |
| -------------- | ---------- | ------------------------------------------------------- |
| `tone`         | `friendly` | Response style: `friendly`, `concise`, or `formal`      |
| `language`     | `English`  | `English` or `Arabic`: the agent replies in it and the web interface follows |
| `save_history` | `true`     | When `false`, requests are not recorded in the history  |

Values `true` and `false` are stored as real booleans, so
`/set save_history false` switches history recording off immediately.
An unrecognized `tone` value falls back to the friendly style.

## How Memory Works

`/remember` (or the Memory panel) stores information under an automatic
key (`memory_1`, `memory_2`, ...). Memory is written to
`data/memory.json`, so it **remains available after restarts**. Keys stay
unique even after deletions, so removing one entry never overwrites
another.

## Clearing Stored Information

- Delete a single entry in the Memory panel, or `/forget memory_1`.
- Clear everything with the panel's **Clear all** button (asks for
  confirmation) or `/forget all`.
- **Clear history** in the sidebar (asks for confirmation) or `/clear`
  clears the conversation history only; it does not touch saved memory.
- You can also delete `data/memory.json` while the server is stopped — it
  is recreated automatically.

## Common Errors and Solutions

| Message                                                | Cause and solution                                                       |
| ------------------------------------------------------ | ------------------------------------------------------------------------ |
| `Configuration file not found: ...`                    | Run from the project root folder, where `config.json` lives.             |
| `Configuration file is not valid JSON: ...`            | Fix the JSON syntax in `config.json` (a missing comma or quote).         |
| `Unknown command: /... Enter /help ...`                | The command is misspelled or unsupported — check `/help`.                |
| `Please provide information to remember.`              | `/remember` was used without any text after it.                          |
| `Usage: /set <setting> <value>.`                       | `/set` needs both a setting name and a value.                            |
| `No saved information found for ...`                   | The key does not exist — check `/recall` or the Memory panel.            |
| `Cannot reach the Agentic OS server.` (web)            | The server is not running or the connection dropped — a retry is offered.|
| `This session has ended.` (web)                        | Start a new session from the sidebar.                                    |

Invalid or unexpected input never crashes the application; the agent
always answers with an explanation of what to do instead.

## Privacy and Data Storage

- Saved memory is **plain, unencrypted text** in `data/memory.json`;
  analytics runs and reports are stored in `data/agentic.db`; approved
  reports are written to `vault/`. Everything stays on the machine running
  Agentic OS — nothing is sent over the internet unless you configure the
  optional Groq narrator on the server.
- Conversations (messages, preferences, and history) are stored durably
  alongside runs, so they survive a restart. The Activity timeline is
  browser-side and resets on reload.
- The web app stores three things in your browser: the theme choice, the
  onboarding-dismissed flag, and the current session id (so a refresh can
  reconnect). It stores no personal content.
- Do not store passwords, API keys, or confidential personal information
  with `/remember`.
