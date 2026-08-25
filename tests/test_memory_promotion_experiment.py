from repopilot.evaluation.memory_promotion import run_memory_promotion_experiment


def test_memory_promotion_experiment_identifies_save_group_as_best(tmp_path):
    result = run_memory_promotion_experiment(output_dir=tmp_path)

    assert result["summary"]["best_group"] == "D_candidate_save_promotion"
    assert result["candidate_count"] == 180
    assert result["candidates_per_type"] == 30
    assert set(result["category_distribution"].values()) == {30}

    groups = {group["group"]: group for group in result["groups"]}
    save = groups["D_candidate_save_promotion"]["metrics"]
    direct = groups["C_llm_direct_summary_write"]["metrics"]
    save_by_category = groups["D_candidate_save_promotion"]["category_metrics"]

    assert save["candidate_count"] == 180
    assert save["promoted_count"] == 90
    assert save["rejected_count"] == 60
    assert save["pending_count"] == 30
    assert save["evidence_coverage"] == 1.0
    assert save["promotion_precision_proxy"] == 1.0
    assert save["rejected_sensitive_candidate_count"] == 30
    assert save["duplicate_candidate_suppression_count"] == 0
    assert save["conflict_detection_count"] == 30
    assert direct["sensitive_leak_count"] == 30
    assert save["sensitive_leak_count"] == 0

    assert save_by_category["stable_convention"]["promoted_count"] == 30
    assert save_by_category["dependency_fact"]["promoted_count"] == 30
    assert save_by_category["user_preference"]["promoted_count"] == 30
    assert save_by_category["transient_noise"]["transient_rejected_count"] == 30
    assert save_by_category["sensitive_secret"]["sensitive_rejected_count"] == 30
    assert save_by_category["conflict"]["conflict_pending_count"] == 30

    assert (tmp_path / "p7-memory-promotion-experiment.json").exists()
    assert (tmp_path / "p7-memory-promotion-experiment.md").exists()
