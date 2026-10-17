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
with `/` is a command. Everything else is understood as a sentence, in
English or Arabic, and acted on:

| You write | The agent does |
| --- | --- |
| “Remember that the Q4 review is on Monday” | saves it to memory |
| “What do you remember about coffee?” | lists matching memory |
| “Analyse the sample sales data” / “analyse quarterly_sales by team” | starts a run and opens it in Runs |
| “Is it done?” | reports the latest run's progress |
| “Why did revenue move?” / “What should we do?” | quotes that section's headline from the latest report |
| “Be concise” / “Reply in Arabic” / “Call me Ahmad” | changes a preference |
| “Forget everything” | asks you to confirm — nothing is deleted until you reply “yes” |
| “What can you do?” | lists the above |

A sentence outside that vocabulary gets an honest “not understood” in
your chosen tone, with examples of what to ask. With no language model
configured — the default — a set of rules does the understanding and
every reply is marked as such; a configured model widens what is
understood but never what can be done (ADR 0019).

You never need to memorize commands:

- Press <kbd>Ctrl</kbd>+<kbd>K</kbd> (or <kbd>⌘</kbd>+<kbd>K</kbd>) to
  open the searchable command palette — picking a command inserts it into
  the composer.
- The help button (?) lists every command with its usage.
- An empty conversation offers suggested starting actions.

If a message fails to send (for example, offline), it is not lost — a
retry option appears, and the status badge shows the connection state.

If the operator has configured an **agent runtime** — an optional loop
that may call several of the assistant's tools for one sentence — a
sentence the assistant cannot place as one exact action goes to it. The
reply then shows every tool's own text, verbatim and in order, followed
by the runtime's closing line, and is labelled *run by <name> · N tool
calls*. A runtime can never delete anything: deletion is asked for
directly and confirmed in the next message, exactly as before. An exact
sentence such as “remember that …” never reaches the runtime.

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
the bundled sample sales dataset, a dataset you stored before, or a new
file, then start the run. A file can be CSV or TSV, an Excel workbook
(`.xlsx`), JSON or JSON Lines: up to 4 MB as uploaded, 50,000 rows, and
10 MB once converted to CSV. The server reads it, says how many rows it
found, and notes anything worth checking, such as error cells or which
sheet of a workbook it read. CSV must be UTF-8; in Excel, save as "CSV
UTF-8". You can still paste CSV text, header row first. The **Datasets**
page adds files without starting a run. The same data is stored once,
whatever format it came in, and a stored dataset is analysed again without
being sent again. Twenty-one specialist agents execute in order,
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

If the operator has registered **custom stages** — a domain agent written
outside this repository, such as the bundled target-attainment example —
they appear in the same pipeline list at the place they asked for, and a
stage with a question of its own gets its own report tab plus a **Custom
stages** section in the full report. Where the operator has also defined
**profiles**, a *Pipeline profile* selector appears above the goal; the
text under it names the stages the chosen profile adds, and the run
records which profile it ran with. A custom stage's claims pass through
the same validator as the built-in ones, and if a custom stage fails the
report says so rather than leaving it out. Registering a stage is an
operator task: see "Custom agents" in the README.

### Saying what each column is

A run needs to know three things about a dataset: which number it is
about, what to break that number down by, and which column is time.
Unless you say, it guesses from column names. To say, open **Datasets**
and choose **Columns** beside a dataset. A file you have just added
opens there by itself.

The panel shows the first rows, then every column with what it holds
(numbers, dates or text), a suggested role and the reason for it. Give
each column one role:

- **Measure** — a number. Pick the one the analysis is about under
  *Measure analysed*; the others are checked as possible drivers.
- **Dimension** — a category to break totals down by. Pick one under
  *Breakdown*, or none.
- **Date** — at most one column. Choose how dates are written (day or
  month first) and what to sum them by: day, month, quarter or year. The
  automatic choice keeps the data's own detail until there would be more
  than 36 periods.
- **Ignore** — left out of the analysis, such as IDs and free-text notes.
  The quality and privacy checks still read it.

A mapped measure reads currency signs and codes, `(300)` as −300, and
Arabic digits. A comma must group thousands: `12,5` is refused rather
than guessed, and the report counts such cells. Dates are read in ISO
form, as day, month and year in the order you chose, as quarters, and
with English or Arabic month names, and trends are ordered by time.

**Save mapping** checks your choices against every row. If something
cannot work, such as text mapped as a measure or dates that could be day
first or month first, nothing is saved. A box at the top lists each
problem and links to its field, and the message also appears beside the
field. Each run takes a copy of the mapping when it starts, so changing
the mapping later never changes a finished report. **Use automatic
detection** removes the mapping. Pasted CSV and the sample always use
automatic detection.

### Joining other datasets

A run can bring columns from other stored datasets onto each row of its
main dataset, such as a product's category from a product list or a
month's target from a planning sheet. In the new-analysis form, choose
a stored dataset or upload a file, then **Join a dataset** under *Join
other datasets*:

