# Latest DeepSeek LLM Long-Context Compression Results

Scope: latest RepoPilot implementation only. This experiment uses DeepSeek API for LLM compression of older tool rounds, keeps recent active rounds verbatim, and validates evidence/current-request retention.

## Summary

- Provider: deepseek / deepseek-v4-pro
- Config count: 12
- DeepSeek LLM calls: 12
- LLM fallback count: 0
- Average raw prompt chars: 12290.67
- Average LLM-compressed prompt chars: 2130.50
- Average compression ratio: 77.50%
- Max compression ratio: 89.89%
- Current request preserved rate: 100%
- Evidence retention rate: 100%

## Rows

| Config | Raw prompt | LLM-compressed prompt | Compression | Calls | Fallback | Evidence retained | Request preserved |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| short-low-short | 5357 | 1928 | 64.01% | 1 | False | True | True |
| short-low-long | 5451 | 2022 | 62.91% | 1 | False | True | True |
| short-high-short | 5561 | 2132 | 61.66% | 1 | False | True | True |
| short-high-long | 5655 | 2286 | 59.58% | 1 | False | True | True |
| medium-low-short | 11343 | 1994 | 82.42% | 1 | False | True | True |
| medium-low-long | 11437 | 2088 | 81.74% | 1 | False | True | True |
| medium-high-short | 11547 | 2198 | 80.96% | 1 | False | True | True |
| medium-high-long | 11641 | 2346 | 79.85% | 1 | False | True | True |
| long-low-short | 19725 | 1994 | 89.89% | 1 | False | True | True |
| long-low-long | 19819 | 2088 | 89.46% | 1 | False | True | True |
| long-high-short | 19929 | 2198 | 88.97% | 1 | False | True | True |
| long-high-long | 20023 | 2292 | 88.55% | 1 | False | True | True |

## Resume-Safe Metric

Designed a DeepSeek-backed structured context compression path for a local coding agent; in a 12-configuration latest-version long-context benchmark, it made 12 real DeepSeek compression calls with 0 fallbacks, reducing average prompt size from 12291 to 2130 chars (77.50% average, 89.89% max) while preserving current requests and key evidence in 100% of cases.
