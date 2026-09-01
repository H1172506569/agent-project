# P6 Context Compression Experiment Results

## Setup

- Design: 2 x 2 ablation, context strategy (`section_clipping` vs `tool_round_compression`) crossed with memory on/off.
- Workload: deterministic synthetic long-tool-history tasks covering recent result retention, old path retention, failed tool status retention, and memory fact retention.
- Metrics: prompt chars, retained active rounds, compressed rounds, repeated reads, task pass rate, compression failures.

## Results

| Group | Strategy | Memory | Prompt chars | Active rounds | Compressed rounds | Repeated reads | Pass rate | Compression failures |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| section_clipping_memory_on | section_clipping | True | 825 | 0 | 0 | 3 | 50% | 0 |
| section_clipping_memory_off | section_clipping | False | 691 | 0 | 0 | 4 | 25% | 0 |
| tool_round_compression_memory_on | tool_round_compression | True | 840 | 2 | 16 | 1 | 75% | 0 |
| tool_round_compression_memory_off | tool_round_compression | False | 706 | 2 | 16 | 2 | 50% | 0 |

## Summary

- Best group: `tool_round_compression_memory_on` with 75% pass rate and 1 repeated reads.
- Tool-round compression average pass rate: 62%; section clipping average pass rate: 38%.
- Tool-round compression average repeated reads: 1.5; section clipping average repeated reads: 3.5.
- Compression failure count stayed at 0 across all compression groups.

## Resume-Safe Wording

- Designed and implemented a deterministic three-zone context compression strategy for a coding agent, retaining recent tool rounds while compressing older tool outputs into structured breadcrumbs with path and failure-status preservation.
- Built a 2x2 ablation benchmark over context strategy and memory settings; tool-round compression improved average task pass rate from 38% to 62% and reduced repeated reads from 3.5 to 1.5 on the synthetic long-context suite.
