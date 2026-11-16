# Your data in Sahifa

A short note for people who scan their own data with a self-hosted Sahifa: what it reads, what
it keeps, what it deletes, and what leaves the machine.

## What it reads

- **Databases:** Sahifa opens read-only sessions with a time limit and runs `SELECT`s. It never
  writes to a source. The connection's *Test* says whether the login could write, and what to
  revoke (`read-only-login.md`).
- **Files you upload** (CSV, TSV, Parquet, JSON lines) and **folders** the operator mounted
  read-only.
- Each scan reads the tables it finds, up to the number of rows per table you choose.

## What it keeps

In its own database, on the machine it runs on:

- the names of tables and columns, their types, and measures per column (counts, shares of
  empty and distinct values, ranges, frequent values);
- the checks and their findings: a summary, counts, the SQL that found it, and **a few example
  values** per finding;
- scores, the history of findings, schedules, workspaces and members, and the audit log of
  changes people made.

Example values of columns Sahifa recognises as personal (names, email addresses, phone
numbers, IBANs and the like) are stored and shown **masked**. Recognition works by rule and can
miss a column: treat reports as you treat the data they describe, and give people the
workspaces they need, not all of them.

Sahifa does not keep a copy of your tables.

## What it deletes, and when

- **Uploaded files** are deleted `SAHIFA_UPLOAD_TTL_DAYS` (7 unless the operator changed it)
  after their scan finished. The report stays. The demo data is an upload like any other.
- **Deleting a workspace** (organisation admin) removes its uploads, connections, scans,
  findings, members, invitations and audit entries.
- Logins to your sources are not in the database: they are settings of the install
  (`SAHIFA_CONN_*` in `.env`), and never appear in pages, reports or logs.

## What leaves the machine

Nothing, unless you send it:

- no telemetry, no usage statistics, no error reports to the project or anyone else;
- the web app loads no fonts, scripts or images from other servers;
- with sign-in through Keycloak, your browser talks to your Keycloak;
- backups go where the operator puts them (`backup-and-restore.md`).

The *Feedback* link in the footer opens the project's issue tracker on GitHub in a new tab.
What you write there is public: leave out data, host names and passwords. An error's
*Reference* is safe to share; it is a random id.

## The operator's log

The API's log has one line per error with the reference shown on the page, the path of the
request and the error's text. Paths hold ids, not data; an error's text can quote a value in
rare cases (a database refusing a row, for example). Read a log line before you paste it into
a public issue.
