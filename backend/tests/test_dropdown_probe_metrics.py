from scripts.eval.dropdown_rank_probe import (
    aggregate,
    rank_of,
    reciprocal_rank,
)


def test_rank_of_finds_position():
    assert rank_of([7, 3, 9], 3) == 2


def test_rank_of_returns_none_when_absent():
    assert rank_of([7, 3, 9], 4) is None


def test_reciprocal_rank_at_one():
    assert reciprocal_rank([5, 1], 5) == 1.0


def test_reciprocal_rank_absent_is_zero():
    assert reciprocal_rank([5, 1], 99) == 0.0


def test_aggregate_averages():
    rows = [
        {"top1_hit": True,  "top3_hit": True,  "acceptable_at_1": True,
         "reciprocal_rank": 1.0, "gold_rank": 1},
        {"top1_hit": False, "top3_hit": True,  "acceptable_at_1": False,
         "reciprocal_rank": 0.5, "gold_rank": 2},
    ]
    result = aggregate(rows)

    assert result["words"] == 2
    assert result["top1_accuracy"] == 0.5
    assert result["top3_accuracy"] == 1.0
    assert result["mrr"] == 0.75
    assert result["mean_gold_rank"] == 1.5


def test_aggregate_handles_empty():
    assert aggregate([]) == {"words": 0}