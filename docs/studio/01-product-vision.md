# Product vision

## The problem

Most working databases were never designed as a whole. They grew. A team
inherits one and finds:

- Tables named `tbl_cust_x2`, `orders_new_final`, `tmp_migr_2019` that are still read
  by something.
- Foreign keys that exist in the application code but not in the database, so
  nothing in the database says that `orders.cust` refers to `customers.id`.
- Columns whose meaning lives in one person's head: `status` is an integer from
  1 to 7, and nobody remembers what 4 means.
- Data quality problems that are discovered only when a report is wrong:
  duplicate customers, `NULL` emails, dates stored as strings in three formats.
- Schema changes made by hand on production, so staging and production have
  drifted apart.

Existing database IDEs are good at *showing* a schema and *running* SQL. They
do not help a person *understand* a database they did not build, and they do
not check whether a change is safe before running it.

## The product in one paragraph

The Studio connects to a database and builds a map: tables, real and inferred
relationships, what each column actually contains, and where the data is
dirty. A person can ask questions in plain English and get SQL they can read,
run, and check against an execution plan. When they need to change the schema,
the agent drafts the migration, tests it on a disposable copy, explains what it
would lock and what depends on it, and waits for approval. Everything the agent
learns (what `status = 4` means, which column is the real customer key) goes
into a shared glossary, so the next question is easier for everyone.

## Personas

| Persona | Situation | What they need most |
| --- | --- | --- |
| **Inheriting engineer** ("Priya") | Joined a team, owns a 400-table Postgres database with no docs. | A map, inferred relationships, and a glossary she can trust because each entry shows evidence. |
| **Analytics engineer** ("Marco") | Builds dbt models on top of a messy source system. | Profiling, hygiene findings, and a data dictionary he can export straight into dbt `sources.yml`. |
| **Backend developer** ("Sam") | Needs to add a column and an index without taking the site down. | A migration with a rollback, a lock-risk warning, and an impact list of views and queries that will break. |
| **Data-curious PM/analyst** ("Lee") | Can read SQL slowly, cannot write it confidently. | Plain-English questions with SQL shown alongside, safe read-only access, and results that explain themselves. |
| **QA / platform engineer** ("Ana") | Needs realistic test data without copying production PII. | Synthetic seed data that respects foreign keys and looks statistically like production. |

The primary persona for v1 is **Priya**, because her jobs (map, understand,
document) are read-only and therefore the safest to automate first. Sam's jobs
(change the schema) come second, once approval gates exist.

## Jobs to be done

Written as "When ..., I want to ..., so I can ...":

1. When I connect to an unfamiliar database, I want a map of its tables and how
   they relate, so I can find where things live in minutes instead of days.
2. When relationships are not declared, I want the tool to propose likely ones
   with evidence, so I can confirm them instead of guessing.
3. When I am about to trust a column, I want to know how often it is null,
   duplicated, malformed, or sensitive, so I do not build on bad data.
4. When I have a question about the data, I want to ask it in words and see the
   SQL, the plan, and the result, so I can trust the answer and reuse the query.
5. When I need to change the schema, I want a tested migration, a rollback, and
   a list of what it affects, so I can ship the change without an incident.
6. When I need test data, I want generated rows that respect constraints and
   look realistic, so tests catch real bugs without exposing customer data.
7. When I learn what something means, I want to record it once, so my
   teammates and the agent know it too.

## Differentiators

What should make this worth switching to, compared with a database IDE plus a
general chat assistant:

1. **Inferred relationships with evidence.** The Studio checks value overlap,
   name similarity, and type compatibility, then shows the numbers ("98.7% of
   `orders.cust` values exist in `customers.id`; 0 values outside the range").
   A chat assistant can only guess from names.
2. **Verify-before-write migrations.** Every migration is applied and rolled
   back on a shadow copy of the schema before a human sees an approve button.
   The approval screen shows what happened on the shadow, not just the SQL.
3. **The plan, not just the query.** Generated SQL comes with `EXPLAIN` output,
   rendered as a picture, plus a cost guard that refuses to run a sequential
   scan of a 2-billion-row table without asking.
4. **Schema memory.** A glossary of confirmed meanings, keys, and caveats that
   improves retrieval, SQL generation, and documentation over time. This is the
   compounding asset: every confirmed fact makes the next answer cheaper and
   better.
5. **Local-first.** It works with a local model and never sends rows anywhere by
   default. For many teams, that settles whether they can use it at all.

## Non-goals

Stating these early prevents scope creep:

- **Not a BI tool.** Results get simple charts for orientation; dashboards,
  scheduling, and sharing belong in Metabase, Superset, and similar tools.
- **Not an ETL/orchestration tool.** The Studio can export dbt sources and
  models, but it does not run pipelines.
- **Not a database administration console.** No user and role management, no
  backup scheduling, no replication setup.
- **Not autonomous on production.** The agent never writes to a production
  connection in v1 (decision D5). "Autonomous" means it does the investigation
  and drafting on its own, not that it ships changes on its own.
- **Not a data-masking product.** PII detection is used to protect the agent's
  context and generated seeds, not to certify compliance.
- **No NoSQL in v1.** MongoDB and similar stores have different schema
  semantics; they would need their own design.

## Success metrics

Product metrics (measured on real usage, once there is some):

| Metric | Definition | Initial target |
| --- | --- | --- |
| Time to first map | From connection saved to ERD rendered for a 100-table schema | < 60 s (metadata only) |
| Inferred-FK acceptance rate | Proposed relationships the user confirms ÷ proposed relationships the user reviews | > 70% |
| NL→SQL first-run success | Generated queries that run without error and that the user does not edit before using | > 60% on the eval set, tracked in use |
| Migration shadow-pass rate | Proposed migrations that apply and roll back cleanly on the shadow without regeneration | > 80% |
| Glossary growth | Confirmed glossary entries per active connection per week | Increasing; used as a health signal, not a goal to game |
| Unsafe-action incidents | Writes executed outside the approval flow | **Zero.** Any non-zero value is a P0 bug. |

Agent-quality metrics live in [09-evaluation](09-evaluation.md). They are
measured on fixture databases with known answers, which is the only way to
measure correctness rather than satisfaction.

Note that acceptance and success rates are biased by who reviews what. A user
who confirms everything quickly inflates acceptance. Pair them with the
evaluation suite instead of reading them alone.
