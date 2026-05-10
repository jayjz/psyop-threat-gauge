# Psyop Threat Gauge

**OpenClaw-native multi-agent red-teaming tool for detecting coordinated inauthentic behavior (financial rumor swarms).**

A production-grade defensive orchestration skill that spawns realistic rumor-propagation agent swarms, feeds them into your local Psyop fusion/scoring engine, computes the exact Artificiality Score (`round(50 * density + 50 * velocity)`), and triggers human-in-the-loop review when coordination thresholds are breached.

Built as a clean, drop-in OpenClaw skill with runtime CLI discovery, robust fallback generation, and zero external dependencies beyond your existing Psyop server.

---

## Features

- **Native OpenClaw multi-agent orchestration** — Spawns four specialized agents (Originator, Amplifier, Skeptic, Opportunist) using real OpenClaw sessions.
- **Real-time Psyop integration** — Posts go directly to your `fusion_server.py` via the included `bridge.py` helper (full embedding + LSH support).
- **Exact Artificiality Scoring** — Uses your original `gnn_scorer.py` formula (NetworkX density + velocity in 90s window).
- **Human-in-the-Loop Rubric** — Automatic high-score review template with clear decision framework.
- **Robust & Defensive** — Dynamic CLI discovery, graceful degradation, pure-Python fallback swarm generation, no fusion pollution on failure.
- **Local-first** — Runs entirely on your hardware with Ollama/local models.

Perfect demonstration of **AI orchestration + red-team/blue-team + inference physics** in 2026.

---

## Architecture
OpenClaw Chat (/psyop-redteam)
↓
orchestrator.py (main entrypoint)
↓
├── Dynamic CLI discovery (openclaw agent --help parsing)
├── Spawn 4 role agents (native sessions)
├── Role-specific strict JSON prompts + fallback generator
├── Bridge.py → POST to fusion_server.py (/api/fusion)
├── Poll /api/clusters
└── GNN Scorer → Artificiality Score + Human Rubric (if >70)
text---

## Installation

1. Clone the repo into your OpenClaw skills workspace:
   ```powershell
   cd ~/.openclaw/workspace/skills
   git clone https://github.com/jayjz/psyop-threat-gauge.git psyop-threat-gauge

Make sure your Psyop fusion server is running:PowerShellcd ~/Desktop/psyop
.\venv\Scripts\activate
python fusion_server.py
(Optional but recommended) Start Ollama with a capable model:PowerShellollama run qwen2.5-coder:7b   # or any strong local model


## Usage
From OpenClaw Chat (recommended)
text/psyop-redteam scenario="fictional semiconductor supply chain rumor" duration_minutes=5 posts_per_agent=6
From CLI (for testing)
PowerShellcd ~/.openclaw/workspace/skills/psyop-threat-gauge
python orchestrator.py "/psyop-redteam scenario='fictional semiconductor supply chain rumor' duration_minutes=5 posts_per_agent=6"
Diagnostic commands
PowerShellpython scripts/bridge.py post --post-id 1001 --text "[SIMULATION] Test post"
python scripts/bridge.py clusters

## Example Output
When a coordinated swarm is detected you will see:

Generated posts submitted to fusion server
Live cluster polling
Artificiality Score calculation
Full human review rubric if score > 70

The skill always produces output — even if OpenClaw agents fail, it falls back to synthetic posts so demos never die.

## Safety & Ethics
This tool is built exclusively for defensive red-teaming and research.

All generated content is explicitly marked [SIMULATION]
Hardcoded fictional entities only
No real securities, people, or platforms are targeted
Human review required for any high-score cluster
Never publish or amplify generated content

See SKILL.md for full safety contract.

## Portfolio Context
This project demonstrates production-grade AI orchestration:

Multi-agent coordination with real tool (OpenClaw)
Local inference + custom scoring pipeline (your Psyop repo)
Evaluation & guardrails (Handshake-style rubrics)
Resilience (dynamic discovery, fallbacks, graceful degradation)

Built as part of a deliberate deep dive into agent orchestration, red-teaming, and local inference physics.

## Repository Structure
textpsyop-threat-gauge/
├── SKILL.md                    # OpenClaw skill definition
├── orchestrator.py             # Main runtime + spawning logic
├── scripts/
│   └── bridge.py               # Embedding, POST, polling helper
├── FALLBACK_TEMPLATES          # Synthetic data when agents fail
└── README.md

Contributing
Pull requests welcome for:

Additional role templates
Better model prompting strategies
Support for other local inference backends
Observability / tracing additions


License: MIT

Built with ❤️ for understanding how coordinated inauthentic behavior actually works in 2026 — so we can defend against it.
