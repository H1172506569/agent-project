from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repopilot.evaluation.context_compression import run_context_compression_experiment


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run P6 context compression experiment.")
    parser.add_argument("--compression-mode", choices=("deterministic", "llm"), default="deterministic")
    parser.add_argument("--provider", default="deepseek")
    args = parser.parse_args()
    output_dir = ROOT / "docs" / "metrics"
    result = run_context_compression_experiment(output_dir=output_dir, compression_mode=args.compression_mode, provider=args.provider)
    suffix = "llm" if args.compression_mode == "llm" else "deterministic"
    print("Wrote:")
    print(output_dir / f"context-compression-p6-{suffix}-experiment.json")
    print(output_dir / f"context-compression-p6-{suffix}-experiment.md")
    print(f"compression_mode={result.get('compression_mode')}, provider={result.get('provider', {}).get('provider')}, llm_calls={result.get('summary', {}).get('llm_call_count', 0)}")
    for row in result["groups"]:
        print(
            f"{row['group']}: pass_rate={row['task_pass_rate']:.0%}, "
            f"repeated_reads={row['repeated_reads']}, prompt_chars={row['prompt_chars']}, "
            f"active_rounds={row['active_round_count']}, compressed_rounds={row['compressed_round_count']}, "
            f"llm_calls={row.get('llm_call_count', 0)}, fallback={row.get('llm_fallback_used', False)}"
        )
