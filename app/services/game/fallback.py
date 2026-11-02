"""
app/services/game/fallback.py — Information-Gain Fallback Question Selector.

Purpose
-------
When the LLM provider is unavailable (or raises ``LLMFallbackError``), the
game engine falls back to this pure-KB mode.  Instead of asking the LLM to
generate a creative question, we deterministically choose the entity attribute
that conveys the most information — i.e. the one whose yes/no answer most
evenly splits the candidate pool, as measured by Shannon entropy.

Algorithm
---------
For each candidate attribute key ``q`` not yet asked this session:

1. **Current entropy** H(C):

       H(C) = −Σ_c  P(c) · log₂ P(c)

   where P(c) is the probability mass of candidate c, computed from the
   current normalized scores.

2. **Answer probability vector** P(a | q):

   For each entity c, its attribute value v_c ∈ [0, 1] implies a soft
   distribution over the 5 possible player answers.  We use a piecewise
   linear "bucketizer" so that:

   * v = 1.0  → player almost certainly says "yes"
   * v = 0.75 → player leans "probably"
   * v = 0.5  → player says "don't know"
   * v = 0.25 → player leans "probably not"
   * v = 0.0  → player almost certainly says "no"

   P(a | q) = Σ_c P(c) · prob_vec(v_c)[a]

3. **Conditional entropy** H(C | a, q):

   Apply ``candidates.update_scores(scores, a, attr_key, cache)`` for each
   answer ``a``, then compute the entropy of the resulting score distribution.

4. **Information gain**:

       IG(q) = H(C) − Σ_a P(a | q) · H(C | a, q)

5. ``select_best_question`` iterates over all attributes present in the
   candidate pool, computes IG for each, excludes already-asked ones, and
   returns the key with the highest IG.

Question-Text Generation
------------------------
``generate_question_text(attribute_key, language)`` maps a snake_case
attribute key to a human-readable yes/no question in English, French, or
Arabic (Algerian Darija).  A comprehensive built-in dictionary covers common
game attributes; unknown keys fall back to a generic template.
"""

from __future__ import annotations

import logging
import math
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from app.services.game.candidates import _normalize, update_scores

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_EPS: float = 1e-9

#: All 5 canonical player answers, in score-update order.
_ANSWERS: List[str] = ["yes", "probably", "dont_know", "probably_not", "no"]

# ── Question text dictionary ──────────────────────────────────────────────────
# Structure: { attribute_key: { "en": "...", "fr": "...", "ar": "..." } }
# Arabic uses Algerian Darija phonetics.

