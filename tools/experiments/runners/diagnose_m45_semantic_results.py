"""Analyze existing M4.5-P2 result vectors without loading an embedding model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from xuanyi_npc.evaluation.semantic_memory_diagnostics import (
    analyze_saved_results,
    write_diagnostic_result,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run1", type=Path, required=True)
    parser.add_argument("--run2", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze_saved_results(
        run1_path=args.run1,
        run2_path=args.run2,
        input_path=args.inputs,
        expectation_path=args.expectations,
        manifest_path=args.manifest,
    )
    write_diagnostic_result(result, args.output)
    print(
        json.dumps(
            {
                "analysis_label": result.analysis_label,
                "scenario_count": len(result.scenarios),
                "counterfactual_count": len(result.counterfactuals),
                "ordered_results_match": result.ordered_results_match,
                "metrics_match": result.metrics_match,
                "vector_payloads_match": result.vector_payloads_match,
                "max_vector_absolute_difference": (
                    result.max_vector_absolute_difference
                ),
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
