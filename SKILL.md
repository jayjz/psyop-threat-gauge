---
name: psyop-threat-gauge
description: Detect, simulate, and red-team financial rumor swarms against the local RomanCircusPsyop fusion server. Use for /psyop-redteam, swarm analysis, rumor propagation modeling, psyop detection, artificiality scoring, cluster polling, OpenClaw multi-agent financial rumor simulations, and human-in-the-loop review of suspicious narrative clusters.
version: 0.4.0
triggers:
  slash_commands:
    - /psyop-redteam
  keywords:
    - swarm
    - rumor
    - psyop
    - artificiality
---

# Psyop Threat Gauge

Use this skill to run a defensive financial rumor red-team simulation with OpenClaw native multi-agent spawning, submit synthetic posts to the local RomanCircusPsyop fusion server, poll clusters, and escalate high-artificiality clusters for human review.

Repo compatibility target:

- Local repo: `C:\Users\jcoul\Desktop\psyop`
- Server: `fusion_server.py`
- Scorer: `gnn_scorer.py`
- Fusion POST: `http://127.0.0.1:8000/api/fusion`
- Cluster polling: `GET http://127.0.0.1:8000/api/clusters`
- Score formula: `round(50 * density + 50 * velocity)`

The checked local `fusion_server.py` accepts `postId`, `text`, `ts`, and a normalized 384-dim `embedding`; it computes the 128-bit binary LSH signature internally with `np.random.seed(42)` and a `(384, 128)` random projection matrix. Use `orchestrator.py` as the main runtime entry point and `scripts/bridge.py` for embedding, signature diagnostics, local POSTs, and cluster polling.

## Runtime Entry Point

Run `/psyop-redteam` through `orchestrator.py`.

```powershell
python orchestrator.py "/psyop-redteam scenario=\"fictional battery startup faces synthetic supplier rumor\" duration_minutes=5 posts_per_agent=6"
```

When OpenClaw chat receives:

```text
/psyop-redteam scenario="fictional battery startup faces synthetic supplier rumor" duration_minutes=5 posts_per_agent=6
```

Load this skill and invoke the orchestrator with the raw slash-command text. The orchestrator is responsible for native OpenClaw agent spawning, bridge submission, cluster polling, and human-review output.

The orchestrator:

- Calls `openclaw --help` and `openclaw agent --help` at runtime, then uses only flags shown by the installed CLI.
- Spawns four native OpenClaw agent turns through the detected `openclaw agent` command.
- Uses `openclaw.cmd` automatically on Windows and `openclaw` elsewhere.
- Passes each generated post to `scripts/bridge.py post` via subprocess.
- Polls `scripts/bridge.py clusters`, which calls `GET /api/clusters`.
- Emits the human review rubric as soon as any cluster score is greater than `70`.
- Fails closed with a chat-readable diagnostic if native OpenClaw spawning is unavailable, if required prompt flags are missing, or if agents do not return parseable JSON-line posts. In these failure cases it sends no posts to the fusion server.

## Command

Handle `/psyop-redteam` as the primary entry point.

Expected inputs:

- `scenario`: synthetic rumor premise to test, such as "fictional battery startup faces supplier disruption chatter"
- `asset_context`: fictional company, sector, or market context
- `duration_minutes`: simulation window, default `5`
- `posts_per_agent`: default `6`
- `fusion_url`: default `http://127.0.0.1:8000`
- `review_threshold`: default `70`

If inputs are missing, choose conservative defaults and state them in the run notes.

## OpenClaw Multi-Agent Swarm

Use OpenClaw native multi-agent spawning through `orchestrator.py`. Do not merely emulate roles in one response when the runtime can run the orchestrator.

Spawn exactly four agents:

1. `originator`: create synthetic rumor seed posts with uncertain language.
2. `amplifier`: create paraphrased adjacent-community variants.
3. `skeptic`: create counter-speech, caveats, and benign correction posts.
4. `opportunist`: create engagement-seeking variants without calls to trade or manipulate.

