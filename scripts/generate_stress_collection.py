#!/usr/bin/env python
"""Generate a synthetic Postman v2.1 collection at any requested scale.

Defaults to 500 requests across deep folder trees with folder names that
mix ASCII, Cyrillic, accented Latin, and CJK characters so name-sanitiser
edge cases get exercised. Used by the `stress-test` CI job (and locally
when reasoning about generation speed and pytest collection limits) so
real Postman exports in the 500-2000 request range stay green.

Usage:
    python scripts/generate_stress_collection.py --requests 500 \
        --out data/stress_collection_500.json

Run `python scripts/generate_stress_collection.py --help` for all flags.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ASCII_FOLDER_NAMES = (
    "Auth",
    "Users",
    "Orders",
    "Inventory",
    "Search",
    "Billing",
    "Webhooks",
    "Admin",
    "Reports",
    "Notifications",
)
CYRILLIC_FOLDER_NAMES = (
    "Каталог",
    "Заказы",
    "Доставка",
    "Авторизация",
    "Платежи",
    "Аналитика",
)
ACCENTED_FOLDER_NAMES = (
    "Réservations",
    "Cancellations Élégantes",
    "Détails Produit",
    "Mise à jour",
)
CJK_FOLDER_NAMES = (
    "用户",
    "订单",
    "商品",
    "支付",
)
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
RESOURCE_WORDS = (
    "items",
    "users",
    "orders",
    "products",
    "sessions",
    "tokens",
    "logs",
    "events",
    "metrics",
    "preferences",
)


def random_folder_name(rng: random.Random) -> str:
    pool = (
        ASCII_FOLDER_NAMES * 4
        + CYRILLIC_FOLDER_NAMES * 2
        + ACCENTED_FOLDER_NAMES
        + CJK_FOLDER_NAMES
    )
    return rng.choice(pool)


def random_request(rng: random.Random, index: int) -> dict:
    method = rng.choice(METHODS)
    resource = rng.choice(RESOURCE_WORDS)
    path_pieces = [resource]
    if rng.random() < 0.6:
        path_pieces.append("{id}")
    if rng.random() < 0.3:
        path_pieces.append(rng.choice(RESOURCE_WORDS))
    raw = "https://api.example.test/" + "/".join(path_pieces)
    return {
        "name": f"{method} {resource} {index}",
        "request": {
            "method": method,
            "header": [{"key": "Accept", "value": "application/json"}],
            "url": {
                "raw": raw,
                "protocol": "https",
                "host": ["api", "example", "test"],
                "path": path_pieces,
            },
            "body": (
                {"mode": "raw", "raw": json.dumps({"index": index})}
                if method in {"POST", "PUT", "PATCH"}
                else {}
            ),
        },
        "response": [],
    }


def build_folder_tree(rng: random.Random, requests: int, max_depth: int) -> list[dict]:
    """Distribute `requests` over a folder tree up to `max_depth` deep."""
    folders: list[dict] = []
    remaining = requests
    request_index = 1

    while remaining > 0:
        depth = rng.randint(1, max_depth)
        cursor_parent: list[dict] = folders
        for level in range(depth):
            name = random_folder_name(rng) + (f" L{level}" if level else "")
            existing = next((f for f in cursor_parent if f["name"] == name), None)
            if existing is None:
                existing = {"name": name, "item": []}
                cursor_parent.append(existing)
            cursor_parent = existing["item"]

        batch_size = min(remaining, rng.randint(3, 12))
        for _ in range(batch_size):
            cursor_parent.append(random_request(rng, request_index))
            request_index += 1
        remaining -= batch_size

    return folders


def build_collection(requests: int, max_depth: int, seed: int) -> dict:
    rng = random.Random(seed)
    folders = build_folder_tree(rng, requests, max_depth)
    return {
        "info": {
            "name": f"Stress Test Collection ({requests} reqs)",
            "_postman_id": f"stress-{seed}-{requests}",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": folders,
    }


def count_requests(items: list[dict]) -> int:
    total = 0
    for it in items:
        if "request" in it:
            total += 1
        if "item" in it:
            total += count_requests(it["item"])
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=500, help="Total request count")
    parser.add_argument("--max-depth", type=int, default=4, help="Max folder nesting")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/stress_collection_500.json"),
        help="Output path for the generated collection JSON",
    )
    args = parser.parse_args()

    collection = build_collection(args.requests, args.max_depth, args.seed)
    actual = count_requests(collection["item"])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {args.out} with {actual} requests (seed={args.seed}, max_depth={args.max_depth})")
    if actual < args.requests:
        print(
            f"warning: produced {actual} requests, fewer than requested {args.requests}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
