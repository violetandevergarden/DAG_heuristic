"""Command-line interface for reproducible benchmark generation."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_generate.export import export_suite
from benchmark_generate.reference import generate_reference_results
from benchmark_generate.preemptive import export_preemptive_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("all", "random", "preemptive", "reference"))
    parser.add_argument("--output", type=Path, default=Path("benchmark"))
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--seed", type=int, default=260819)
    args = parser.parse_args()
    if args.samples < 0:
        parser.error("--samples must be non-negative")
    if args.command == "reference":
        written = generate_reference_results(args.output)
        print(f"generated {len(written)} exact reference files under {args.output / 'reference_results'}")
        return
    if args.command == "preemptive":
        written = export_preemptive_suite(
            args.output, samples=args.samples, seed=args.seed
        )
        # Rebuild the shared index while preserving the established v1 suite.
        export_suite(args.output, samples=args.samples, seed=args.seed)
        print(f"generated {len(written)} preemptive benchmark files under {args.output / 'preemptive'}")
        return
    categories = {"random"} if args.command == "random" else None
    rows = export_suite(
        args.output,
        samples=args.samples,
        seed=args.seed,
        categories=categories,
    )
    if args.command == "random":
        # The complete index is retained so references remain self-describing;
        # callers can select category=random without invoking algorithm code.
        rows = [row for row in rows if row["category"] == "random"]
    print(f"generated {len(rows)} benchmark files under {args.output}")


if __name__ == "__main__":
    main()
