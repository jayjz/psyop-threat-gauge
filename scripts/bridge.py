#!/usr/bin/env python
"""Bridge helpers for the local RomanCircusPsyop fusion server.

The checked fusion_server.py accepts postId, text, ts, and a normalized
384-dimensional all-MiniLM-L6-v2 embedding. It computes the 128-bit LSH
signature server-side. This helper also emits the matching signature for
diagnostics and for future signature-only server variants.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any

import numpy as np


MODEL_NAME = "all-MiniLM-L6-v2"
FUSION_URL = "http://127.0.0.1:8000"
EMBEDDING_DIM = 384
SIGNATURE_BITS = 128


def _load_model() -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit(
            "sentence-transformers is not installed. Install the psyop repo "
            "requirements or run inside C:\\Users\\jcoul\\Desktop\\psyop\\venv."
        ) from exc
    return SentenceTransformer(MODEL_NAME)


def embed_text(text: str) -> list[float]:
    model = _load_model()
    embedding = model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    arr = np.asarray(embedding, dtype=np.float32)
    if arr.shape != (EMBEDDING_DIM,):
        raise SystemExit(f"expected {EMBEDDING_DIM}-dim embedding, got shape {arr.shape}")
    norm = float(np.linalg.norm(arr))
    if not 0.98 <= norm <= 1.02:
        arr = arr / max(norm, 1e-12)
    return arr.astype(float).tolist()


def signature_from_embedding(embedding: list[float]) -> list[int]:
    arr = np.asarray(embedding, dtype=np.float32).reshape(1, EMBEDDING_DIM)
    np.random.seed(42)
    proj_matrix = np.random.randn(EMBEDDING_DIM, SIGNATURE_BITS).astype(np.float32)
    signature = (arr @ proj_matrix > 0).astype(np.uint8).flatten()
    return [int(bit) for bit in signature]


def make_payload(post_id: int, text: str, timestamp_ms: int | None = None) -> dict[str, Any]:
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    embedding = embed_text(text)
    return {
        "postId": post_id,
        "text": text,
        "ts": ts,
        "embedding": embedding,
    }


def make_signature_payload(post_id: int, text: str, timestamp_ms: int | None = None) -> dict[str, Any]:
    ts = timestamp_ms if timestamp_ms is not None else int(time.time() * 1000)
    embedding = embed_text(text)
    return {
        "postId": post_id,
        "signature": signature_from_embedding(embedding),
        "timestamp": ts,
    }


def request_json(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {url}: {exc.reason}") from exc


def command_encode(args: argparse.Namespace) -> None:
    if args.signature_only:
        print(json.dumps(make_signature_payload(args.post_id, args.text, args.timestamp_ms)))
        return
    payload = make_payload(args.post_id, args.text, args.timestamp_ms)
    diagnostic = {
        "payload": payload,
        "signature": signature_from_embedding(payload["embedding"]),
    }
    print(json.dumps(diagnostic))


def command_post(args: argparse.Namespace) -> None:
    payload = make_payload(args.post_id, args.text, args.timestamp_ms)
    response = request_json("POST", f"{args.fusion_url.rstrip('/')}/api/fusion", payload)
    print(json.dumps(response))


def command_clusters(args: argparse.Namespace) -> None:
    response = request_json("GET", f"{args.fusion_url.rstrip('/')}/api/clusters")
    print(json.dumps(response))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RomanCircusPsyop fusion bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    encode = subparsers.add_parser("encode", help="Generate embedding payload and LSH signature")
    encode.add_argument("--post-id", type=int, default=1)
    encode.add_argument("--text", required=True)
    encode.add_argument("--timestamp-ms", type=int)
    encode.add_argument("--signature-only", action="store_true")
    encode.set_defaults(func=command_encode)

    post = subparsers.add_parser("post", help="POST a server-compatible payload to /api/fusion")
    post.add_argument("--fusion-url", default=FUSION_URL)
    post.add_argument("--post-id", type=int, required=True)
    post.add_argument("--text", required=True)
    post.add_argument("--timestamp-ms", type=int)
    post.set_defaults(func=command_post)

    clusters = subparsers.add_parser("clusters", help="GET /api/clusters")
    clusters.add_argument("--fusion-url", default=FUSION_URL)
    clusters.set_defaults(func=command_clusters)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
