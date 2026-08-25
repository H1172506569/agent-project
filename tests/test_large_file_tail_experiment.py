from repopilot.evaluation.large_file_tail import run_tail_probe


def test_head_only_strategy_misses_answer_in_large_file_tail():
    result = run_tail_probe("head_only", total_lines=2000, answer_line=2000, max_steps=6)

    assert result["correct"] is False
    assert result["read_file_calls"] == 1
    assert result["read_ranges"] == [[1, 200]]


def test_sequential_reads_still_miss_tail_answer_when_chunk_output_is_clipped():
    result = run_tail_probe("sequential", total_lines=1000, answer_line=1000, max_steps=6)

    assert result["correct"] is False
    assert result["read_file_calls"] == 6
    assert [801, 1000] in result["read_ranges"]


def test_sequential_reads_miss_tail_answer_when_default_budget_is_too_small():
    result = run_tail_probe("sequential", total_lines=2000, answer_line=2000, max_steps=6)

    assert result["correct"] is False
    assert result["required_read_pages_from_start"] == 10
    assert result["read_file_calls"] == 6
    assert result["read_ranges"][-1] == [1001, 1200]


def test_sequential_reads_find_tail_answer_when_step_budget_is_increased():
    result = run_tail_probe("sequential", total_lines=2000, answer_line=2000, max_steps=12)

    assert result["correct"] is False
    assert result["read_file_calls"] == 12
    assert [1801, 2000] in result["read_ranges"]


def test_direct_line_read_finds_tail_answer_if_exact_line_is_known():
    result = run_tail_probe("direct_line", total_lines=2000, answer_line=2000, max_steps=6)

    assert result["correct"] is True
    assert result["read_file_calls"] == 1
    assert result["read_ranges"] == [[2000, 2000]]


def test_shell_tail_strategy_finds_tail_answer_in_one_tool_call():
    result = run_tail_probe("shell_tail", total_lines=2000, answer_line=2000, max_steps=6)

    assert result["correct"] is True
    assert result["read_file_calls"] == 0
    assert result["run_shell_calls"] == 1
