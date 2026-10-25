# Agent evaluation: baseline vs agent, across models

Does letting the model investigate the network (alarms, topology, circuits, runbooks) produce a
better diagnosis than the chained baseline that only reads the ticket? And how do OpenAI, DeepSeek
and a local model compare on quality, latency and cost? Measured on 2026-10-24.

## Method

**Cases.** `data/eval/agent_cases.jsonl` holds 30 synthetic tickets about the incidents in the
network snapshot (`data/network/seed.json`): customers who don't give their circuit, internal
alarms (failed uplink, bundle member, power supply, commercial power, optical loss), a misspelled
hostname, prompt injections in the ticket and in the logs, customers with no fault in the network,
an alarm that already cleared, and vague tickets. Each case is labeled with:

- the defensible categories and final severities;
- `evidence_any` (23 cases): strings such as `Gi0/0/3` or `VLAN 210`, of which one must appear in
  the **top probable cause**. Most can only be found by querying the network. A test checks that
  every label exists in the network data, so a typo can't silently fail every system;
- the runbooks that apply, and whether a customer reply should be drafted.

**Systems.** All three use the same triage prompt (`classify_v3`):

| System | What it does |
|---|---|
| baseline | classify, then diagnose (`diagnose_v2`) from the ticket text only; no tools |
| agent | classify, investigate with the four network tools (`investigate_v1`), report (`report_v3`) |
| agent-runbooks | same, plus `search_runbooks` (`investigate_v2`) |

The agent's report re-assesses the severity with the evidence; the baseline keeps the triage
severity. **Final severity** compares what each system ends with.

**Providers.** OpenAI `gpt-6-luna` (reasoning effort medium), DeepSeek `deepseek-flash` (thinking
on, effort low) and Ollama `qwen3:4b` on a laptop GPU (thinking off, 12k context). Fallbacks were
disabled so each provider is measured on its own. OpenAI and DeepSeek ran all 30 cases; Ollama ran
10 representative cases with two systems because each agent run takes about two minutes.

**Cost** is estimated from the token counts with the prices in `app/llm/pricing.py`, using the
uncached input price and DeepSeek's peak-hour price: an **upper bound**, see the limitations.

Reproduce with `python scripts/evaluate_agents.py --providers openai deepseek` (raw results,
including every diagnosis, are in `data/eval/results/`).

## Results

| Provider | System | Category | Final severity | Root cause | Runbook cited | Reply | Tools/ticket | Latency mean (p90) | Tokens/ticket | Cost/ticket (upper bound) |
|---|---|---|---|---|---|---|---|---|---|---|
| OpenAI | baseline | 29/30 | 23/30 | 1/23 | - | 29/30 | 0 | 17 s (21 s) | 5.9k | $0.0013 |
| OpenAI | agent | 30/30 | 26/30 | **21/23** | - | 27/30 | 4.3 | 46 s (54 s) | 15.4k | $0.0029 |
| OpenAI | agent-runbooks | 30/30 | **27/30** | 20/23 | 21/24 | 28/30 | 5.7 | 58 s (71 s) | 20.3k | $0.0036 |
| DeepSeek | baseline | 30/30 | 25/30 | 5/23 | - | 30/30 | 0 | 19 s (28 s) | 7.4k | $0.0047 |
| DeepSeek | agent | 30/30 | **27/30** | **20/23** | - | 29/30 | 5.9 | 40 s (50 s) | 25.8k | $0.0133 |
| DeepSeek | agent-runbooks | 29/30 | 25/30 | 19/23 | 20/24 | 28/30 | 7.2 | 45 s (55 s) | 32.0k | $0.0156 |
| Ollama (10 cases) | baseline | 9/10 | 2/10 | 1/8 | - | 7/10 | 0 | 14 s (17 s) | 4.5k | $0 |
| Ollama (10 cases) | agent-runbooks | 9/10 | 3/10 | 7/8 | 1/10 | 7/10 | 2.2 | 118 s (138 s) | 22.1k | $0 |

DeepSeek agent-runbooks had one failed run (a JSON answer cut off mid-string), counted as a
failure on every metric that applies.

## Findings

**1. Investigating is what finds the cause.** Without tools, the top cause names the evidence in
1 of 23 cases on OpenAI: the ticket doesn't contain it ("Distribuidora Del Sur has no internet"
says nothing about port `Gi0/0/3`). With tools it is 21/23 on OpenAI, 20/23 on DeepSeek and 7/8
even on the 4B local model. DeepSeek's baseline scores 5/23 mostly where the evidence was already
in the ticket or logs (the uplink name in an NMS alarm, `Gi0/0/3` in the injected logs).