_QUESTION_BANK: Dict[str, Dict[str, str]] = {
    # ── Existence / Reality ──────────────────────────────────────────────────
    "is_real": {
        "en": "Is it a real thing (not fictional)?",
        "fr": "Est-ce quelque chose de réel (non fictif) ?",
        "ar": "واش هو حقيقي (مش خيالي) ؟",
    },
    "is_fictional": {
        "en": "Is it a fictional character or thing?",
        "fr": "Est-ce un personnage ou une chose fictif(ve) ?",
        "ar": "واش هو شخصية أو شيء خيالي ؟",
    },
    "is_alive": {
        "en": "Is it currently alive?",
        "fr": "Est-ce encore en vie actuellement ?",
        "ar": "واش هو حي دابا ؟",
    },
    "is_historical": {
        "en": "Is it a historical figure or object?",
        "fr": "Est-ce un personnage ou objet historique ?",
        "ar": "واش هو شخصية أو شيء تاريخي ؟",
    },
    # ── Gender ───────────────────────────────────────────────────────────────
    "is_female": {
        "en": "Is it female?",
        "fr": "Est-ce une femme / de sexe féminin ?",
        "ar": "واش هي أنثى ؟",
    },
    "is_male": {
        "en": "Is it male?",
        "fr": "Est-ce un homme / de sexe masculin ?",
        "ar": "واش هو ذكر ؟",
    },
    # ── Profession / Role ────────────────────────────────────────────────────
    "is_scientist": {
        "en": "Is it a scientist?",
        "fr": "Est-ce un(e) scientifique ?",
        "ar": "واش هو/هي عالم/عالمة ؟",
    },
    "is_computer_scientist": {
        "en": "Is it a computer scientist or software engineer?",
        "fr": "Est-ce un(e) informaticien(ne) ou ingénieur(e) logiciel ?",
        "ar": "واش هو/هي متخصص/ة في علوم الحاسوب أو هندسة البرمجيات ؟",
    },
    "is_mathematician": {
        "en": "Is it a mathematician?",
        "fr": "Est-ce un(e) mathématicien(ne) ?",
        "ar": "واش هو/هي رياضياتي/رياضياتية ؟",
    },
    "is_programmer": {
        "en": "Is it a programmer or software developer?",
        "fr": "Est-ce un(e) programmeur(euse) ou développeur(euse) ?",
        "ar": "واش هو/هي مبرمج/ة ؟",
    },
    "is_artist": {
        "en": "Is it an artist (painter, musician, actor …)?",
        "fr": "Est-ce un(e) artiste (peintre, musicien, acteur …) ?",
        "ar": "واش هو/هي فنان/فنانة (رسام، موسيقي، ممثل …) ؟",
    },
    "is_athlete": {
        "en": "Is it an athlete or sports player?",
        "fr": "Est-ce un(e) athlète ou sportif(ve) ?",
        "ar": "واش هو/هي رياضي/رياضية ؟",
    },
    "is_politician": {
        "en": "Is it a politician or world leader?",
        "fr": "Est-ce un homme/une femme politique ou un chef d'État ?",
        "ar": "واش هو/هي سياسي/سياسية أو قائد/ة دولة ؟",
    },
    "is_inventor": {
        "en": "Is it an inventor?",
        "fr": "Est-ce un(e) inventeur(trice) ?",
        "ar": "واش هو/هي مخترع/ة ؟",
    },
    "is_writer": {
        "en": "Is it a writer or author?",
        "fr": "Est-ce un(e) écrivain(e) ou auteur(e) ?",
        "ar": "واش هو/هي كاتب/ة ؟",
    },
    "is_philosopher": {
        "en": "Is it a philosopher?",
        "fr": "Est-ce un(e) philosophe ?",
        "ar": "واش هو/هي فيلسوف ؟",
    },
    # ── Provenance / Origin ──────────────────────────────────────────────────
    "is_human": {
        "en": "Is it a human being?",
        "fr": "Est-ce un être humain ?",
        "ar": "واش هو إنسان ؟",
    },
    "is_animal": {
        "en": "Is it an animal?",
        "fr": "Est-ce un animal ?",
        "ar": "واش هو حيوان ؟",
    },
    "is_object": {
        "en": "Is it a physical object or device?",
        "fr": "Est-ce un objet physique ou un appareil ?",
        "ar": "واش هو شيء مادي أو جهاز ؟",
    },
    "is_place": {
        "en": "Is it a place or location?",
        "fr": "Est-ce un endroit ou un lieu ?",
        "ar": "واش هو مكان ؟",
    },
    "is_concept": {
        "en": "Is it an abstract concept or idea?",
        "fr": "Est-ce un concept abstrait ou une idée ?",
        "ar": "واش هو مفهوم مجرد أو فكرة ؟",
    },
    # ── Geography ────────────────────────────────────────────────────────────
    "lives_in_africa": {
        "en": "Does it live in (or originate from) Africa?",
        "fr": "Vit-il (ou est-il originaire) d'Afrique ?",
        "ar": "واش يعيش (أو اصله من) إفريقيا ؟",
    },
    "lives_in_europe": {
        "en": "Does it live in (or originate from) Europe?",
        "fr": "Vit-il (ou est-il originaire) d'Europe ?",
        "ar": "واش يعيش (أو اصله من) أوروبا ؟",
    },
    "lives_in_asia": {
        "en": "Does it live in (or originate from) Asia?",
        "fr": "Vit-il (ou est-il originaire) d'Asie ?",
        "ar": "واش يعيش (أو اصله من) آسيا ؟",
    },
    "lives_in_americas": {
        "en": "Does it live in (or originate from) the Americas?",
        "fr": "Vit-il (ou est-il originaire) des Amériques ?",
        "ar": "واش يعيش (أو اصله من) الأمريكتين ؟",
    },
    # ── Biology / Animals ────────────────────────────────────────────────────
    "is_mammal": {
        "en": "Is it a mammal?",
        "fr": "Est-ce un mammifère ?",
        "ar": "واش هو من الثدييات ؟",
    },
    "is_bird": {
        "en": "Is it a bird?",
        "fr": "Est-ce un oiseau ?",
        "ar": "واش هو طائر ؟",
    },
    "is_reptile": {
        "en": "Is it a reptile?",
        "fr": "Est-ce un reptile ?",
        "ar": "واش هو زاحف ؟",
    },
    "is_fish": {
        "en": "Is it a fish?",
        "fr": "Est-ce un poisson ?",
        "ar": "واش هو سمكة ؟",
    },
    "is_insect": {
        "en": "Is it an insect?",
        "fr": "Est-ce un insecte ?",
        "ar": "واش هو حشرة ؟",
    },
    "is_carnivore": {
        "en": "Is it a carnivore (eats meat)?",
        "fr": "Est-ce un carnivore (mange de la viande) ?",
        "ar": "واش هو آكل لحوم ؟",
    },
    "is_herbivore": {
        "en": "Is it a herbivore (eats plants)?",
        "fr": "Est-ce un herbivore (mange des plantes) ?",
        "ar": "واش هو آكل نباتات ؟",
    },
    "is_wild": {
        "en": "Is it a wild animal (not domesticated)?",
        "fr": "Est-ce un animal sauvage (non domestiqué) ?",
        "ar": "واش هو حيوان بري (مش مدجن) ؟",
    },
    "is_pet": {
        "en": "Is it commonly kept as a pet?",
        "fr": "Est-ce communément gardé comme animal de compagnie ?",
        "ar": "واش يتربى غالباً كحيوان أليف ؟",
    },
    "can_fly": {
        "en": "Can it fly?",
        "fr": "Peut-il voler ?",
        "ar": "واش يقدر يطير ؟",
    },
    "lives_in_water": {
        "en": "Does it live in water?",
        "fr": "Vit-il dans l'eau ?",
        "ar": "واش يعيش في الماء ؟",
    },
    "has_mane": {
        "en": "Does it have a mane?",
        "fr": "A-t-il une crinière ?",
        "ar": "واش عنده لبدة (شعر الرقبة) ؟",
    },
    "has_wings": {
        "en": "Does it have wings?",
        "fr": "A-t-il des ailes ?",
        "ar": "واش عنده أجنحة ؟",
    },
    "has_fur": {
        "en": "Does it have fur or hair?",
        "fr": "A-t-il de la fourrure ou des poils ?",
        "ar": "واش عنده فروة أو شعر ؟",
    },
    "has_scales": {
        "en": "Does it have scales?",
        "fr": "A-t-il des écailles ?",
        "ar": "واش عنده حراشف ؟",
    },
    "is_large": {
        "en": "Is it larger than a dog?",
        "fr": "Est-ce plus grand qu'un chien ?",
        "ar": "واش هو أكبر من كلب ؟",
    },
    "is_endangered": {
        "en": "Is it an endangered species?",
        "fr": "Est-ce une espèce en danger d'extinction ?",
        "ar": "واش هو من الأنواع المهددة بالانقراض ؟",
    },
    # ── Technology / Objects ─────────────────────────────────────────────────
    "is_electronic": {
        "en": "Is it an electronic device?",
        "fr": "Est-ce un appareil électronique ?",
        "ar": "واش هو جهاز إلكتروني ؟",
    },
    "has_screen": {
        "en": "Does it have a screen?",
        "fr": "A-t-il un écran ?",
        "ar": "واش عنده شاشة ؟",
    },
    "portable": {
        "en": "Is it portable (easy to carry around)?",
        "fr": "Est-ce portable (facile à transporter) ?",
        "ar": "واش هو محمول (سهل التنقل به) ؟",
    },
    "connects_to_internet": {
        "en": "Does it connect to the internet?",
        "fr": "Se connecte-t-il à internet ?",
        "ar": "واش يتوصل بالإنترنت ؟",
    },
    "uses_electricity": {
        "en": "Does it use electricity?",
        "fr": "Utilise-t-il de l'électricité ?",
        "ar": "واش يخدم بالكهرباء ؟",
    },
    "is_vehicle": {
        "en": "Is it a vehicle or means of transport?",
        "fr": "Est-ce un véhicule ou moyen de transport ?",
        "ar": "واش هو مركبة أو وسيلة نقل ؟",
    },
    "is_tool": {
        "en": "Is it a tool or instrument?",
        "fr": "Est-ce un outil ou instrument ?",
        "ar": "واش هو أداة أو آلة ؟",
    },
    "is_furniture": {
        "en": "Is it a piece of furniture?",
        "fr": "Est-ce un meuble ?",
        "ar": "واش هو أثاث (حاجة للمنزل) ؟",
    },
    "is_food": {
        "en": "Is it something you can eat?",
        "fr": "Est-ce quelque chose que l'on peut manger ?",
        "ar": "واش هو شيء ياكل ؟",
    },
    "is_made_of_metal": {
        "en": "Is it made of metal?",
        "fr": "Est-ce fabriqué en métal ?",
        "ar": "واش مصنوع من المعدن ؟",
    },
    "is_weapon": {
        "en": "Is it a weapon?",
        "fr": "Est-ce une arme ?",
        "ar": "واش هو سلاح ؟",
    },
    # ── Fame / Pop culture ───────────────────────────────────────────────────
    "is_famous": {
        "en": "Is it well known worldwide?",
        "fr": "Est-ce mondialement connu(e) ?",
        "ar": "واش هو/هي مشهور/ة على مستوى العالم ؟",
    },
    "is_from_20th_century": {
        "en": "Did it exist mainly in the 20th century?",
        "fr": "A-t-il existé principalement au XXe siècle ?",
        "ar": "واش عاش أو وُجد بزاف في القرن العشرين ؟",
    },
    "is_from_21st_century": {
        "en": "Did it emerge in the 21st century?",
        "fr": "Est-il apparu au XXIe siècle ?",
        "ar": "واش ظهر في القرن الحادي والعشرين ؟",
    },
    "is_award_winner": {
        "en": "Has it won a major award (Nobel, Oscar, etc.)?",
        "fr": "A-t-il remporté un grand prix (Nobel, Oscar …) ?",
        "ar": "واش ربح جائزة كبيرة (نوبل، أوسكار …) ؟",
    },
}

