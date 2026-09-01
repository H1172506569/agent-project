# P7 Memory Candidate + SAVE Promotion Experiment

This benchmark compares four durable-memory strategies on 180 candidate facts across 6 categories, with 30 candidates per category.

## Candidate Distribution

| Category | Candidates |
| --- | ---: |
| stable_convention | 30 |
| dependency_fact | 30 |
| user_preference | 30 |
| transient_noise | 30 |
| sensitive_secret | 30 |
| conflict | 30 |

## Strategy Results

| Group | Promoted | Rejected | Pending | Evidence coverage | Precision proxy | Sensitive leaks | Duplicate suppressed | Conflicts detected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A_no_durable_memory | 0 | 0 | 0 | 0% | 0% | 0 | 0 | 0 |
| B_file_style_durable_memory | 90 | 0 | 0 | 0% | 100% | 0 | 0 | 0 |
| C_llm_direct_summary_write | 180 | 0 | 0 | 0% | 50% | 30 | 0 | 0 |
| D_candidate_save_promotion | 90 | 60 | 30 | 100% | 100% | 0 | 0 | 30 |

## SAVE Category Outcomes

| Category | Candidates | Promoted | Rejected | Pending | Sensitive rejected | Transient rejected | Conflict pending |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| stable_convention | 30 | 30 | 0 | 0 | 0 | 0 | 0 |
| dependency_fact | 30 | 30 | 0 | 0 | 0 | 0 | 0 |
| user_preference | 30 | 30 | 0 | 0 | 0 | 0 | 0 |
| transient_noise | 30 | 0 | 30 | 0 | 0 | 30 | 0 |
| sensitive_secret | 30 | 0 | 30 | 0 | 30 | 0 | 0 |
| conflict | 30 | 0 | 0 | 30 | 0 | 0 | 30 |

## Result

Best group: `D_candidate_save_promotion`.

Resume-safe wording:

- Designed an evidence-bound long-term memory promotion pipeline with MemoryCandidate, SAVE scoring, dedupe, conflict detection and sensitive-info filtering.
- In a 180-candidate durable-memory benchmark across 6 categories, the SAVE group promoted 90 reusable facts, rejected 60 unsafe/noisy candidates, and held 30 conflicting candidates for confirmation, reaching 100% evidence coverage and 100% promotion precision proxy.
- Compared with direct LLM summary writes, SAVE reduced sensitive memory leaks from 30 to 0 in the benchmark.
