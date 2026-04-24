"""
postman2pytest — convert a Postman Collection v2.1 into executable pytest tests.

Usage:
    python main.py --collection data/my_api.postman_collection.json --out generated_tests/test_api.py
"""
import argparse
import json
import logging
import sys
from pathlib import Path

from core.generator import generate
from core.parser import parse_collection

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Postman Collection v2.1 into executable pytest tests."
    )
    parser.add_argument(
        "--collection", required=True,
        help="Path to Postman Collection JSON file (.json)"
    )
    parser.add_argument(
        "--out", required=True,
        help="Output path for the generated pytest file (e.g. generated_tests/test_api.py)"
    )
    parser.add_argument(
        "--base-url",
        help="Override BASE_URL in generated tests (default: reads from BASE_URL env var)"
    )
    args = parser.parse_args()

    collection_path = Path(args.collection)
    if not collection_path.exists():
        logger.error("Collection file not found: %s", collection_path)
        return 1

    try:
        collection_name = json.loads(
            collection_path.read_text(encoding="utf-8")
        ).get("info", {}).get("name", collection_path.stem)
    except Exception:
        collection_name = collection_path.stem

    requests = parse_collection(collection_path)
    if not requests:
        logger.error("No valid requests found in collection — nothing to generate")
        return 1

    output_path = Path(args.out)
    generate(requests, collection_name=collection_name, output_path=output_path)

    print(f"\n✓ Generated {len(requests)} test(s) → {output_path}")
    print(f"  Run with: pytest {output_path} -v")
    if args.base_url:
        print(f"  Tip: BASE_URL={args.base_url} pytest {output_path} -v")
    else:
        print(f"  Tip: set BASE_URL env var to point at your API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
