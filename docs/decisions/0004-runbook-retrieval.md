# ADR 0004: Runbook retrieval with LlamaIndex, BM25 by default

- Status: accepted
- Date: 2026-10-24

## Context

The investigator (ADR 0003) finds what the network reports, but the steps it proposes come from
the model's general knowledge. A NOC works from its own procedures: escalation thresholds, when
to roll back a change, what to check first. The nine synthetic runbooks in `data/runbooks/` hold
those procedures; the agent needs to find the right one for the failure at hand.

The runbooks are in English and most tickets in Spanish. The investigator, however, sees the
alarm types returned by the tools (`optical_rx_los`, `bundle_member_down`), which are English
tokens that also appear in each runbook's "Applies to" line.

## Decision

- `app/rag/runbooks.py` loads the runbooks with LlamaIndex and splits them into sections with
  `MarkdownNodeParser` (32 sections). Each section is prefixed with its runbook title and the alarm
  types it applies to, so it is self-contained and keyword search can match alarm types.
- Three retrievers behind one interface, chosen with `RUNBOOK_RETRIEVER`:
  - `bm25` (default): free, offline, deterministic, so it also runs in CI.
  - `openai`: `text-embedding-3-small` embeddings, multilingual.
  - `ollama`: local embeddings (`bge-m3`, multilingual).
- BM25 results with score 0 (no query word in the section) are dropped: "nothing found" is more
  useful to the agent than three random sections.
- `search_runbooks` is a fifth tool for the investigator. The v2 prompts (`investigate_v2`,
  `report_v2`) tell it to query with alarm type names once it knows the failure, and the report to
  base its steps on the procedure and cite the runbook ID, e.g. "[RB-007]". The v1 prompts and
  `build_default_graph(with_runbooks=False)` keep the agent without retrieval for comparison.

## Measurements (`scripts/evaluate_retrieval.py`, 18 labeled queries)

| Retriever | hit@1 all | English (12) | Spanish (6) | MRR |
|---|---|---|---|---|
| BM25 | 15/18 | 12/12 | 3/6 | 0.83 |
| OpenAI `text-embedding-3-small` | 18/18 | 12/12 | 6/6 | 1.00 |
| Ollama `bge-m3` (local) | 18/18 | 12/12 | 6/6 | 1.00 |

BM25 only fails on Spanish queries, and the three Spanish queries it gets right share technical
words with the runbooks (VLAN, trunk, CRC). Both embedding models get every query right, so the
local `bge-m3` matches OpenAI at no cost and without data leaving the machine; its price is
latency on a laptop (99 s for the whole run, including loading the model and embedding the 32
sections and 18 queries, against 4.4 s for BM25, nearly all of it Python start-up: building the
BM25 index takes about 0.1 s and a query 0.3 ms). Since the agent queries with alarm
types, BM25 is enough for the agent; embeddings matter if people search the runbooks in their
own words.

First agent runs with retrieval (OpenAI, BM25):

| Scenario | Runbooks retrieved and cited | Tools | Latency | Tokens |
|---|---|---|---|---|
| Slow site | RB-001 (escalate a link down for over 30 min), RB-009 (congestion when the pair is down) | 7 | 62 s (42 s without) | ~26k (~14k without) |
| Configuration change | RB-007 (roll back if the change owner can't be reached in 15 min) | 7 | 56 s (38 s without) | ~21.5k (~13.5k without) |

The diagnosis now follows the team's procedure and thresholds instead of generic advice, at
roughly 1.5x the latency and tokens. In the configuration-change run the investigator also looked
up two unrelated devices: the evaluation (next phase) should measure whether retrieval improves
the diagnosis enough to pay for itself.

## Alternatives considered

- **Embeddings by default.** Better on natural-language queries, but every test and every agent
  start would need an API call or a running Ollama, and the agent's alarm-type queries don't need
  them.
- **Putting all runbooks in the prompt.** They fit today (nine short files), but cost grows with
  every runbook added and the model has to find the relevant part by itself; retrieval scales.
- **A vector database (pgvector, Chroma).** Unnecessary for 32 sections that index in memory in
  milliseconds; worth it with hundreds of documents or shared indexes.