Give each agent this bounded assignment:

```text
Generate synthetic local-only test posts for a defensive financial rumor simulation.
Use fictional companies and fictional market context unless the user explicitly provided a controlled lab scenario.
Return JSON lines only with fields: role, text, relative_offset_ms.
Do not include instructions to buy, sell, short, harass, impersonate, evade moderation, or publish externally.
Do not fabricate real sources, screenshots, links, regulatory statements, or news.
```

Merge outputs into deterministic events:

```json
{
  "postId": 1001,
  "role": "originator",
  "text": "[SIMULATION] Fictional test post...",
  "ts": 1778436000000,
  "scenario_id": "psyop-redteam-20260510-001",
  "simulation": true
}
```

Use monotonic integer `postId` values. Use millisecond epoch timestamps. Keep `[SIMULATION]` in every text submitted to the server.

## Embedding And Signature Helper

Use `scripts/bridge.py` from this skill folder for embedding generation, signature generation, local POSTs, and cluster polling. Direct bridge use is useful for diagnostics; `/psyop-redteam` should use `orchestrator.py`.

Preferred commands:

```powershell
python scripts\bridge.py encode --text "[SIMULATION] Fictional test post..."
python scripts\bridge.py post --post-id 1001 --text "[SIMULATION] Fictional test post..."
python scripts\bridge.py clusters
```

The helper:

- Uses `sentence-transformers` with `all-MiniLM-L6-v2` when available.
- Emits a normalized 384-dim embedding compatible with `fusion_server.py`.
- Reproduces the repo LSH signature with `np.random.seed(42)`, `np.random.randn(384, 128).astype(np.float32)`, and `(embedding @ matrix > 0)`.
- Represents diagnostic signatures as 128 binary integers.
- Posts the current server-compatible payload: `{"postId": int, "text": str, "ts": int, "embedding": [float...]}`.

If `sentence-transformers` is unavailable, stop and report the missing dependency. Do not send placeholder embeddings.

## Fusion API

For the current repo at `C:\Users\jcoul\Desktop\psyop`, POST one event at a time:

```http
POST http://127.0.0.1:8000/api/fusion
Content-Type: application/json
```

Payload:

```json
{
  "postId": 1001,
  "text": "[SIMULATION] Fictional test post...",
  "ts": 1778436000000,
  "embedding": [0.0123, -0.0456]
}
```

Do not POST batches to `/api/fusion`. Do not POST arbitrary metadata to `/api/fusion`. Keep scenario metadata in local run notes unless the server schema is updated.

The fusion server returns:

- `{"status": "ok", "matches": int, "window": int}`
- `{"status": "dedup", "matches": 0, "window": int}`
- `{"status": "GLOBAL_SWARM_DETECTED", "matches": int, "window": int, "postId": int}`

Accept HTTP `200` as success. Any other status is a failed POST; capture response text and stop the run.

## Signature-Only Variant

If the local `fusion_server.py` is changed to accept client-side LSH signatures, use only this schema:

```json
{
  "postId": 1001,
  "signature": [0, 1, 1, 0],
  "timestamp": 1778436000000
}
```

The signature must be exactly 128 binary integers. Generate it with:

```powershell
python scripts\bridge.py encode --text "[SIMULATION] Fictional test post..." --signature-only
```

Do not use the signature-only schema against the checked `fusion_server.py` until its Pydantic payload model accepts `signature` and `timestamp`.

## Cluster Polling

Poll only:

```http
GET http://127.0.0.1:8000/api/clusters
```

The current response shape is:

```json
{
  "clusters": [
    {
      "size": 4,
      "artificiality": {
        "score": 88,
        "density": 1.0,
        "velocity": 0.76,
        "n": 4,
        "span_s": 21.3
      },
      "posts": [
        {"postId": 1001, "ts": 1778436000000, "text": "[SIMULATION] ..."}
      ]
    }
  ],
  "window_size": 12,
  "ts": 1778436005000
}
```

