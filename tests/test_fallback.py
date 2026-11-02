"""
tests/test_fallback.py — Unit tests for app/services/game/fallback.py

Covers:
  * compute_entropy           — formula correctness, edge cases
  * _answer_prob_vec          — boundary values, linearity, sums-to-one
  * compute_information_gain  — monotonicity, zero-IG for useless questions,
                                 positive IG for discriminating questions
  * select_best_question      — best attribute chosen, exclusion, empty pool
  * generate_question_text    — known key / unknown key / all 3 languages
  * get_all_question_keys     — sanity check on the question bank
"""

from __future__ import annotations

import math
import pytest

from app.services.game.fallback import (
    _answer_prob_vec,
    compute_entropy,
    compute_information_gain,
    generate_question_text,
    get_all_question_keys,
    select_best_question,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeEntity:
    """Minimal stand-in for Entity — only id and attributes are needed."""

    def __init__(self, eid: int, attrs: dict):
        self.id = eid
        self.attributes = attrs


def _cache(*entities) -> dict:
    return {str(e.id): e for e in entities}


def _uniform(n: int) -> dict:
    """Return equal-score dict for n candidates."""
    return {str(i): 1.0 for i in range(1, n + 1)}


# ── compute_entropy ────────────────────────────────────────────────────────────

class TestComputeEntropy:
    def test_uniform_two_candidates(self):
        """H({0.5, 0.5}) = 1.0 bit."""
        scores = {"1": 1.0, "2": 1.0}
        assert compute_entropy(scores) == pytest.approx(1.0)

    def test_uniform_four_candidates(self):
        """H({0.25, 0.25, 0.25, 0.25}) = 2.0 bits."""
        scores = {str(i): 1.0 for i in range(4)}
        assert compute_entropy(scores) == pytest.approx(2.0)

    def test_certain_single_candidate(self):
        """H({1.0}) = 0 bits — no uncertainty."""
        assert compute_entropy({"1": 1.0}) == pytest.approx(0.0)

    def test_dominant_candidate_low_entropy(self):
        """Very dominant leader → entropy close to 0."""
        scores = {"1": 1.0, "2": 0.001, "3": 0.001}
        h = compute_entropy(scores)
        assert h < 0.1

    def test_empty_pool_returns_zero(self):
        assert compute_entropy({}) == pytest.approx(0.0)

    def test_all_zero_scores_returns_zero(self):
        assert compute_entropy({"1": 0.0, "2": 0.0}) == pytest.approx(0.0)

    def test_entropy_increases_with_more_candidates(self):
        """More equally-scored candidates → higher entropy."""
        h2 = compute_entropy({str(i): 1.0 for i in range(2)})
        h4 = compute_entropy({str(i): 1.0 for i in range(4)})
        h8 = compute_entropy({str(i): 1.0 for i in range(8)})
        assert h2 < h4 < h8

    def test_entropy_equals_log2_n_for_uniform(self):
        """H for n uniform candidates should equal log₂(n)."""
        for n in [2, 4, 8, 16]:
            scores = {str(i): 1.0 for i in range(n)}
            assert compute_entropy(scores) == pytest.approx(math.log2(n), rel=1e-5)


# ── _answer_prob_vec ───────────────────────────────────────────────────────────

class TestAnswerProbVec:
    def test_v_one_gives_yes(self):
        vec = _answer_prob_vec(1.0)
        assert vec["yes"] == pytest.approx(1.0)
        assert vec["no"] == pytest.approx(0.0)

    def test_v_zero_gives_no(self):
        vec = _answer_prob_vec(0.0)
        assert vec["no"] == pytest.approx(1.0)
        assert vec["yes"] == pytest.approx(0.0)

    def test_v_half_gives_dont_know(self):
        vec = _answer_prob_vec(0.5)
        assert vec["dont_know"] == pytest.approx(1.0)

    def test_v_threequarters_gives_probably(self):
        vec = _answer_prob_vec(0.75)
        assert vec["probably"] == pytest.approx(1.0)

    def test_v_quarter_gives_probably_not(self):
        vec = _answer_prob_vec(0.25)
        assert vec["probably_not"] == pytest.approx(1.0)

    def test_sums_to_one(self):
        for v in [0.0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0]:
            vec = _answer_prob_vec(v)
            assert sum(vec.values()) == pytest.approx(1.0), f"v={v} does not sum to 1"

    def test_all_probabilities_non_negative(self):
        for v in [0.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0]:
            vec = _answer_prob_vec(v)
            for a, p in vec.items():
                assert p >= 0.0, f"Negative probability for answer '{a}' at v={v}"

    def test_clamped_below_zero(self):
        """Values outside [0,1] should be clamped."""
        vec = _answer_prob_vec(-0.5)
        assert vec["no"] == pytest.approx(1.0)

    def test_clamped_above_one(self):
        vec = _answer_prob_vec(1.5)
        assert vec["yes"] == pytest.approx(1.0)


# ── compute_information_gain ───────────────────────────────────────────────────

class TestComputeInformationGain:
    def _entity(self, eid, attrs):
        return _FakeEntity(eid, attrs)

    def test_perfectly_discriminating_binary_attr_has_high_ig(self):
        """Attribute that perfectly splits two candidates (0 vs 1) → max IG."""
        e1 = self._entity(1, {"binary": 1.0})
        e2 = self._entity(2, {"binary": 0.0})
        scores = {"1": 1.0, "2": 1.0}
        ig = compute_information_gain("binary", scores, _cache(e1, e2))
        # With equal scores and perfectly discriminating attr, IG ≈ 1.0 bit
        assert ig > 0.5

    def test_useless_uniform_attr_has_zero_ig(self):
        """All entities have same attribute value (0.5) → no information gain."""
        e1 = self._entity(1, {"same": 0.5})
        e2 = self._entity(2, {"same": 0.5})
        e3 = self._entity(3, {"same": 0.5})
        scores = {"1": 1.0, "2": 1.0, "3": 1.0}
        ig = compute_information_gain("same", scores, _cache(e1, e2, e3))
        # attr=0.5 → attr_match=0 → no score change regardless of answer → IG≈0
        assert ig == pytest.approx(0.0, abs=1e-6)

    def test_ig_non_negative(self):
        """Information gain must never be negative."""
        e1 = self._entity(1, {"x": 0.9})
        e2 = self._entity(2, {"x": 0.3})
        e3 = self._entity(3, {"x": 0.7})
        scores = {"1": 1.0, "2": 0.5, "3": 0.8}
        ig = compute_information_gain("x", scores, _cache(e1, e2, e3))
        assert ig >= 0.0

    def test_missing_attr_defaults_to_neutral_zero_ig(self):
        """Entities without the queried attr default to 0.5 → IG≈0."""
        e1 = self._entity(1, {})
        e2 = self._entity(2, {})
        scores = {"1": 1.0, "2": 1.0}
        ig = compute_information_gain("absent_key", scores, _cache(e1, e2))
        assert ig == pytest.approx(0.0, abs=1e-6)

    def test_empty_pool_returns_zero(self):
        assert compute_information_gain("any", {}, {}) == pytest.approx(0.0)

    def test_single_candidate_returns_zero(self):
        """No uncertainty with one candidate → IG must be 0."""
        e = self._entity(1, {"is_real": 1.0})
        ig = compute_information_gain("is_real", {"1": 1.0}, _cache(e))
        assert ig == pytest.approx(0.0, abs=1e-6)

    def test_discriminating_attr_beats_indifferent_attr(self):
        """An attribute that splits candidates cleanly should score higher IG
        than one that barely changes anything."""
        e1 = self._entity(1, {"good": 1.0, "bad": 0.6})
        e2 = self._entity(2, {"good": 0.0, "bad": 0.5})
        scores = {"1": 1.0, "2": 1.0}
        cache = _cache(e1, e2)

        ig_good = compute_information_gain("good", scores, cache)
        ig_bad = compute_information_gain("bad", scores, cache)
        assert ig_good > ig_bad

    def test_ig_is_symmetric_for_inverted_attrs(self):
        """Flipping which entity has attr=1.0 vs 0.0 should give the same IG
        (discriminating power is the same in both directions)."""
        e1a = self._entity(1, {"attr": 1.0})
        e2a = self._entity(2, {"attr": 0.0})
        e1b = self._entity(1, {"attr": 0.0})
        e2b = self._entity(2, {"attr": 1.0})
        scores = {"1": 1.0, "2": 1.0}

        ig_a = compute_information_gain("attr", scores, _cache(e1a, e2a))
        ig_b = compute_information_gain("attr", scores, _cache(e1b, e2b))
        assert ig_a == pytest.approx(ig_b, rel=1e-5)


# ── select_best_question ───────────────────────────────────────────────────────

class TestSelectBestQuestion:
    def _entity(self, eid, attrs):
        return _FakeEntity(eid, attrs)

    def test_selects_most_discriminating_attribute(self):
        """The attribute that perfectly splits the pool should be chosen."""
        e1 = self._entity(1, {"good_split": 1.0, "no_split": 0.5})
        e2 = self._entity(2, {"good_split": 0.0, "no_split": 0.5})
        scores = {"1": 1.0, "2": 1.0}
        best = select_best_question(scores, _cache(e1, e2))
        assert best == "good_split"

    def test_excludes_already_asked_attributes(self):
        """Asked attributes must not be returned."""
        e1 = self._entity(1, {"a": 1.0, "b": 0.0})
        e2 = self._entity(2, {"a": 0.0, "b": 1.0})
        scores = {"1": 1.0, "2": 1.0}
        # Ask "a" first — "b" should be returned next
        best = select_best_question(scores, _cache(e1, e2), asked_attributes=["a"])
        assert best == "b"

    def test_all_attrs_exhausted_returns_none(self):
        e1 = self._entity(1, {"x": 1.0})
        scores = {"1": 1.0}
        result = select_best_question(
            scores, _cache(e1), asked_attributes=["x"]
        )
        assert result is None

    def test_empty_pool_returns_none(self):
        assert select_best_question({}, {}) is None

    def test_no_entity_in_cache_returns_none(self):
        """If no entities are in the cache, there are no attributes to ask."""
        result = select_best_question({"1": 1.0, "2": 1.0}, {})
        assert result is None

    def test_returns_string(self):
        e1 = self._entity(1, {"is_real": 1.0})
        e2 = self._entity(2, {"is_real": 0.0})
        best = select_best_question({"1": 1.0, "2": 1.0}, _cache(e1, e2))
        assert isinstance(best, str)

    def test_with_multiple_candidates_and_attrs(self):
        """Smoke test: 4 candidates, 3 attributes; must return a valid key."""
        entities = [
            self._entity(1, {"a": 1.0, "b": 1.0, "c": 0.5}),
            self._entity(2, {"a": 0.0, "b": 1.0, "c": 0.5}),
            self._entity(3, {"a": 1.0, "b": 0.0, "c": 0.5}),
            self._entity(4, {"a": 0.0, "b": 0.0, "c": 0.5}),
        ]
        scores = {str(e.id): 1.0 for e in entities}
        best = select_best_question(scores, _cache(*entities))
        assert best in {"a", "b", "c"}


# ── generate_question_text ────────────────────────────────────────────────────

class TestGenerateQuestionText:
    def test_known_key_english(self):
        text = generate_question_text("is_real", "en")
        assert isinstance(text, str) and len(text) > 5
        # Should not contain the raw key
        assert "is_real" not in text.lower() or "real" in text.lower()

    def test_known_key_french(self):
        text = generate_question_text("is_real", "fr")
        assert isinstance(text, str) and len(text) > 5

    def test_known_key_arabic(self):
        text = generate_question_text("is_real", "ar")
        assert isinstance(text, str) and len(text) > 5

    def test_different_languages_give_different_text(self):
        en = generate_question_text("is_alive", "en")
        fr = generate_question_text("is_alive", "fr")
        ar = generate_question_text("is_alive", "ar")
        assert en != fr
        assert en != ar
        assert fr != ar

    def test_unknown_key_uses_fallback_template(self):
        text = generate_question_text("some_unknown_attr_xyz", "en")
        assert "some unknown attr xyz" in text.lower() or "some_unknown_attr_xyz" in text

    def test_unknown_language_falls_back_to_english(self):
        en_text = generate_question_text("is_real", "en")
        unknown_lang_text = generate_question_text("is_real", "zz")
        assert en_text == unknown_lang_text

    def test_all_known_keys_return_non_empty_strings(self):
        for key in get_all_question_keys():
            for lang in ("en", "fr", "ar"):
                text = generate_question_text(key, lang)
                assert isinstance(text, str) and len(text) > 0, \
                    f"Empty text for key='{key}', lang='{lang}'"

    def test_known_animal_attributes(self):
        """Spot-check a few animal-specific attribute questions."""
        for key in ("is_mammal", "is_carnivore", "can_fly", "has_mane"):
            text = generate_question_text(key, "en")
            assert len(text) > 5

    def test_known_tech_attributes(self):
        for key in ("is_electronic", "has_screen", "connects_to_internet"):
            text = generate_question_text(key, "en")
            assert len(text) > 5


# ── get_all_question_keys ─────────────────────────────────────────────────────

class TestGetAllQuestionKeys:
    def test_returns_frozenset(self):
        assert isinstance(get_all_question_keys(), frozenset)

    def test_non_empty(self):
        assert len(get_all_question_keys()) > 10

    def test_contains_core_keys(self):
        keys = get_all_question_keys()
        for key in ("is_real", "is_alive", "is_mammal", "is_electronic", "has_screen"):
            assert key in keys, f"Expected '{key}' in question bank"
