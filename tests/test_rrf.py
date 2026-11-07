import pytest

from multimodal_doc_rag.search import rrf


def test_docstring_example() -> None:
    result = rrf([[7, 3], [3, 9]])
    assert [i for i, _ in result] == [3, 7, 9]
    assert result[0][1] == pytest.approx(1 / 62 + 1 / 61)
    assert result[1][1] == pytest.approx(1 / 61)
    assert result[2][1] == pytest.approx(1 / 62)


def test_item_in_both_lists_beats_items_in_one() -> None:
    # 5 is only 3rd in each list but still beats both list-topping singletons.
    result = rrf([[1, 2, 5], [3, 4, 5]])
    assert result[0][0] == 5


def test_ties_break_by_first_appearance() -> None:
    # 1 and 2 are each rank 1 in one list: equal scores; the earlier list's item wins.
    assert [i for i, _ in rrf([[1], [2]])] == [1, 2]
    assert [i for i, _ in rrf([[2], [1]])] == [2, 1]


def test_empty_input() -> None:
    assert rrf([]) == []
    assert rrf([[], []]) == []


def test_k_changes_scores() -> None:
    small = dict(rrf([[1]], k=1))
    large = dict(rrf([[1]], k=100))
    assert small[1] == pytest.approx(1 / 2)
    assert large[1] == pytest.approx(1 / 101)