# Fallback template per language when the attribute key is not in the bank.
_FALLBACK_TEMPLATE: Dict[str, str] = {
    "en": "Does it have the attribute '{key}'?",
    "fr": "A-t-il l'attribut '{key}' ?",
    "ar": "واش عنده الخاصية '{key}' ؟",
}


# ── Public API ────────────────────────────────────────────────────────────────


def compute_entropy(candidate_scores: Dict[str, float]) -> float:
    """Compute the Shannon entropy H(C) = −Σ P(c) log₂ P(c) over candidates.

    Parameters
    ----------
    candidate_scores:
        ``{entity_id_str: float}`` — raw scores (need not sum to 1; this
        function normalizes internally).

    Returns
    -------
    float
        Entropy in bits.  Returns 0.0 for an empty or single-element pool.
    """
    total = sum(candidate_scores.values())
    if total < _EPS:
        return 0.0

    entropy = 0.0
    for score in candidate_scores.values():
        p = score / total
        if p > _EPS:
            entropy -= p * math.log2(p)

    return entropy


def _answer_prob_vec(attr_value: float) -> Dict[str, float]:
    """Map an entity's attribute value to a soft probability distribution
    over the 5 player answers.

    Uses a piecewise-linear model centred on 5 evenly-spaced breakpoints:

    * v = 1.0   → yes = 1.0
    * v = 0.75  → probably = 1.0
    * v = 0.5   → dont_know = 1.0
    * v = 0.25  → probably_not = 1.0
    * v = 0.0   → no = 1.0

    Linear interpolation is used between adjacent breakpoints so that the
    distribution varies smoothly.

    Parameters
    ----------
    attr_value:
        Entity attribute value clamped to [0, 1].

    Returns
    -------
    dict
        Probability mass for each of the 5 answers (sums to 1.0).
    """
    v = max(0.0, min(1.0, float(attr_value)))

    # Breakpoints: no=0.0, probably_not=0.25, dont_know=0.5, probably=0.75, yes=1.0
    breakpoints = [
        (0.0,  {"no": 1.0, "probably_not": 0.0, "dont_know": 0.0, "probably": 0.0, "yes": 0.0}),
        (0.25, {"no": 0.0, "probably_not": 1.0, "dont_know": 0.0, "probably": 0.0, "yes": 0.0}),
        (0.5,  {"no": 0.0, "probably_not": 0.0, "dont_know": 1.0, "probably": 0.0, "yes": 0.0}),
        (0.75, {"no": 0.0, "probably_not": 0.0, "dont_know": 0.0, "probably": 1.0, "yes": 0.0}),
        (1.0,  {"no": 0.0, "probably_not": 0.0, "dont_know": 0.0, "probably": 0.0, "yes": 1.0}),
    ]

    # Find the two adjacent breakpoints and linearly interpolate
    for i in range(len(breakpoints) - 1):
        v0, d0 = breakpoints[i]
        v1, d1 = breakpoints[i + 1]
        if v0 <= v <= v1:
            t = (v - v0) / (v1 - v0) if (v1 - v0) > _EPS else 0.0
            return {ans: d0[ans] * (1 - t) + d1[ans] * t for ans in _ANSWERS}

    # Fallback: exact match at v=1.0
    return {"yes": 1.0, "probably": 0.0, "dont_know": 0.0, "probably_not": 0.0, "no": 0.0}


