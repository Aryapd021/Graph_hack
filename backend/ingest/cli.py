"""Ingestion CLI dispatcher.

Per ARCHITECTURE.md sections 5, 7, 8, 19:
- Command: python -m ingest {fetch|load|synth|derive|embed|verify|all}
- Flags:
    --refresh: passed to fetch to force re-download
    --synthetic: passed to load to load synthetic entities instead of GitHub cache
    --reset: drops only the graph named FALKORDB_GRAPH. If host is not localhost, requires --yes.
    --yes: confirm dangerous drop operation on non-localhost host
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from brain_core.config import get_ingest_settings, get_settings
from brain_core.db import get_db
from ingest.derive import run_derive
from ingest.embed import run_embed
from ingest.github_loader import GitHubFetcher
from ingest.loaders import load_from_cache, load_synthetic_from_files
from ingest.synthetic_gen import generate_synthetic_data
from ingest.verify import run_verify


def get_cache_dir() -> Path:
    """Resolve data/cache/github relative to repository root."""
    return Path(__file__).resolve().parent.parent.parent / "data" / "cache" / "github"


def get_synthetic_dir() -> Path:
    """Resolve data/synthetic relative to repository root."""
    return Path(__file__).resolve().parent.parent.parent / "data" / "synthetic"


def handle_reset(yes_flag: bool) -> None:
    """Drop the graph named FALKORDB_GRAPH.

    Why: Section 7 mandates: --reset drops only the graph named FALKORDB_GRAPH and,
    when the host is not localhost, requires --yes (print host and graph name before dropping).
    """
    settings = get_settings()
    host = settings.FALKORDB_HOST.strip()
    graph_name = settings.FALKORDB_GRAPH.strip()

    is_localhost = host.lower() in ("localhost", "127.0.0.1", "::1")

    if not is_localhost and not yes_flag:
        print(
            f"ERROR: Target FalkorDB host '{host}' is not localhost. "
            f"Dropping graph '{graph_name}' requires --yes flag.\n"
            f"Run: python -m ingest all --reset --yes",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Resetting graph: dropping graph '{graph_name}' on host '{host}'...", flush=True)
    db = get_db()
    try:
        g = db.select_graph(graph_name)
        g.delete()
        print(f"Graph '{graph_name}' dropped successfully.", flush=True)
    except Exception as exc:
        # If the graph does not exist yet, treat as success
        print(f"Note on drop: {exc}", flush=True)


def main(argv: Optional[list[str]] = None) -> None:
    """Parse command line arguments and dispatch ingestion pipeline subcommands."""
    parser = argparse.ArgumentParser(
        prog="python -m ingest",
        description="CompanyBrain ingestion pipeline",
    )
    parser.add_argument(
        "subcommand",
        choices=["fetch", "load", "synth", "derive", "embed", "verify", "all"],
        help="Pipeline step to run",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force refetch of GitHub data, ignoring existing cache",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Load synthetic entities (Team, Decision, Ticket, Thread) and their relationships",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop graph FALKORDB_GRAPH before running step",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm dropping graph when host is not localhost",
    )

    args = parser.parse_args(argv)

    # 1. Handle --reset if requested
    if args.reset:
        handle_reset(yes_flag=args.yes)

    cache_dir = get_cache_dir()
    synthetic_dir = get_synthetic_dir()

    # 2. Dispatch subcommand
    cmd = args.subcommand
    if cmd == "fetch":
        fetcher = GitHubFetcher()
        fetcher.run_fetch(cache_dir=cache_dir, refresh=args.refresh)

    elif cmd == "load":
        if args.synthetic:
            load_synthetic_from_files(synthetic_dir=synthetic_dir)
        else:
            load_from_cache(cache_dir=cache_dir)

    elif cmd == "synth":
        generate_synthetic_data(cache_dir=cache_dir, output_dir=synthetic_dir)

    elif cmd == "derive":
        run_derive(synthetic_dir=synthetic_dir)

    elif cmd == "verify":
        run_verify(synthetic_dir=synthetic_dir)

    elif cmd == "embed":
        run_embed()

    elif cmd == "all":
        print("\n=== Pipeline Step 1: GitHub Data Load ===", flush=True)
        # Check if cache exists or fetch needed
        if not (cache_dir / "prs.json").exists() or args.refresh:
            fetcher = GitHubFetcher()
            fetcher.run_fetch(cache_dir=cache_dir, refresh=args.refresh)
        load_from_cache(cache_dir=cache_dir)

        print("\n=== Pipeline Step 2: Synthetic Data Generation ===", flush=True)
        generate_synthetic_data(cache_dir=cache_dir, output_dir=synthetic_dir)

        print("\n=== Pipeline Step 3: Synthetic Data Load ===", flush=True)
        load_synthetic_from_files(synthetic_dir=synthetic_dir)

        print("\n=== Pipeline Step 4: Graph Edge Derivation ===", flush=True)
        run_derive(synthetic_dir=synthetic_dir)

        print("\n=== Pipeline Step 5: Embeddings Generation ===", flush=True)
        run_embed()

        print("\n=== Pipeline Step 6: Verification Gates ===", flush=True)
        run_verify(synthetic_dir=synthetic_dir)

        print("\nIngestion pipeline completed successfully.")


if __name__ == "__main__":
    main()
