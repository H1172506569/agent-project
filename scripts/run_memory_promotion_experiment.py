from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repopilot.evaluation.memory_promotion import run_memory_promotion_experiment


if __name__ == "__main__":
    output_dir = ROOT / "docs" / "metrics"
    result = run_memory_promotion_experiment(output_dir=output_dir)
    print("Wrote:")
    print(result["output_json"])
    print(result["output_md"])
    print(f"best_group={result['summary']['best_group']}")
    for group in result["groups"]:
        metrics = group["metrics"]
        print(
            f"{group['group']}: promoted={metrics['promoted_count']}, rejected={metrics['rejected_count']}, "
            f"pending={metrics['pending_count']}, evidence={metrics['evidence_coverage']:.0%}, "
            f"precision={metrics['promotion_precision_proxy']:.0%}, sensitive_leaks={metrics['sensitive_leak_count']}"
        )
