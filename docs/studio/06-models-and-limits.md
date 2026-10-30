# Models and limits

## Starting point

The app already lets the user choose an Ollama model and an effort level per
thread. The document agent experiments chose qwen3:4b as the default for tool
calling, because in the evaluated cases it chose tools correctly where Llama 3.1 8B
called tools for greetings. The repository also includes `langchain-openai` and an
`OPENAI_API_KEY` setting, so an OpenAI-compatible cloud path exists in the
dependencies, although the agent does not use it.

The Studio keeps **local-first** as the default and adds optional
bring-your-own-key (BYOK) cloud models (decision D3).

## Task-based model routing

Not every step needs the same model. A run uses up to three **roles**. Each role
maps to a model configured per workspace, with an override per connection.

| Role | Used for | Requirements | Local default | When to prefer cloud |
| --- | --- | --- | --- | --- |
| **Fast** | Planning short checklists, summarizing tool results, naming threads, classifying intent, choosing the mode | Low latency; reliable short JSON | A small instruct model (qwen3:4b with thinking off, or smaller) | Rarely needed |
| **Tool** | The agent loop: choosing tools, writing arguments, NL→SQL drafts | Native tool calling; follows schemas; good SQL | qwen3:4b (current default); larger local models when hardware allows | Large schemas, complex joins, many repair attempts |
| **Reasoning** | Migration design, reviewing shadow diffs, explaining plans, ambiguous FK judgment | Long context; careful multi-step reasoning | The largest local model the machine runs comfortably | Recommended for migrations on Dev/Prod, when the user opts in |

Rules:

- **Effort maps to roles and budgets**, not just to tokens. Low effort uses
  the Fast model for everything that does not need tools, and small budgets.
  High effort enables the Reasoning role, self-consistency for SQL, and larger
  budgets.
- **Model capability is checked, not assumed.** Before a model is assigned the
  Tool role, a short probe checks that it emits valid tool calls (Ollama
  advertises tool support per model; the probe confirms it). The document agent
  walkthrough found that `llama3` does not advertise tool support.
- **Every answer records which model and provider produced it**, shown in the
  thread and stored in the audit log.
- **Thinking output stays separate** from answers, as the current Qwen
  configuration does. A truncated or malformed answer remains a failure
  (`response_failure` in `services/document_agent_runtime.py`), not an answer.

### Local versus cloud

| | Local (Ollama) | BYOK cloud (OpenAI-compatible) |
| --- | --- | --- |
| Data leaves the machine | No | Yes: the prompt, schema excerpts, masked samples, statistics |
| Quality on complex SQL and migrations | Lower with small models; adequate for simple queries | Generally higher |
| Latency | Depends on hardware; the walkthrough observed 6–30 s for a simple inventory call with Qwen thinking | Usually faster per call, plus network time |
| Cost | Hardware and electricity | Per-token usage billed to the user's own key |
| Setup | Download models | Paste a key |

Cloud use is controlled per connection, not just globally, because the same
user may be happy to send their Sandbox fixture schema to a cloud model but not
their production one. When a cloud model is active for a connection:

- The agent panel shows "Cloud model · data leaves this machine".
- PII masking stays on and cannot be disabled.
- The audit log records each cloud call's size (tokens in and out) but not its
  content.
- The first use per connection asks for confirmation, listing what is sent:
  table and column names, glossary text, statistics, masked sample rows, and
  query results up to the per-result caps.

