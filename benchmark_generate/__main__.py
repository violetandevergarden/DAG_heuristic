"""Command-line interface for reproducible benchmark generation."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchmark_generate.export import build_index, export_semantic_suite
from benchmark_generate.reference import generate_reference_results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("all", "random", "reference"))
    parser.add_argument("--output", type=Path, default=Path("benchmark"))
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--seed", type=int, default=260819)
    parser.add_argument(
        "--category",
        choices=("adversarial", "random", "real", "all"),
        default="adversarial",
        help="reference command category selection",
    )
    parser.add_argument(
        "--semantics",
        choices=("all", "preemptive", "nonpreemptive"),
        default="all",
    )
    args = parser.parse_args()
    if args.samples < 0:
        parser.error("--samples must be non-negative")
    if args.command == "reference":
        written = generate_reference_results(
            args.output,
            category=None if args.category == "all" else args.category,
        )
        print(
            f"generated {len(written)} exact reference files under {args.output / 'reference_results'}"
        )
        return
    categories = {"random"} if args.command == "random" else None
    if args.semantics in {"all", "nonpreemptive"}:
        export_semantic_suite(
            args.output,
            semantics="nonpreemptive",
            samples=args.samples,
            seed=args.seed,
            categories=categories,
        )
    if args.semantics in {"all", "preemptive"}:
        export_semantic_suite(
            args.output,
            semantics="preemptive",
            samples=args.samples,
            seed=args.seed,
            categories=categories,
        )
    rows = build_index(args.output)
    if args.command == "random":
        # The complete index is retained so references remain self-describing;
        # callers can select category=random without invoking algorithm code.
        rows = [row for row in rows if row["category"] == "random"]
    print(f"generated {len(rows)} benchmark files under {args.output}")


if __name__ == "__main__":
    main()
