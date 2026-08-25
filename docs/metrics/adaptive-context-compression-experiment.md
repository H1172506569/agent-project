# Adaptive Context Compression Experiment

## Setup

- Feature flag: `adaptive_context_compression=True`.
- Async threshold: 60% prompt budget usage.
- Sync threshold: 80% prompt budget usage.
- Compression backend: deterministic tool-round compressor for runtime stability.

## Results

| Scenario | Usage before | Action | Prompt before | Prompt after | Summary status | Persisted summary used | Current request preserved |
| --- | ---: | --- | ---: | ---: | --- | --- | --- |
| no_trigger | 17.7% | none | 248 | 248 | none | False | True |
| async_60 | 66.8% | async_scheduled | 601 | 601 | ready | False | True |
| sync_80 | 91.9% | sync_compressed | 827 | 610 | ready | True | True |
| persisted_reuse | 79.8% | async_scheduled | 718 | 718 | ready | True | True |

## Summary

- Async compression scheduled scenarios: 2.
- Sync compression scenarios: 1.
- Persisted summary reuse scenarios: 2.
- Sync prompt reduction rate: 26.2%.

## Resume-Safe Wording

- Added an adaptive context-compression scheduler with 60% async pre-compression and 80% sync compression thresholds; compressed history summaries are persisted in session state and reused by later prompt builds.