def compute_information_gain(
    attribute_key: str,
    candidate_scores: Dict[str, float],
    entities_cache: Dict[str, object],
) -> float:
    """Compute the information gain for asking a question about *attribute_key*.

    IG(q) = H(C) − Σₐ P(a|q) · H(C|a, q)

    Parameters
    ----------
    attribute_key:
        The entity attribute to evaluate (e.g. ``"is_real"``).
    candidate_scores:
        Current ``{entity_id_str: float}`` scores.
    entities_cache:
        ``{entity_id_str: Entity}`` — pre-fetched entities.  Entities absent
        from the cache default to attribute value 0.5 (neutral).

    Returns
    -------
    float
        Information gain in bits (≥ 0).  Returns 0.0 for an empty pool.
    """
    if not candidate_scores:
        return 0.0

    current_h = compute_entropy(candidate_scores)

    total_score = sum(candidate_scores.values())
    if total_score < _EPS:
        return 0.0

    # --- Accumulate P(a|q) by summing entity contributions ------------------
    answer_probs: Dict[str, float] = {a: 0.0 for a in _ANSWERS}

    for eid, score in candidate_scores.items():
        entity = entities_cache.get(eid)
        attr_value = 0.5  # default neutral
        if entity is not None:
            attr_value = float((entity.attributes or {}).get(attribute_key, 0.5))

        p_entity = score / total_score
        vec = _answer_prob_vec(attr_value)
        for ans in _ANSWERS:
            answer_probs[ans] += p_entity * vec[ans]

    # --- For each possible answer, compute conditional entropy ---------------
    conditional_h = 0.0
    for answer in _ANSWERS:
        p_answer = answer_probs[answer]
        if p_answer < _EPS:
            continue  # This answer is impossible for the current candidate set

        updated = update_scores(
            candidate_scores, answer, attribute_key, entities_cache=entities_cache
        )
        h_given_answer = compute_entropy(updated)
        conditional_h += p_answer * h_given_answer

    ig = current_h - conditional_h
    return max(0.0, ig)  # guard against tiny floating-point negatives


