# ADR 0034 — Live data: connectors that snapshot, scheduled re-runs, pushed updates

**Status:** Accepted
**Date:** 2026-10-17
**Milestone:** A7 in `project-progress.md`; phase 6 of `docs/UI_PLAN.md`
**Keeps:** content-addressed datasets (ADR 0024), the column mapping (ADR 0025), durable runs and worker leases (ADR 0006), tenancy, the approval gate (no run publishes itself), raw data never sent to a model

## Context

Every dataset so far arrives by hand: a file uploaded, or text pasted. A dashboard over last week's file is a report, not a live view. Three things are missing:

1. a **source** the system can fetch again by itself;
2. a **schedule** that fetches it and analyses what changed;
3. a way for an open page to **learn** that something changed, without asking every few seconds.

A server that fetches a URL on a user's behalf is also the classic way to reach what the user cannot: the cloud metadata service at `169.254.169.254`, a database on `localhost`, an admin page on the private network (server-side request forgery). Live data is only acceptable if that is closed off.

## Decision

### 1. A connector is a saved source that snapshots into datasets

A connector belongs to one owner and holds a name, an `https://` address, an optional format and sheet, an optional refresh interval (15 minutes to a week, or none for manual only), and the analysis to run on each new snapshot (goal, report language, pipeline profile).

Refreshing it fetches the address and reads the file with the dataset reader (ADR 0024), so every format and limit is the upload's: 4 MB, CSV, TSV, Excel, JSON and JSON Lines. The result is stored like an upload, content-addressed:

- **The same content as last time** is recorded as *unchanged*, and nothing else happens.
- **New content** becomes a new dataset. If the previous snapshot had a column mapping and it still fits every row of the new one, the new snapshot gets a copy; otherwise it runs unmapped and the refresh says why. A run is started on it with the connector's goal, and stops at the approval gate like any run.

### 2. Fetching is fenced

| Rule | Why |
| --- | --- |
| `https` only | Credentials and content stay encrypted in transit |
| Every address the host resolves to must be public (`ipaddress.is_global`): no loopback, private, link-local, multicast, reserved or unspecified address, and no IPv4 hidden in IPv6 | Closes the metadata service, localhost and the private network |
| The connection is made to the address that was checked, with the host name kept for TLS | A second DNS answer cannot swap in a private address between the check and the connection (DNS rebinding) |
| Redirects are refused, with the target named | A public address cannot hand the request to a private one |
| 4 MB, read in pieces, and 15 seconds | The same ceiling an upload has; a slow or endless source cannot hold a worker |
| `AGENTIC_OS_CONNECTOR_HOSTS`, when set, lists the only hosts allowed | An operator can close it further |
| No proxy | A proxy would resolve the name itself and undo the check; where only a proxy reaches the internet, a refresh fails and says so |

For end-to-end tests only, `AGENTIC_OS_CONNECTOR_FIXTURES` maps addresses on the reserved `fixtures.invalid` host to files in one folder. The name is reserved by RFC 2606 and can never be a real host.

### 3. The worker refreshes what is due

The background worker (ADR 0006) also claims connectors whose refresh is due, with the same kind of lease runs use, so two workers never refresh the same source. A failed refresh is recorded with its reason and retried later, waiting twice as long after each failure up to a day. **Refresh now** does the same work at once from the interface, which is how a deployment without a worker (a serverless one) refreshes.

### 4. Pushed updates: one event stream per owner

`GET /api/events` is a server-sent event stream of the owner's runs and connectors as they change: each event names what changed and carries an `id`, the position to resume from. The server reads changes from the database, so an event written by the worker in another process reaches every open page.

- A comment line every 15 seconds keeps the connection open through proxies.
- The stream ends after at most 55 seconds; the client reconnects with `Last-Event-ID` and receives everything since. A platform that limits how long a request may run then costs nothing.
- The client reads the stream with `fetch`, so the bearer token travels in a header, as on every other request. It reconnects after an error with a growing, randomised wait up to 30 seconds.
- The interface shows the connection as **Live**, **Reconnecting** or **Offline**, announces a finished run politely to screen readers, and says how old the data on screen is once the connection has been lost.

### 5. Settled while building it

- **Ten live sources per account.** Each can refresh every 15 minutes, so the limit bounds the outbound requests one account can cause.
- **"Refresh now" takes the worker's lease, and waits a minute.** A refresh asked for while the worker is fetching the same source is refused with 409, so one source is never fetched twice at once. One asked for within 60 seconds of the last fetch of that source is refused with 429 and a `Retry-After` (`AGENTIC_OS_CONNECTOR_COOLDOWN`; the end-to-end tests set it to 0).
- **No credentials in an address.** A query key that names a credential (`key`, `token`, `secret`, `password`, `signature`, `auth`, `session` and their variants) is refused, because a connector would store it in plain text and in every backup. Non-ASCII characters in the address are percent-encoded.
- **IPv4 inside IPv6 is checked as IPv4**, including the NAT64 prefix `64:ff9b::/96`; the local-use NAT64 prefix `64:ff9b:1::/48` is refused outright.
- **The time limit covers the whole read.** Each receive is waited for no longer than what remains of the 15 seconds, and a source that sends a byte at a time is still cut off. Any error while reading the file is recorded as a failed refresh and waits like one, so a bad file cannot make the worker fetch it in a loop.
- **At most five open event streams per owner in one process** (429 beyond); each polls the database once a second.
- **A connector is its owner's alone.** Another owner's connector is a 404, and the event stream carries only the caller's own runs and connectors, admins included.
- **At least once.** Within one connection the stream looks five seconds back on every poll, because a change stamped before a poll can be written after it. A page treats every event as "look again", never as a total.
- **The dashboard never swaps its figures.** Over a run made from a live source, it shows the badge and, once a newer snapshot's analysis has finished, offers it in a polite notice; the reader opens it.
- **Deleting a connector keeps its snapshots and runs**, as deleting nothing else would: they are records the approval gate may already have bound to.
- **Accepted after the security review:** the test seam stays in the server, closed unless `AGENTIC_OS_CONNECTOR_FIXTURES` names a folder, and it reads only plain file names inside that folder; and a refused redirect names its target, which the interface shows as text. Neither reaches anything the caller could not already see.

## Consequences

- A source refreshed every hour becomes a series of snapshots and runs, each still a fixed record the approval gate binds to.
- Nothing publishes itself: a scheduled run waits for a person at the gate.
- The server makes outbound requests, but only to public addresses, only over `https`, and only within the upload's limits.

## Not done here

- Database and API connectors with credentials. Storing secrets for sources needs its own decision about where they live and who can read them.
- Incremental loads: each refresh is a whole snapshot.
- Pushing to anything but an open page (email, chat).
