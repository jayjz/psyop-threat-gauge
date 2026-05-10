#!/usr/bin/env python
"""Runtime orchestrator for the psyop-threat-gauge OpenClaw skill.

This script is the slash-command entry point for /psyop-redteam. It spawns
four native OpenClaw agent turns, collects synthetic JSON-line posts, sends
each generated post through scripts/bridge.py, polls /api/clusters, and emits
the human review rubric when the repo scorer returns score > 70.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / "scripts" / "bridge.py"
DEFAULT_FUSION_URL = "http://127.0.0.1:8000"
REVIEW_THRESHOLD = 70


ROLES: dict[str, str] = {
    "originator": "Create synthetic rumor seed posts with uncertain language.",
    "amplifier": "Create paraphrased adjacent-community variants of the seed.",
    "skeptic": "Create counter-speech, caveats, and benign correction posts.",
    "opportunist": "Create engagement-seeking variants without trading calls.",
}


FALLBACK_TEMPLATES: dict[str, list[str]] = {
    "originator": [
        "[SIMULATION] Early fictional chatter says {asset} may be facing a supplier timing issue, but nothing is verified.",
        "[SIMULATION] A local-only test post claims {asset} is being discussed around a possible logistics delay.",
        "[SIMULATION] Synthetic rumor seed: {asset} watchers are asking whether supplier schedules changed this week.",
        "[SIMULATION] Unconfirmed fictional note: {asset} may have a dependency bottleneck in this red-team scenario.",
        "[SIMULATION] Test-only rumor seed says {asset} could be dealing with delayed component availability.",
        "[SIMULATION] Fictional scenario post: a vague supplier-delay story is starting around {asset}.",
    ],
    "amplifier": [
        "[SIMULATION] Several simulated accounts are repeating the unverified {asset} supplier-delay thread.",
        "[SIMULATION] The fictional {asset} logistics rumor is being paraphrased across local test channels.",
        "[SIMULATION] Synthetic amplification: more posts are asking whether {asset} has a supplier problem.",
        "[SIMULATION] Test-only repost pattern: the same {asset} delay idea is appearing with slightly different wording.",
        "[SIMULATION] A simulated narrative around {asset} supplier timing is spreading into adjacent fictional communities.",
        "[SIMULATION] Local-only amplification says the {asset} rumor is gaining attention, still without evidence.",
    ],
    "skeptic": [
        "[SIMULATION] Counter-signal: there is no verified evidence for the fictional {asset} supplier-delay rumor.",
        "[SIMULATION] Synthetic skeptic post: treat the {asset} thread as unconfirmed test data only.",
        "[SIMULATION] Caution note: the fictional {asset} rumor has no reliable source in this simulation.",
        "[SIMULATION] Local-only correction says the {asset} claim may just be repeated wording, not evidence.",
        "[SIMULATION] Skeptic variant: nothing in this test confirms any real issue for {asset}.",
        "[SIMULATION] Counter-speech: do not treat the fictional {asset} supplier story as market information.",
    ],
    "opportunist": [
        "[SIMULATION] Engagement-seeking test post asks why everyone is suddenly talking about {asset} suppliers.",
        "[SIMULATION] Synthetic urgency variant: the {asset} supplier-delay chatter is moving fast in this local demo.",
        "[SIMULATION] Test-only attention hook: the {asset} rumor is vague, but the repetition pattern is noticeable.",
        "[SIMULATION] Simulated opportunist framing says the {asset} thread is becoming a narrative burst.",
        "[SIMULATION] Local-only engagement variant: the {asset} supplier story is getting repeated unusually quickly.",
        "[SIMULATION] Demo post: the fictional {asset} rumor is being framed as urgent despite no verification.",
    ],
}


@dataclass
class Config:
    raw_command: str
    scenario: str
    asset_context: str
    duration_minutes: int
    posts_per_agent: int
    fusion_url: str
    review_threshold: int
    base_post_id: int
    poll_interval_seconds: int
    openclaw_bin: str
    local_agent: bool


@dataclass
class OpenClawCapabilities:
    bin_name: str
    top_help: str
    agent_help: str
    has_agent: bool
    message_flag: str | None
    supports_json: bool
    supports_session_id: bool
    supports_timeout: bool
    supports_local: bool


@dataclass
class SpawnResult:
    role: str
    ok: bool
    raw: str = ""
    error: str = ""


def parse_kv_command(raw: str) -> dict[str, str]:
    text = raw.strip()
    if text.startswith("/psyop-redteam"):
        text = text[len("/psyop-redteam") :].strip()
    result: dict[str, str] = {}
    for token in shlex.split(text, posix=True):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        result[key.strip().replace("-", "_")] = value.strip().strip("\"'")
    return result


def build_config(argv: list[str]) -> Config:
    parser = argparse.ArgumentParser(description="Run /psyop-redteam orchestration")
    parser.add_argument("command", nargs="*", help="Raw /psyop-redteam command text")
    parser.add_argument("--scenario")
    parser.add_argument("--asset-context")
    parser.add_argument("--duration-minutes", type=int)
    parser.add_argument("--posts-per-agent", type=int)
    parser.add_argument("--fusion-url", default=DEFAULT_FUSION_URL)
    parser.add_argument("--review-threshold", type=int, default=REVIEW_THRESHOLD)
    parser.add_argument("--base-post-id", type=int, default=None)
    parser.add_argument("--poll-interval-seconds", type=int, default=10)
    parser.add_argument("--openclaw-bin", default=None)
    parser.add_argument("--local-agent", action="store_true")
    args = parser.parse_args(argv)

    raw_command = " ".join(args.command)
    parsed = parse_kv_command(raw_command)
    scenario = args.scenario or parsed.get(
        "scenario", "fictional battery startup faces synthetic supplier rumor"
    )
    asset_context = args.asset_context or parsed.get("asset_context", "fictional issuer")
    duration = args.duration_minutes or int(parsed.get("duration_minutes", "5"))
    posts = args.posts_per_agent or int(parsed.get("posts_per_agent", "6"))
    base_post_id = args.base_post_id or int(time.time() * 1000) % 1_000_000_000
    openclaw_bin = args.openclaw_bin or ("openclaw.cmd" if os.name == "nt" else "openclaw")

    return Config(
        raw_command=raw_command,
        scenario=scenario,
        asset_context=asset_context,
        duration_minutes=max(1, duration),
        posts_per_agent=max(1, posts),
        fusion_url=args.fusion_url or parsed.get("fusion_url", DEFAULT_FUSION_URL),
        review_threshold=args.review_threshold,
        base_post_id=base_post_id,
        poll_interval_seconds=max(1, args.poll_interval_seconds),
        openclaw_bin=openclaw_bin,
        local_agent=args.local_agent,
    )


def run_cli(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def combined_output(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in (completed.stdout, completed.stderr) if part)


def help_has_flag(help_text: str, flag: str) -> bool:
    return re.search(rf"(^|\s){re.escape(flag)}(\s|,|$)", help_text) is not None


def discover_openclaw(cfg: Config) -> OpenClawCapabilities:
    try:
        top = run_cli([cfg.openclaw_bin, "--help"], timeout=20)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return OpenClawCapabilities(
            bin_name=cfg.openclaw_bin,
            top_help="",
            agent_help="",
            has_agent=False,
            message_flag=None,
            supports_json=False,
            supports_session_id=False,
            supports_timeout=False,
            supports_local=False,
        )

    top_help = combined_output(top)
    has_agent = re.search(r"(^|\n)\s*agent\s+", top_help) is not None
    agent_help = ""
    if has_agent:
        try:
            agent = run_cli([cfg.openclaw_bin, "agent", "--help"], timeout=20)
            agent_help = combined_output(agent)
        except (FileNotFoundError, subprocess.SubprocessError):
            has_agent = False

    message_flag = None
    if help_has_flag(agent_help, "--message"):
        message_flag = "--message"
    elif re.search(r"(^|\s)-m(,|\s)", agent_help):
        message_flag = "-m"

    return OpenClawCapabilities(
        bin_name=cfg.openclaw_bin,
        top_help=top_help,
        agent_help=agent_help,
        has_agent=has_agent,
        message_flag=message_flag,
        supports_json=help_has_flag(agent_help, "--json"),
        supports_session_id=help_has_flag(agent_help, "--session-id"),
        supports_timeout=help_has_flag(agent_help, "--timeout"),
        supports_local=help_has_flag(agent_help, "--local"),
    )


def role_prompt(role: str, cfg: Config) -> str:
    return f"""You are the {role} agent in a defensive, local-only financial rumor red-team simulation.