An **enterprise endpoint** option (an OpenAI-compatible URL pointing to a
company's own gateway) is a simple extension and matters for teams that are
allowed to use only an approved provider.

## Context budgeting for schemas

A small local model's context window is the binding constraint. The current
configuration uses `num_ctx=4096`, which is too small for schema work. The
Studio should raise it to what the chosen model and hardware support (8k–32k),
and still budget carefully.

Budget for a Tool-role call (example with a 16k context):

| Part | Budget | Notes |
| --- | --- | --- |
| System prompt + tool definitions | ~1.5k tokens | Mode-scoped tool sets keep this small. |
| Schema context | ~5k | Retrieved, not the whole schema. |
| Glossary entries | ~1k | Confirmed entries for the retrieved tables. |
| Conversation history | ~2k | Recent turns, older turns summarized by the Fast model. |
| Tool results in this run | ~4k | Each result capped at 8 KB; older results replaced by their summary line. |
| Generation | ~2.5k | Thinking plus answer, as today's 2,048 token cap plus a margin. |

### How the schema context is built

1. **Retrieve** with `search_schema`: embedding similarity over table documents
   plus exact name matches from the question. Take the top *k* tables (k ≈ 6).
2. **Expand** one hop along declared and confirmed FKs, because answers often
   need a join table that the question never mentions.
3. **Compress** each table into a compact form:
   ```text
   orders(id PK int, cust int→customers.id [inferred .99], status int {1:new,2:paid,4:refunded}, created_at timestamptz, total numeric) ~42M rows
   ```
   Only key columns, columns named in the question, and columns with glossary
   entries are included at first. The model can call `describe_tables` for more.
4. **Trim** to the budget by dropping expanded neighbors first, then columns
   without glossary entries.

This "retrieve, then let the model ask for more" pattern is cheaper and more
reliable than stuffing the schema into the prompt. It costs one or two extra
tool calls on hard questions.

## Per-run budgets

Per-run budgets protect the database and keep runs bounded (04). The effort
level selects a budget, and the tier caps it:

| Budget | Low | Medium | High | Cap on Prod |
| --- | --- | --- | --- | --- |
| Model calls | 6 | 12 | 24 | 24 |
| Tool calls | 8 | 20 | 40 | 40 |
| SQL repair attempts per draft | 1 | 2 | 3 | 3 |
| Self-consistency SQL variants | 1 | 1 | 3 | 3 |
| Wall-clock | 2 min | 5 min | 15 min | 5 min |
| Rows read (actual) | 1M | 10M | 50M | 1M |

These numbers are starting points to tune using the evaluation suite (09), not
measured optima.

## Plan quotas (hosted product only)

If the product is hosted (D1 options b or c), plans limit sustained use. Quotas
are counted per workspace, reset monthly, and are separate from per-run safety
budgets. The table lists **what is limited**, with placeholder values to tune
once real usage data exists. It deliberately contains no prices.

| | Free | Pro | Team |
| --- | --- | --- | --- |
| Connections | 2 (Sandbox/Dev only) | 10 | Unlimited |
| Prod-tier connections | 0 | 2 | Unlimited |
| Agent runs per month | 200 | 3,000 | Pooled, per seat |
| Hosted-model tokens | Small allowance | Larger allowance | Pooled |
| BYOK models | Yes (doesn't count toward token allowance) | Yes | Yes |
| Local models via a local runner | Yes | Yes | Yes |
| Profiling rows per month | 50M | 2B | Custom |
| Shadow verification minutes | 30 | 600 | Custom |
| Schema snapshots retained | 30 days | 1 year | Custom |
| Glossary sharing | Single user | Single user | Shared, with reviewer roles |
| Approvals | Single approver | Single approver | Two-person rule option for Prod |
| Audit log export | No | Yes | Yes, plus external log sinks |

Quota design notes:

- **Count what costs us money.** In a hosted product, our costs are hosted
  model tokens, shadow compute, and storage. BYOK and local-model usage cost us
  nearly nothing, so they should not consume runs from the same pool.
- **Never cut a run off mid-write.** Quotas are checked when a run starts and
  between steps, never between "approved" and "applied".
- **Show remaining quota before starting expensive runs** ("Profiling all
  tables will use ≈40M of your 50M rows this month").
- **Rate limits per workspace** (for example, 3 concurrent runs) protect a hosted
  service; they are separate from monthly quotas.

For the local-first build (the v1 recommendation), there are no quotas, only
per-run budgets.

## Prompts and structured output

- **One system prompt per mode**, assembled from shared blocks: the identity,
  data-is-untrusted rules, citation rules ("cite evidence IDs; never invent
  table or column names"), and mode-specific instructions.
- **Structured outputs** use tool arguments with strict schemas, as in the
  document tools. Free-form JSON in text is never parsed as an action.
- **Few-shot examples** are short and drawn from the fixture databases, never
  from the user's data.
- **Prompt versions** are tracked as constants with a version string, recorded
  in each run, so evaluation results can be compared across prompt changes.

## What we do not do

- No fine-tuning in v1. Retrieval plus the glossary is the adaptation mechanism.
  Fine-tuning a local model on one customer's schema is a later idea, and it
  carries data-handling questions of its own.
- No automatic fallback from local to cloud. If the local model fails, the UI
  offers a switch, and the user decides.
