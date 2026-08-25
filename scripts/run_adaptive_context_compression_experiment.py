from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repopilot.evaluation.adaptive_context_compression import run_adaptive_context_compression_experiment


if __name__ == "__main__":
    output_dir = ROOT / "docs" / "metrics"
    result = run_adaptive_context_compression_experiment(output_dir=output_dir)
    print("Wrote:")
    print(output_dir / "adaptive-context-compression-experiment.json")
    print(output_dir / "adaptive-context-compression-experiment.md")
    for row in result["scenarios"]:
        print(
            f"{row['scenario']}: usage={row['usage_ratio_before']:.1%}, action={row['scheduler_action']}, "
            f"before={row['prompt_chars_before']}, after={row['prompt_chars_after']}, "
            f"summary={row['summary_status']}, persisted={row['persisted_summary_used']}"
        )