**2. Re-assessing the severity after investigating works, with one bias.** On OpenAI the agent
with runbooks changed the triage severity in 16 cases and was right in 13: a "slow site" became
major once the agent saw the failed uplink pair (lost redundancy), a power alarm became major once
it saw ~3 h of battery left, and "cuts last night, fine now" went down to minor because the alarm
had cleared. The three misses share a pattern, finding 3.

**3. The agent's main failure mode: blaming the loudest alarm nearby.** When the customer's own
port is fine or the real cause is small, the agent tends to attribute the incident to whatever
major alarm it sees on the site:

- Transportes Lago's cause is CRC errors on its own port (`Gi1/0/12`); both OpenAI and DeepSeek
  blamed the site's congested uplink instead, which they found first.
- A clinic with one web page not loading, a vague "we have a problem" and a CPU alarm that already
  cleared were all raised to major; for the vague ticket the top cause was the commercial power
  alarm of a site the customer was never tied to.
- The local model does this far more often: for a customer with no alarm on its port it blamed a
  bundle member down on the same router, which doesn't carry that customer's traffic.

A prompt rule ("an alarm only explains the ticket if it affects the customer's access path") and
eval cases with a loud but unrelated alarm are the next steps.

**4. Runbooks change the procedure, not the accuracy.** With `search_runbooks`, 21 of 24
applicable OpenAI diagnoses cite the right runbook, and the steps follow the team's rules (escalate
a link down after 30 minutes, roll back a change if its owner can't be reached in 15). Root-cause
and severity accuracy stay about the same, at about +30% tokens and +12 s on OpenAI. Whether that is
worth it depends on how much the team values consistent, procedure-backed answers; on this
synthetic data the diagnosis is not more correct, only better grounded.

**5. Provider differences.**

- **OpenAI** is the most consistent: no failed runs, best final severity with runbooks, and the
  lowest token use (15-20k per agent run).
- **DeepSeek** matches OpenAI on root cause and is 13-22% faster, but makes more tool calls and
  uses 58-68% more tokens. Out of the box it was not usable: its default thinking effort used up the
  output budget before answering, and in JSON mode it sometimes added keys outside the schema.
  Before fixing both, 37 of 90 runs failed (`data/eval/results/agents-deepseek-before-fix.jsonl`);
  after (`DEEPSEEK_MAX_TOKENS=16000`, lenient key handling), 1 of 90.
- **Ollama `qwen3:4b`** finds the evidence when it has tools but gets the severity wrong in most
  cases (it overrates to critical), cites runbooks poorly, mixes languages, and takes about two
  minutes per analysis on a laptop. Usable for offline experiments, not for diagnosis.

**6. Cost.** Per ticket, the agent costs about 2-3x the baseline and takes about 3x as long. On
OpenAI that is $0.0036 instead of $0.0013 with runbooks: below half a cent per analysis. The
DeepSeek figures are an upper bound (uncached, peak hours); its usage page shows the real spend.

## Recommendation

- Use the **agent with runbooks on OpenAI** as the default: the best final severity, procedure-
  backed steps, no failures, at about a third of a cent per ticket.
- Keep **DeepSeek** as the fallback provider (`LLM_FALLBACK_PROVIDERS=deepseek`): comparable
  accuracy and lower latency, now that its two configuration problems are fixed.
- Keep the **baseline** for when latency matters more than the cause (first response in a few
  seconds), or when no tools are available.
- Use the **local model** only where data can't leave the machine, and expect worse severities.

## Limitations

- **Synthetic and small.** 30 tickets on one network snapshot, written by the same person who
  wrote the prompts; one run per configuration, so a single case moves a score by 3-4 points. The
  differences between the two agent variants and between OpenAI and DeepSeek on root cause (1 case)
  are within that noise; the gap between baseline and agent is not.
- **String-match scoring.** The root cause counts as found when the top cause contains one of the
  evidence strings. A cause that names the right interface with the wrong explanation passes, and
  a correct paraphrase without the identifier fails. An LLM judge or expert review would be more
  precise.
- **Costs are an upper bound.** Prompt caching applies across calls with the same system prompt,
  and DeepSeek is half price off-peak; the token counts don't record cache hits yet.
- **Ollama** ran only 10 cases and two systems.