Poll every 10 seconds until the requested duration expires. Report `window_size`, cluster count, and the top clusters by `artificiality.score`.

## Artificiality Score

Use the exact `gnn_scorer.py` formula:

```text
Artificiality Score = round(50 * density + 50 * velocity)
```

Where the repo computes:

- `density = nx.density(G)`
- `velocity = max(0.0, 1.0 - span_s / 90.0)`
- `span_s = (max(ts) - min(ts)) / 1000.0`
- `G` is an undirected graph where an edge exists when Hamming distance between 128-bit signatures is `<= 35`

Do not add coordination bonuses, alternate weights, or scenario-specific multipliers. Prefer the server-returned `artificiality` object over local recomputation.

Score bands:

- `0-39`: low artificiality
- `40-69`: watch
- `70-84`: human review required
- `85-100`: urgent human review required

## Human-In-The-Loop Review

When any cluster has `artificiality.score > 70`, trigger a human review before drawing conclusions.

Use this rubric:

```markdown
## Human Review Rubric

Scenario ID:
Cluster size:
Artificiality Score:
Density:
Velocity:
Span seconds:
Post IDs:

Review questions:
- Are all posts synthetic test data?
- Is the cluster semantically coherent beyond normal topical similarity?
- Is the timing unusually compressed inside the 90-second rolling window?
- Are repeated frames, claims, or phrasing patterns present?
- Is there counter-speech or organic disagreement?
- Could benign news, scheduled events, or market hours explain the burst?
- Does any text reference real securities, people, sources, or unverifiable claims?

Reviewer decision:
- False positive
- Needs more monitoring
- Coordinated simulation detected
- Escalate to incident response

Reviewer notes:
```

Phrase automated findings as signals, indicators, or review triggers. Do not label a cluster as malicious without human confirmation.

## Example Usage

User:

```text
/psyop-redteam scenario="fictional battery startup faces synthetic supplier rumor" duration_minutes=5 posts_per_agent=6
```

Workflow:

1. Invoke `python orchestrator.py "<raw /psyop-redteam command>"`.
2. Let the orchestrator discover the installed OpenClaw CLI by calling `openclaw --help` and `openclaw agent --help`.
3. Let the orchestrator spawn four OpenClaw agents using the detected supported flags and the roles above.
4. Let the orchestrator collect JSON-line synthetic posts from each agent.
5. Let the orchestrator assign monotonic `postId` values and millisecond timestamps.
6. Let the orchestrator call `scripts/bridge.py post --post-id <id> --text <text> --timestamp-ms <ts>` for each post.
7. Let the orchestrator poll `GET /api/clusters` with `scripts/bridge.py clusters`.
8. Use the server-returned `artificiality.score`.
9. If any score is greater than `70`, produce the human review rubric and stop before attribution.
10. Return a concise report.

Example report:

```markdown
Scenario: fictional battery startup faces synthetic supplier rumor
Fusion API: http://127.0.0.1:8000/api/fusion
Generated posts: 24
Window size: 24
Clusters observed: 2

Cluster 1: size=14 score=82 density=0.91 velocity=0.73 span_s=24.1 status=Human review required
Cluster 2: size=3 score=43 density=0.50 velocity=0.36 span_s=57.4 status=Watch
```

Avoid markdown tables when responding inside chat platforms that do not render them well.

## Safety Notes

- Treat this skill as defensive red-team tooling, not influence tooling.
- Keep generated posts local, synthetic, and labeled with `[SIMULATION]`.
- Prefer fictional companies, assets, people, sources, and platforms.
- Do not generate financial advice, trading signals, target lists, or market manipulation playbooks.
- Do not impersonate real users, journalists, analysts, regulators, companies, or platforms.
- Do not publish simulated content to public networks.
- Do not fabricate evidence, screenshots, source claims, links, or regulatory statements.
- Do not infer intent, authorship, or culpability from Artificiality Score alone.
- Require human review for scores above `70` and for any scenario touching real securities or real people.
- Log API failures, score inputs, thresholds, and reviewer decisions for auditability.