def select_best_question(
    candidate_scores: Dict[str, float],
    entities_cache: Dict[str, object],
    asked_attributes: Optional[List[str]] = None,
) -> Optional[str]:
    """Return the attribute key whose question yields the highest information gain.

    Iterates over every attribute key present in any candidate entity, skips
    keys already asked this session, and returns the key with the highest IG.

    Parameters
    ----------
    candidate_scores:
        Current ``{entity_id_str: float}`` scores.
    entities_cache:
        ``{entity_id_str: Entity}`` — pre-fetched candidate entities.
    asked_attributes:
        List (or set) of attribute keys already asked this session.
        Defaults to an empty list.

    Returns
    -------
    str or None
        The attribute key with the highest information gain, or ``None`` if
        the candidate pool is empty or all attributes have been exhausted.
    """
    asked: Set[str] = set(asked_attributes or [])

    # Collect all attribute keys present in at least one candidate entity
    all_attrs: Set[str] = set()
    for eid in candidate_scores:
        entity = entities_cache.get(eid)
        if entity is not None and entity.attributes:
            all_attrs.update(entity.attributes.keys())

    remaining_attrs = all_attrs - asked

    if not remaining_attrs:
        logger.warning(
            "select_best_question: no remaining attributes to ask "
            "(pool=%d, asked=%d, total_attrs=%d)",
            len(candidate_scores),
            len(asked),
            len(all_attrs),
        )
        return None

    best_attr: Optional[str] = None
    best_ig: float = -1.0

    for attr_key in remaining_attrs:
        ig = compute_information_gain(attr_key, candidate_scores, entities_cache)
        logger.debug("IG(%s) = %.4f", attr_key, ig)
        if ig > best_ig:
            best_ig = ig
            best_attr = attr_key

    logger.info(
        "select_best_question → '%s' (IG=%.4f, candidates=%d, remaining_attrs=%d)",
        best_attr,
        best_ig,
        len(candidate_scores),
        len(remaining_attrs),
    )
    return best_attr


def generate_question_text(attribute_key: str, language: str) -> str:
    """Map an entity attribute key to a natural-language yes/no question.

    Parameters
    ----------
    attribute_key:
        Snake_case attribute key (e.g. ``"is_real"``, ``"has_screen"``).
    language:
        ISO 639-1 code — ``"en"``, ``"fr"``, or ``"ar"``.

    Returns
    -------
    str
        A human-readable yes/no question in the requested language.
        Falls back to English if the language is unknown, and to a generic
        template if the attribute key is not in the built-in dictionary.
    """
    lang = language if language in ("en", "fr", "ar") else "en"

    entry = _QUESTION_BANK.get(attribute_key)
    if entry:
        return entry.get(lang, entry["en"])

    # Generate a readable label from the snake_case key as a last resort
    template = _FALLBACK_TEMPLATE.get(lang, _FALLBACK_TEMPLATE["en"])
    readable_key = attribute_key.replace("_", " ")
    return template.format(key=readable_key)


def get_all_question_keys() -> FrozenSet[str]:
    """Return the set of attribute keys covered by the built-in question bank.

    Useful for the game engine to decide whether to fall back to the generic
    template or use the curated question text.
    """
    return frozenset(_QUESTION_BANK.keys())