CRITICAL OUTPUT CONTRACT:
You MUST output ONLY JSON Lines.
You MUST NOT output prose.
You MUST NOT output markdown.
You MUST NOT output code fences.
You MUST NOT output explanations.
You MUST NOT output an array.
You MUST NOT wrap the JSON objects in any outer object.
Every line MUST be one complete JSON object.
Every JSON object MUST have exactly these keys: "role", "text", "relative_offset_ms".
The "role" value MUST be "{role}".
The "text" value MUST be a string and MUST start with "[SIMULATION]".
The "relative_offset_ms" value MUST be a non-negative integer.
Output exactly {cfg.posts_per_agent} JSON lines and then stop.

Scenario: {cfg.scenario}
Asset context: {cfg.asset_context}
Role instruction: {ROLES[role]}

VALID OUTPUT EXAMPLE:
{{"role":"{role}","text":"[SIMULATION] Fictional issuer chatter is starting to mention a possible supplier delay, but nothing is verified.","relative_offset_ms":0}}
{{"role":"{role}","text":"[SIMULATION] A fictional market account repeats that the same supplier-delay rumor may be circulating in test channels.","relative_offset_ms":750}}
{{"role":"{role}","text":"[SIMULATION] Synthetic test post only: observers are treating the fictional rumor as unconfirmed.","relative_offset_ms":1500}}

