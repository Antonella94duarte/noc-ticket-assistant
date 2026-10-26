# Small local models vs the LLM

Every step of the agent uses an LLM, even triage, which is a classification. Could small
Hugging Face models, free and running on a CPU next to the API, take over some steps? Two
candidates were measured on 2026-10-25: zero-shot classification for **triage**, and sentence
embeddings for **runbook search**.

## How the models were chosen

`scripts/find_models.py` searches the Hugging Face Hub through its API by task and language
(Spanish or multilingual, since the tickets are in Spanish), sorted by downloads, and lists size
and license. From that list:

| Use | Model | Parameters | Why |
|---|---|---|---|
| Triage | `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` | 107M | The smallest multilingual NLI model |
| Triage | `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | 279M | The most downloaded zero-shot model for Spanish |
| Runbooks | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 118M | The most downloaded multilingual embedding model |
| Runbooks | `intfloat/multilingual-e5-small` | 118M | Second most downloaded; trained with query/passage prefixes |

All MIT or Apache 2.0. They run in their own image (`requirements-hf.txt`, PyTorch CPU build;
2.3 GB image) on the laptop's CPU through Docker.

## Triage: zero-shot classification

**Method.** `app/small_models/triage.py` uses the `zero-shot-classification` pipeline: an NLI
model scores how well the ticket supports "Este ticket trata sobre {label}" for each category and
"El impacto de este incidente es {label}" for each severity, and the best label wins. Labels are
short Spanish descriptions written once from the classification rubric and **not tuned on the
evaluation set**. The LLM is `classify_v3` with `gpt-6-luna`, the triage step of the agent. All
three run on the same 53 labeled tickets (`classification.jsonl` and `agent_cases.jsonl`).
Reproduce with `python scripts/evaluate_small_models.py --llm openai` in the image; raw results in
`data/eval/results/small-models-triage.jsonl`.

| System | Category | Severity | Latency/ticket mean (p90) | Cost/ticket |
|---|---|---|---|---|
| Always answer the most common label | 27/53 | 38/53 | - | - |
| MiniLMv2-L6 (zero-shot) | 16/53 | 14/53 | 0.07 s (0.10 s) | $0 |
| mDeBERTa-v3-base (zero-shot) | 30/53 | 20/53 | 4.2 s (5.8 s) | $0 |
| LLM `gpt-6-luna`, `classify_v3` | **53/53** | **46/53** | 4.8 s (6.9 s) | $0.0004 |

The first row is the floor any classifier should beat: answering `connectivity_loss` for every
ticket gets 27 categories right, and `major` for every ticket gets 38 severities right.

**Findings.**

- **Zero-shot doesn't work for this triage.** mDeBERTa beats the constant answer by three tickets
  on category and loses to it on severity; MiniLM is below the floor on both. mDeBERTa gets
  connectivity loss right (21/24), but it answers `connectivity_loss` for 31 of the 53 tickets and
  gets 2/8 of the "other" tickets (customers with no fault, cleared alarms).
- **The labels need knowledge the model doesn't have.** Telling a hardware failure from a lost
  link, or a major from a minor incident, depends on the NOC's rubric (a lost redundant power
  supply is major; an alarm that already cleared is not an outage). The LLM gets that rubric and
  five examples in its prompt; an NLI model only sees one sentence per label.
- **Severity is the hardest part**, as expected: it is a judgment about impact, not a topic.
  Both small models lean on `minor`, which is right for only 15 of the 53 tickets.
- **Small isn't automatically fast.** mDeBERTa runs one model pass per label (ten per ticket), so
  on this CPU it is as slow as the API call. MiniLM is 60x faster, but its answers are unusable.
- The LLM triage costs **$0.0004 per ticket**. Saving that is not worth losing the classification
  the rest of the agent builds on, so the hybrid system (small model for triage, LLM for the
  rest) planned for this phase was not built.

What could make a small model viable: fine-tuning on a few hundred labeled tickets (for example
with SetFit, which works with little data), which the project doesn't have yet. 53 tickets are
enough to evaluate, not to train and evaluate.

## Runbook search: Hugging Face embeddings

**Method.** `RUNBOOK_RETRIEVER=hf` embeds the runbook sections with a Hugging Face model in the
API process (LlamaIndex `HuggingFaceEmbedding`), next to the existing BM25, OpenAI and Ollama
retrievers. E5 models get their `query:`/`passage:` prefixes. Same 18 labeled queries as in
[ADR 0004](decisions/0004-runbook-retrieval.md) (`python scripts/evaluate_retrieval.py
hf:<model>`).

| Retriever | hit@1 all | English (12) | Spanish (6) | MRR | Where it runs |
|---|---|---|---|---|---|
| BM25 | 15/18 | 12/12 | 3/6 | 0.83 | in-process, no model |
| OpenAI `text-embedding-3-small` | 18/18 | 12/12 | 6/6 | 1.00 | API |
| Ollama `bge-m3` (568M) | 18/18 | 12/12 | 6/6 | 1.00 | separate server |
| HF `paraphrase-multilingual-MiniLM-L12-v2` (118M) | 18/18 | 12/12 | 6/6 | 1.00 | in-process, CPU |
| HF `multilingual-e5-small` (118M) | 18/18 | 12/12 | 6/6 | 1.00 | in-process, CPU |

**Findings.**

- **A 118M model matches OpenAI and `bge-m3`** on these queries, including the Spanish ones BM25
  misses, with no API, no Ollama server and nothing leaving the process.
- **It is fast once loaded**: embedding the 32 sections takes 0.1 s and a query about 11 ms.
- **Loading took 80-100 s here**, and nearly all of it was requests to the Hugging Face Hub at
  start-up over my connection, not computation: the model is cached, but offline mode
  (`HF_HUB_OFFLINE=1`) still failed to load it from the cache. A deployment should download the
  model into the image at build time and run offline.
- The two models tie; `paraphrase-multilingual-MiniLM-L12-v2` is the default
  (`HF_EMBEDDING_MODEL`) because it needs no prefixes and is the most used.

## Conclusion

Small models are a good fit where the task is **similarity** (matching a Spanish query to an
English runbook) and a poor fit where it is **judgment under a rubric** (category and severity
of an incident). The agent keeps the LLM for triage, investigation and report; runbook search can
run on a local 118M model when the agent must work without external APIs. See
[ADR 0006](decisions/0006-small-models.md).

## Reproduce

```bash
docker build --build-arg REQUIREMENTS=requirements-hf.txt -t noc-ticket-assistant-hf .
# The repository mounted as /code; a volume keeps the downloaded models between runs.
docker run --rm --env-file .env -v "$PWD:/code" -v noc-hf-cache:/root/.cache/huggingface \
  noc-ticket-assistant-hf python scripts/evaluate_small_models.py --llm openai
docker run --rm -v "$PWD:/code" -v noc-hf-cache:/root/.cache/huggingface \
  noc-ticket-assistant-hf python scripts/evaluate_retrieval.py bm25 \
  hf:sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 hf:intfloat/multilingual-e5-small
python scripts/find_models.py   # only needs huggingface_hub
```

On Windows, the PyTorch wheel installed in a local virtual environment failed to load
(`WinError 1114` on `c10.dll`), one more reason to run this in the Linux image.

## Limitations

The same as in [model-comparison.md](model-comparison.md) (synthetic tickets, one run per
configuration), plus: only zero-shot was tried for triage, with one set of label descriptions
written up front; other wordings would change the numbers somewhat, but tuning them on the
evaluation set would only measure how well the labels fit these 53 tickets. Latencies are from a
laptop CPU inside Docker.
