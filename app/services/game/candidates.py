"""
app/services/game/candidates.py — Candidate Scoring Engine.

Responsibilities
----------------
The scoring engine maintains a probability-like dict of
``{entity_id_str: float}`` across the lifetime of one game session.
Every time the player answers a question, all candidate scores are updated
based on how well each entity's attribute value matches the answer.

Attribute Value Convention
--------------------------
Each entity's ``attributes`` JSONB column stores float values in [0, 1]:

  * 1.0  — the attribute is fully true for this entity
            (e.g. ``"is_real": 1.0`` for Alan Turing)
  * 0.0  — the attribute is definitely false
            (e.g. ``"is_alive": 0.0`` for Alan Turing)
  * 0.5  — the attribute is partially or uncertainly true (default assumed
            when the key is absent, i.e. "unknown")

Scoring Weight Table
--------------------
Answer         Player weight   Combined attribute effect
-----------    ------------    ------------------------------------------
yes            +1.0            ``+1.0 × attr_match(v)``
probably       +0.5            ``+0.5 × attr_match(v)``
dont_know       0.0            No change to any score
probably_not   −0.5            ``−0.5 × attr_match(v)``
no             −1.0            ``−1.0 × attr_match(v)``

``attr_match(v)`` maps the entity's attribute value to a directional
multiplier:  attr → 2*attr − 1  so that:
  * 1.0 → +1.0  (fully matches the attribute)
  * 0.5 →  0.0  (neutral / unknown)
  * 0.0 → −1.0  (definitely does NOT have the attribute)

This means a "yes" answer for an entity that definitely has the attribute
(1.0) gives the full +1.0 boost, while a "yes" answer for an entity that
definitely lacks the attribute (0.0) gives a −1.0 penalty (contradiction).

Normalization
-------------
After every update, all scores are clamped to a minimum of 0 (no negative
scores) and then normalized so the maximum score is 1.0.  This keeps the
values interpretable as a relative confidence measure.

Confidence Computation
----------------------
The "confidence" of the top-1 guess is derived from the softmax-like
share of the top candidate relative to the rest of the pool:

    confidence = top_score / (sum_of_all_scores + ε)

clamped to [0.0, 1.0].
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from app.models.entity import Entity, EntityCategory
from app.repositories.entity_repo import EntityRepository

logger = logging.getLogger(__name__)

# Tiny epsilon to avoid division-by-zero in confidence calculation.
_EPS: float = 1e-9

# Answer weights applied to the attribute-match signal.
_ANSWER_WEIGHTS: Dict[str, float] = {
    "yes": 1.0,
    "probably": 0.5,
    "dont_know": 0.0,
    "probably_not": -0.5,
    "no": -1.0,
}

# Score delta applied per turn (keeps scores bounded even after many turns).
_SCORE_STEP: float = 1.0


# ── Public API ────────────────────────────────────────────────────────────────


def load_candidates(category: str) -> Dict[str, float]:
    """Fetch all approved entities for *category* and return initial scores.

    Every entity starts with an equal score of 1.0 so the first answer has
    a uniform baseline to work from.

    Parameters
    ----------
    category:
        One of ``"character"``, ``"animal"``, ``"object"``.

    Returns
    -------
    dict
        ``{str(entity_id): 1.0, ...}`` — keys are *string* IDs so the dict
        round-trips cleanly through JSON / Redis without integer → string
        coercion surprises.

    Raises
    ------
    ValueError
        If *category* is not a valid :class:`~app.models.entity.EntityCategory`.
    """
    cat = EntityCategory(category)
    entities: List[Entity] = EntityRepository.list_approved_by_category(cat)

    scores: Dict[str, float] = {str(e.id): 1.0 for e in entities}

    logger.info(
        "Loaded %d candidates for category '%s'",
        len(scores),
        category,
    )
    return scores


def _attr_match(attr_value: float) -> float:
    """Map an attribute float value [0, 1] to a directional signal in [−1, +1].

    Parameters
    ----------
    attr_value:
        Raw attribute value from the entity's JSONB ``attributes`` dict.

    Returns
    -------
    float
        ``2 * attr_value − 1``:
        * 1.0 → +1.0 (fully matches)
        * 0.5 →  0.0 (neutral)
        * 0.0 → −1.0 (definitely absent)
    """
    return 2.0 * float(attr_value) - 1.0


def _normalize(scores: Dict[str, float]) -> Dict[str, float]:
    """Clamp all scores to ≥ 0 and then scale so the maximum equals 1.0.

    Parameters
    ----------
    scores:
        Mutable candidate score dict (values may be negative after updates).

    Returns
    -------
    dict
        New dict with the same keys and normalized values.
    """
    # First pass: clamp negatives to 0
    clamped = {eid: max(0.0, s) for eid, s in scores.items()}

    max_score = max(clamped.values(), default=0.0)
    if max_score < _EPS:
        # All scores collapsed to zero — reset uniformly so the game can continue
        n = len(clamped)
        return {eid: (1.0 / n if n else 0.0) for eid in clamped}

    return {eid: s / max_score for eid, s in clamped.items()}


def update_scores(
    candidate_scores: Dict[str, float],
    answer: str,
    attribute_key: str,
    entities_cache: Optional[Dict[str, Entity]] = None,
) -> Dict[str, float]:
    """Apply one Q&A turn to the candidate score dict and return updated scores.

    The function **does not mutate** the input dict; it returns a new dict.

    Parameters
    ----------
    candidate_scores:
        Current ``{entity_id_str: float}`` scores (values already normalized
        to [0, 1]).
    answer:
        Player's answer — one of ``"yes"``, ``"no"``, ``"dont_know"``,
        ``"probably"``, ``"probably_not"``.
    attribute_key:
        The entity attribute key that the question targeted
        (e.g. ``"is_real"``, ``"is_alive"``).
    entities_cache:
        Optional pre-fetched ``{entity_id_str: Entity}`` dict.  When provided,
        avoids individual DB lookups per entity.  Pass ``None`` to trigger
        individual lazy fetches (fine for small candidate pools; use the cache
        for large ones).

    Returns
    -------
    dict
        Updated and normalized ``{entity_id_str: float}`` scores.

    Raises
    ------
    ValueError
        If *answer* is not one of the five recognized answer strings.
    """
    if answer not in _ANSWER_WEIGHTS:
        raise ValueError(
            f"Unknown answer '{answer}'. "
            f"Must be one of: {list(_ANSWER_WEIGHTS)}"
        )

    weight = _ANSWER_WEIGHTS[answer]

    # dont_know → no information gain; return scores unchanged
    if weight == 0.0:
        logger.debug(
            "update_scores: answer='dont_know' → no score change for attr '%s'",
            attribute_key,
        )
        return dict(candidate_scores)

    updated: Dict[str, float] = {}

    for eid, current_score in candidate_scores.items():
        # Fetch entity (from cache or DB)
        entity: Optional[Entity] = None
        if entities_cache is not None:
            entity = entities_cache.get(eid)
        if entity is None:
            entity = EntityRepository.get_by_id(int(eid))

        if entity is None:
            # Entity was deleted mid-game; keep current score unchanged
            logger.warning("update_scores: entity id=%s not found; skipping.", eid)
            updated[eid] = current_score
            continue

        # Retrieve the attribute value; default to 0.5 (neutral) if absent
        attr_value: float = float(
            (entity.attributes or {}).get(attribute_key, 0.5)
        )

        # Compute the score delta
        signal = _attr_match(attr_value)          # −1 to +1
        delta = weight * signal * _SCORE_STEP     # scaled delta

        updated[eid] = current_score + delta

    return _normalize(updated)


def get_top_k(
    candidate_scores: Dict[str, float],
    k: int = 10,
    excluded_ids: Optional[List[int]] = None,
) -> List[Tuple[str, float]]:
    """Return the top-K candidates sorted by score (descending).

    Parameters
    ----------
    candidate_scores:
        Current ``{entity_id_str: float}`` scores.
    k:
        Maximum number of results to return.
    excluded_ids:
        Optional list of integer entity IDs to omit (already-guessed entities).

    Returns
    -------
    list of (entity_id_str, score)
        Up to *k* ``(str_id, score)`` tuples, highest score first.
    """
    excluded_set: set[str] = {str(eid) for eid in (excluded_ids or [])}

    eligible = [
        (eid, score)
        for eid, score in candidate_scores.items()
        if eid not in excluded_set
    ]

    eligible.sort(key=lambda t: t[1], reverse=True)
    return eligible[:k]


def get_best_guess(
    candidate_scores: Dict[str, float],
    excluded_ids: Optional[List[int]] = None,
) -> Optional[Tuple[str, float]]:
    """Return the single best-scoring candidate and its confidence.

    Confidence is computed as the top candidate's normalized score share
    of the entire (non-excluded) candidate pool:

        confidence = top_score / (total_eligible_scores + ε)

    This gives values in [0, 1] that the engine can compare against the
    ``GUESS_CONFIDENCE`` threshold.

    Parameters
    ----------
    candidate_scores:
        Current ``{entity_id_str: float}`` scores.
    excluded_ids:
        Optional list of integer entity IDs to skip (already guessed).

    Returns
    -------
    (entity_id_str, confidence_float) or None
        ``None`` when the pool is empty or all candidates are excluded.
    """
    excluded_set: set[str] = {str(eid) for eid in (excluded_ids or [])}

    eligible = {
        eid: score
        for eid, score in candidate_scores.items()
        if eid not in excluded_set
    }

    if not eligible:
        return None

    best_id = max(eligible, key=lambda eid: eligible[eid])
    best_score = eligible[best_id]
    total = sum(eligible.values())

    confidence = best_score / (total + _EPS)
    confidence = max(0.0, min(1.0, confidence))  # clamp to [0, 1]

    return best_id, confidence


def build_entity_cache(
    candidate_scores: Dict[str, float],
) -> Dict[str, Entity]:
    """Pre-fetch all entities in one call and return a lookup dict.

    Use this before calling :func:`update_scores` in a loop to avoid N
    individual DB queries.

    Parameters
    ----------
    candidate_scores:
        Current candidate score dict (only keys are used).

    Returns
    -------
    dict
        ``{entity_id_str: Entity}`` — missing entities are silently omitted.
    """
    cache: Dict[str, Entity] = {}
    for eid in candidate_scores:
        entity = EntityRepository.get_by_id(int(eid))
        if entity is not None:
            cache[eid] = entity
    return cache