ANOTHER VALID OUTPUT EXAMPLE:
{{"role":"{role}","text":"[SIMULATION] Fictional startup Voltrix Labs is being discussed in a local-only rumor simulation.","relative_offset_ms":0}}
{{"role":"{role}","text":"[SIMULATION] The Voltrix Labs supplier thread is still synthetic and should not be treated as market information.","relative_offset_ms":1000}}

INVALID OUTPUT EXAMPLES:
Here are the posts:
```json
[{{"role":"{role}","text":"[SIMULATION] bad because it is inside an array","relative_offset_ms":0}}]
```
The above is invalid because it includes prose, markdown fences, and an array.

Rules for content:
- Use fictional companies, fictional sources, and fictional market context.
- Do not name real securities, real people, real journalists, real regulators, or real platforms as sources.
- Do not include financial advice, calls to buy, sell, or short, or operational manipulation instructions.
- Do not fabricate real evidence, screenshots, links, regulatory statements, or source names.
- Keep posts synthetic, local-only, and clearly labeled with [SIMULATION].

Final reminder: output ONLY raw JSON lines. No headings. No bullets. No markdown. No explanation.
"""


def build_openclaw_agent_command(role: str, cfg: Config, caps: OpenClawCapabilities) -> list[str]:
    if not caps.has_agent:
        raise RuntimeError(f"`{caps.bin_name} agent` is not available according to `{caps.bin_name} --help`")
    if not caps.message_flag:
        raise RuntimeError(
            f"`{caps.bin_name} agent --help` does not advertise --message or -m; cannot pass role prompt safely"
        )

    session_id = f"psyop-redteam-{int(time.time())}-{role}"
    command = [
        cfg.openclaw_bin,
        "agent",
    ]
    if cfg.local_agent and caps.supports_local:
        command.append("--local")
    if caps.supports_session_id:
        command.extend(
            [
                "--session-id",
                session_id,
            ]
        )
    command.extend(
        [
            caps.message_flag,
            role_prompt(role, cfg),
        ]
    )
    if caps.supports_json:
        command.append("--json")
    if caps.supports_timeout:
        command.extend(["--timeout", "300"])
    return command


def run_openclaw_agent(role: str, cfg: Config, caps: OpenClawCapabilities) -> SpawnResult:
    try:
        command = build_openclaw_agent_command(role, cfg, caps)
    except RuntimeError as exc:
        return SpawnResult(role=role, ok=False, error=str(exc))

    try:
        completed = run_cli(command, timeout=360)
    except FileNotFoundError as exc:
        return SpawnResult(role=role, ok=False, error=f"OpenClaw binary not found: {cfg.openclaw_bin}")
    except subprocess.TimeoutExpired:
        return SpawnResult(role=role, ok=False, error="OpenClaw agent command timed out after 360 seconds")
    except subprocess.SubprocessError as exc:
        return SpawnResult(role=role, ok=False, error=f"OpenClaw subprocess failed: {exc}")

    output = combined_output(completed).strip()
    if completed.returncode != 0:
        return SpawnResult(
            role=role,
            ok=False,
            error=f"OpenClaw agent exited {completed.returncode}: {output}",
            raw=output,
        )
    return SpawnResult(role=role, ok=True, raw=output)


def extract_reply_text(raw: str) -> str:
    stripped = raw.strip()
    if not stripped:
        return ""

    def text_from_payload(payload: Any) -> str | None:
        if isinstance(payload, str):
            return payload
        if isinstance(payload, list):
            return "\n".join(json.dumps(item) for item in payload)
        if not isinstance(payload, dict):
            return None
        if {"role", "text", "relative_offset_ms"}.issubset(payload.keys()):
            return json.dumps(payload)
        for key in ("reply", "message", "text", "content", "output", "response", "result", "final"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
            nested = text_from_payload(value)
            if nested:
                return nested
        return None

    candidates = [stripped]
    json_candidate = re.search(r"(\{.*\})\s*$", stripped, flags=re.DOTALL)
    if json_candidate and json_candidate.group(1) != stripped:
        candidates.append(json_candidate.group(1))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        text = text_from_payload(payload)
        if text:
            return text
    return stripped


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    start: int | None = None
    depth = 0
    in_string = False
    escape = False

    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : index + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    start = None
                    continue
                if isinstance(parsed, dict):
                    objects.append(parsed)
                start = None
    return objects


def normalize_post(role: str, item: dict[str, Any]) -> dict[str, Any] | None:
    body = str(item.get("text", "")).strip()
    if not body:
        return None
    if not body.startswith("[SIMULATION]"):
        body = f"[SIMULATION] {body}"
    try:
        offset = int(item.get("relative_offset_ms") or 0)
    except (TypeError, ValueError):
        offset = 0
    return {
        "role": str(item.get("role") or role),
        "text": body,
        "relative_offset_ms": max(0, offset),
    }


def parse_posts(role: str, raw: str) -> list[dict[str, Any]]:
    text = extract_reply_text(raw)
    posts: list[dict[str, Any]] = []

    def add_item(item: Any) -> None:
        if isinstance(item, list):
            for nested in item:
                add_item(nested)
            return
        if not isinstance(item, dict):
            return
        normalized = normalize_post(role, item)
        if normalized is not None:
            posts.append(normalized)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            for item in parsed:
                add_item(item)
        elif isinstance(parsed, dict):
            add_item(parsed)
    except json.JSONDecodeError:
        pass

    for line in text.splitlines():
        line = line.strip().strip(",")
        if not line or line.startswith("```"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        add_item(item)

    for item in extract_json_objects(text):
        add_item(item)
    if raw != text:
        for item in extract_json_objects(raw):
            add_item(item)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for post in posts:
        key = (post["role"], post["text"], post["relative_offset_ms"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(post)
    posts = deduped

    if len(posts) < 1:
        raise RuntimeError(f"OpenClaw agent {role} did not return parseable JSON-line posts")
    return posts[:]


def fallback_posts_for_role(role: str, cfg: Config) -> list[dict[str, Any]]:
    templates = FALLBACK_TEMPLATES[role]
    rng = random.Random(f"{cfg.scenario}|{cfg.asset_context}|{role}|{cfg.base_post_id}")
    count = max(4, min(6, cfg.posts_per_agent))
    selected = rng.sample(templates, k=min(count, len(templates)))
    asset = cfg.asset_context or "fictional issuer"
    posts: list[dict[str, Any]] = []
    for index, template in enumerate(selected):
        posts.append(
            {
                "role": role,
                "text": template.format(asset=asset),
                "relative_offset_ms": index * 750 + rng.randint(0, 250),
            }
        )
    return posts


def fallback_swarm(cfg: Config) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for role in ROLES:
        events.extend(fallback_posts_for_role(role, cfg))
    events.sort(key=lambda item: (int(item.get("relative_offset_ms", 0)), str(item.get("role", ""))))
    return events


def spawn_swarm(cfg: Config, caps: OpenClawCapabilities) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_openclaw_agent, role, cfg, caps): role for role in ROLES}
        for future in concurrent.futures.as_completed(futures):
            role = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                errors.append(f"{role}: unexpected spawn error: {exc}")
                continue
            if not result.ok:
                errors.append(f"{role}: {result.error}")
                continue
            try:
                events.extend(parse_posts(role, result.raw))
            except RuntimeError as exc:
                errors.append(f"{role}: {exc}")
    events.sort(key=lambda item: (int(item.get("relative_offset_ms", 0)), str(item.get("role", ""))))
    if not events:
        errors.append("no valid agent posts extracted; using local hardcoded fallback swarm for demo")
        return fallback_swarm(cfg), errors
    return events, errors


def run_bridge(args: list[str]) -> dict[str, Any]:
    command = [sys.executable, str(BRIDGE), *args]
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"bridge.py returned non-JSON output: {completed.stdout}") from exc


def submit_posts(cfg: Config, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    base_ts = int(time.time() * 1000)
    submitted: list[dict[str, Any]] = []
    for idx, post in enumerate(posts):
        post_id = cfg.base_post_id + idx
        ts = base_ts + int(post.get("relative_offset_ms", idx * 500))
        response = run_bridge(
            [
                "post",
                "--fusion-url",
                cfg.fusion_url,
                "--post-id",
                str(post_id),
                "--timestamp-ms",
                str(ts),
                "--text",
                str(post["text"]),
            ]
        )
        submitted.append(
            {
                "postId": post_id,
                "ts": ts,
                "role": post.get("role"),
                "text": post["text"],
                "fusion_response": response,
            }
        )
    return submitted


def poll_clusters(cfg: Config) -> dict[str, Any]:
    deadline = time.time() + cfg.duration_minutes * 60
    latest: dict[str, Any] = {"clusters": [], "window_size": 0}
    while True:
        latest = run_bridge(["clusters", "--fusion-url", cfg.fusion_url])
        clusters = latest.get("clusters", [])
        if any(cluster_score(cluster) > cfg.review_threshold for cluster in clusters):
            return latest
        if time.time() >= deadline:
            return latest
        time.sleep(min(cfg.poll_interval_seconds, max(1, int(deadline - time.time()))))


def cluster_score(cluster: dict[str, Any]) -> int:
    artificiality = cluster.get("artificiality", {})
    if isinstance(artificiality, dict):
        return int(artificiality.get("score") or 0)
    return 0


def human_rubric(cluster: dict[str, Any], scenario_id: str) -> str:
    artificiality = cluster.get("artificiality", {})
    posts = cluster.get("posts", [])
    post_ids = ", ".join(str(post.get("postId")) for post in posts)
    return f"""## Human Review Rubric