- **Dataset to join** — any other dataset you have stored.
- **Key** — a column of the main table and the column of the joined
  dataset that holds the same values. When both have a column of the
  same name, it is suggested. Up to three key pairs.
- **Rows without a match** — *Keep every row* leaves every total as it
  was and leaves the joined columns empty for unmatched rows; *Keep only
  matched rows* drops them, and the report says how many.

**Preview the merge** shows the rows in and out, how many rows found a
match in each dataset, the keys that found none, and the first rows of
the merged table. A joined dataset whose key appears more than once is
refused, because a row would otherwise be counted twice. After a
preview you can choose a column from a joined dataset under *Break
totals down by*. Up to four datasets can be joined; the run then shows a
Data Merge Agent right after cleaning.

### Downloading the cleaned data

Once a run has cleaned its data, and merged any joined datasets, **Download
cleaned data (CSV)** at the top of the run saves the table it analysed:
the rows it kept, measures as plain numbers and mapped dates as the
periods it summed by. The file opens correctly in Excel, Arabic
included, and text that a spreadsheet would run as a formula (a cell
starting with `=`, `+`, `-` or `@`) is saved with a leading apostrophe so
it stays text.

### Dashboards

**Dashboards** opens any analysis whose data has been cleaned as a set of
pages, every figure computed from the same cleaned table the report used.
A finished analysis also has **Open dashboard** at the top.

- **Overview** — records, the measure's total and its value per record,
  the largest group, the trend and the top groups.
- **Breakdown** — the measure by any text column, as totals or per
  record, largest first.
- **Trend** — totals and per-record values by period (when the data has
  a date).
- **Distribution** — how the measure spreads over twelve equal ranges.
- **Relationship** — the measure against another number, from an even
  sample of at most 500 records.
- **Records** — the rows themselves, 25 at a time, sortable.

The **Filters** card keeps values of any text column and a range of
periods; a filter applies on every page. Every chart has **Show the
numbers**, a table of its figures with **Show records** beside each
group, which filters to that group and opens its rows. The page, the
filters and every choice are in the address, so a reload keeps them and
a link opens the same view for anyone who can open the analysis.

### Live sources

**Datasets → Live sources** keeps files that change: give a name, an
`https://` address of a public file (CSV, TSV, Excel, JSON or JSON Lines,
up to 4 MB), how often to refresh (every 15 minutes to every week, or
only when you ask) and the question each analysis should answer.

Each refresh fetches the file. If it has not changed, nothing happens and
the source says **No change**. If it has, the new version is stored as a
dataset, gets the previous version's column mapping when that still fits
every row, and is analysed. The analysis waits for approval like any
other: nothing publishes itself. A refresh that fails says why, and a
scheduled source waits longer after each failure, up to a day. **Pause**
stops the schedule; **Refresh now** fetches at once.

The badge beside the title says whether the page is following changes:
**Live**, **Reconnecting…** or **Offline**, with the time of the last
update when it is not live. A dashboard over a live source's analysis
shows the same badge and, when a newer snapshot has been analysed,
offers **Open the newer analysis**; the figures on screen never change
by themselves.

A server administrator can limit which hosts sources may come from.
Addresses on a private network, addresses that redirect, and addresses
that carry a password or key are refused. **Refresh now** works once a
minute per source.

### Models

Choose the **models** pipeline profile when starting an analysis to add
four models to it: what predicts the measure (a regression), which
records land in its top quarter, or in the classes of a text column the
operator names (a classification), whether the records fall into natural groups (a
clustering) and whether the measure follows a season (a seasonal
forecast).

Each model is tested on data it did not learn from: the latest fifth of
the periods, every fifth record when there is no date, or the last full
season. It is compared with the guess a person would make without it:
the average, the most common class, or "same as last period" or "same
as a season ago". The **Models** card under the charts gives the
verdict first. A model has to beat its guess by at least 5% to count;
otherwise the card says it is weak and should not be used. A weak model
is a finding too.

The models show what moves with the measure, not what causes it. An
input recorded after the outcome makes a model look better than it is,
so leave such columns out of the mapping.

### Defining what a number means

Without a column mapping, a run picks the column it analyses by its
name — a column called `revenue`, or failing that the first numeric
column — and the report says which rule applied. That is a guess, and the report calls it
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

Reports are written in the language the interface was in when you
started the run: start it in Arabic and every headline, finding and
report is Arabic, right-to-left, with the same figures the English would
show. Column names, group names and the calculation table keep the
notation of your data. To get the other language, switch and start a new
run; an existing report is never rewritten, because what you approve is
what gets published.

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

Every line you type after `You:` is sent to the agent. Sentences work
here too — “remember that…”, “what do you remember?”, “be concise”,
“reply in Arabic” — through the same rules the web interface uses;
analytics runs need the web interface, and the agent says so. Empty
input is rejected with a gentle reminder — the application never crashes
on blank lines.

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
