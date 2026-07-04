"""
postman2pytest: convert a Postman Collection v2.1 into executable pytest tests.

Usage:
    python main.py --collection data/my_api.postman_collection.json --out generated_tests/test_api.py
"""

import argparse
import json
import logging
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from core.environment import load_environment
from core.generator import generate
from core.parser import ParsedRequest, parse_collection

try:
    __version__ = version("postman2pytest")
except PackageNotFoundError:
    __version__ = "1.2.0"

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def filter_requests_by_folder(
    requests: list[ParsedRequest], folder_name: str
) -> list[ParsedRequest]:
    """Return requests whose parsed folder slug matches the requested name."""
    normalized = folder_name.casefold()
    return [
        request
        for request in requests
        if request.folder and request.folder.casefold() == normalized
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Postman Collection v2.1 into executable pytest tests."
    )
    parser.add_argument("--version", action="version", version=f"postman2pytest {__version__}")
    parser.add_argument(
        "--collection", required=True, help="Path to Postman Collection JSON file (.json)"
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output path for the generated pytest file (e.g. generated_tests/test_api.py)",
    )
    parser.add_argument(
        "--base-url",
        help="Print a run tip with this BASE_URL after generation (generated tests read BASE_URL from the env var)",
    )
    parser.add_argument(
        "--filter-folder",
        help="Only generate tests for requests in the named Postman folder (case-insensitive)",
    )
    parser.add_argument(
        "--env",
        help=(
            "Path to a Postman environment JSON export. Non-secret variables are "
            "resolved to literal values in the generated tests; secret and unknown "
            "variables stay as os.environ lookups."
        ),
    )
    parser.add_argument(
        "--max-input-mb",
        type=int,
        default=100,
        help="Refuse to load collections larger than this many MB (default: 100)",
    )
    args = parser.parse_args()

    collection_path = Path(args.collection)
    if not collection_path.exists():
        logger.error("Collection file not found: %s", collection_path)
        return 1

    size_mb = collection_path.stat().st_size / (1024 * 1024)
    if size_mb > args.max_input_mb:
        logger.error(
            "Collection file is %.1f MB, larger than --max-input-mb %d. Refusing to load.",
            size_mb,
            args.max_input_mb,
        )
        return 1

    try:
        collection_name = (
            json.loads(collection_path.read_text(encoding="utf-8"))
            .get("info", {})
            .get("name", collection_path.stem)
        )
    except (json.JSONDecodeError, OSError, KeyError) as exc:
        logger.warning(
            "Could not read collection name from %s: %s. Falling back to file stem.",
            collection_path,
            exc,
        )
        collection_name = collection_path.stem

    requests = parse_collection(collection_path)
    if args.filter_folder:
        requests = filter_requests_by_folder(requests, args.filter_folder)
        if not requests:
            logger.error("Folder not found or contains no valid requests: %s", args.filter_folder)
            return 1

    if not requests:
        logger.error("No valid requests found in collection. Nothing to generate.")
        return 1

    postman_env = None
    if args.env:
        env_path = Path(args.env)
        if not env_path.exists():
            logger.error("Environment file not found: %s", env_path)
            return 1
        try:
            postman_env = load_environment(env_path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Could not read environment file %s: %s", env_path, exc)
            return 1

    output_path = Path(args.out)
    generate(
        requests,
        collection_name=collection_name,
        output_path=output_path,
        postman_env=postman_env,
    )

    print(f"\nGenerated {len(requests)} test(s) -> {output_path}")
    print(f"  Run with: pytest {output_path} -v")
    if args.base_url:
        print(f"  Tip: BASE_URL={args.base_url} pytest {output_path} -v")
    else:
        print("  Tip: set BASE_URL env var to point at your API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