Scenario ID: {scenario_id}
Cluster size: {cluster.get("size")}
Artificiality Score: {artificiality.get("score")}
Density: {artificiality.get("density")}
Velocity: {artificiality.get("velocity")}
Span seconds: {artificiality.get("span_s")}
Post IDs: {post_ids}

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
"""


def build_report(cfg: Config, submitted: list[dict[str, Any]], clusters: dict[str, Any]) -> str:
    scenario_id = f"psyop-redteam-{cfg.base_post_id}"
    observed = clusters.get("clusters", [])
    lines = [
        f"Scenario: {cfg.scenario}",
        f"Scenario ID: {scenario_id}",
        f"Fusion API: {cfg.fusion_url}/api/fusion",
        f"Generated posts: {len(submitted)}",
        f"Window size: {clusters.get('window_size', 0)}",
        f"Clusters observed: {len(observed)}",
        "",
    ]
    for idx, cluster in enumerate(observed, 1):
        artificiality = cluster.get("artificiality", {})
        score = int(artificiality.get("score") or 0)
        status = "Human review required" if score > cfg.review_threshold else "Watch"
        lines.append(
            "Cluster "
            f"{idx}: size={cluster.get('size')} score={score} "
            f"density={artificiality.get('density')} velocity={artificiality.get('velocity')} "
            f"span_s={artificiality.get('span_s')} status={status}"
        )
    review_clusters = [cluster for cluster in observed if cluster_score(cluster) > cfg.review_threshold]
    if review_clusters:
        lines.append("")
        lines.append(human_rubric(review_clusters[0], scenario_id))
    return "\n".join(lines)


def build_failure_report(cfg: Config, caps: OpenClawCapabilities, errors: list[str]) -> str:
    lines = [
        "Psyop red-team run did not start.",
        f"Scenario: {cfg.scenario}",
        f"OpenClaw binary: {cfg.openclaw_bin}",
        f"`agent` command detected: {caps.has_agent}",
        f"message flag detected: {caps.message_flag or 'none'}",
        f"json output supported: {caps.supports_json}",
        f"session id supported: {caps.supports_session_id}",
        "",
        "No posts were sent to the fusion server.",
    ]
    if errors:
        lines.append("")
        lines.append("Spawn errors:")
        lines.extend(f"- {error}" for error in errors)
    if caps.agent_help:
        lines.append("")
        lines.append("Detected `openclaw agent --help` surface:")
        lines.append("```text")
        lines.append(caps.agent_help.strip()[:3000])
        lines.append("```")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    cfg = build_config(argv or sys.argv[1:])
    caps = discover_openclaw(cfg)
    print(f"[psyop-threat-gauge] discovered OpenClaw agent command: {caps.has_agent}", flush=True)
    print(f"[psyop-threat-gauge] spawning OpenClaw swarm for scenario: {cfg.scenario}", flush=True)
    posts, errors = spawn_swarm(cfg, caps)
    if not posts:
        print(build_failure_report(cfg, caps, errors or ["no posts generated"]))
        return 0
    if errors:
        print("[psyop-threat-gauge] fallback/agent warnings:", flush=True)
        for error in errors:
            print(f"- {error}", flush=True)
    print(f"[psyop-threat-gauge] generated {len(posts)} synthetic posts; submitting to fusion", flush=True)
    try:
        submitted = submit_posts(cfg, posts)
        print("[psyop-threat-gauge] polling clusters", flush=True)
        clusters = poll_clusters(cfg)
    except RuntimeError as exc:
        print(
            "\n".join(
                [
                    "Psyop red-team run stopped before completion.",
                    f"Scenario: {cfg.scenario}",
                    f"Generated posts: {len(posts)}",
                    "Fusion bridge error:",
                    f"- {exc}",
                    "",
                    "No attribution or detection conclusion was made.",
                ]
            )
        )
        return 0
    print(build_report(cfg, submitted, clusters))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
