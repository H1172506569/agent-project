# Latest Long-Context Stress Results

Scope: latest RepoPilot implementation only. The experiment uses the 12-configuration long-context matrix and compares the latest context-managed prompt with a no-context-reduction baseline inside the same codebase.

## Summary

- Config count: 12
- Average raw prompt chars: 6959.33
- Average context-managed prompt chars: 5540.67
- Average compression ratio: 16.43%
- Max compression ratio: 33.72%
- Current request preserved rate: 100.00%

## Configs

| Config | Raw prompt | Managed prompt | Compression | Current request preserved |
| --- | ---: | ---: | ---: | ---: |
| short-low-short | 4509 | 4509 | 0.00% | 100% |
| short-low-long | 4581 | 4581 | 0.00% | 100% |
| short-high-short | 4707 | 4707 | 0.00% | 100% |
| short-high-long | 4779 | 4779 | 0.00% | 100% |
| medium-low-short | 6491 | 5429 | 16.36% | 100% |
| medium-low-long | 6563 | 5501 | 16.18% | 100% |
| medium-high-short | 6689 | 5627 | 15.88% | 100% |
| medium-high-long | 6761 | 5699 | 15.71% | 100% |
| long-low-short | 9473 | 6279 | 33.72% | 100% |
| long-low-long | 9545 | 6351 | 33.46% | 100% |
| long-high-short | 9671 | 6477 | 33.03% | 100% |
| long-high-long | 9743 | 6549 | 32.78% | 100% |

## Resume-Safe Metric

Designed a layered context manager for a local coding agent; in a 12-configuration latest-version long-context stress matrix, it reduced average prompt size from 6959 to 5541 chars, with 16.43% average compression, 33.72% max compression, and 100% current-request preservation.
