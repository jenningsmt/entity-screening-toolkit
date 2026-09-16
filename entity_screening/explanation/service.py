"""Orchestration for Epic J: `explain()` is the one entry point the API layer
calls. Computes the recitation, calls the one allowed generative step, and
persists the result -- idempotently, mirroring `case/demo.py`'s
`_ensure_demo_case_exists`-style caching: a second `explain()` call for the
same observation at the same evidence content and the same model/prompt
version returns the stored row rather than paying for a second live call.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from entity_screening.common.schema import ConcernTie, Finding
from entity_screening.explanation import store
from entity_screening.explanation.generate import (
    MODEL,
    PROMPT_VERSION,
    _default_anthropic_call,
    generate_synthesis,
)
from entity_screening.explanation.schema import MatchExplanation, ObservationKind
from entity_screening.explanation.skeletons import recite


def evidence_hash_for(
    observation: Finding | ConcernTie,
    case_context: list[Finding | ConcernTie] | tuple[Finding | ConcernTie, ...] = (),
) -> str:
    """The cache key's content component: a hash of the observation's own
    fully-templated recitation, plus `case_context`'s (M17 -- the
    synthesis sentence is explicitly allowed to connect the primary to
    other observations in the same case, so two cases sharing an
    identical finding but different surrounding ties must not share a
    cached sentence), plus the model/prompt version currently in use.
    `case_context`'s recitations are sorted before joining: it's built
    from store.load_findings/load_ties, whose row order isn't guaranteed
    stable across calls (M10), so sorting makes the hash depend on the
    context's *content*, not the order it happened to arrive in -- without
    it, the same logical context could hash differently between the call
    that cached a row and a later call that reads it. Since
    `finding_id`/`tie_id` are already regenerated (uuid4) on every
    reconciliation run, this hash mainly guards against a
    model/prompt_version change invalidating a previously-cached
    explanation for an otherwise-unchanged observation, not against
    evidence drift under a fixed id (which can't happen -- ids don't
    persist across runs). Public (not `_`-prefixed): the API layer's
    ungated `GET .../explanation` route (case_routes.py) needs to compute
    the same cache key `explain()` uses below, so the two paths agree on
    what "the cached explanation" means."""
    context_payload = "|".join(sorted(recite(o) for o in case_context))
    payload = f"{recite(observation)}|{context_payload}|{MODEL}|{PROMPT_VERSION}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def explain(
    conn,
    observation_kind: ObservationKind,
    observation: Finding | ConcernTie,
    case_id: str,
    case_context: list[Finding | ConcernTie],
    *,
    synthetic: bool,
    call: Callable[[dict[str, Any]], Any] = _default_anthropic_call,
) -> MatchExplanation:
    """`call` is the same injectable-external-service parameter as
    `generate_synthesis`'s -- threaded through explicitly (not left as a
    module-level default for a test to monkeypatch) because a Python
    default argument is bound once at function-definition time; patching
    the module attribute afterward would silently miss it."""
    observation_id = (
        observation.finding_id
        if isinstance(observation, Finding)
        else observation.tie_id
    )
    evidence_hash = evidence_hash_for(observation, case_context)

    cached = store.load_explanation(conn, observation_id, evidence_hash)
    if cached is not None:
        return cached

    synthesis = generate_synthesis(observation, case_context, call=call)

    explanation = MatchExplanation(
        explanation_id=str(uuid.uuid4()),
        observation_kind=observation_kind,
        observation_id=observation_id,
        case_id=case_id,
        recitation=recite(observation),
        synthesis_sentence=synthesis.sentence if synthesis else None,
        citations=synthesis.citations if synthesis else (),
        evidence_hash=evidence_hash,
        model=MODEL,
        prompt_version=PROMPT_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        synthetic=synthetic,
    )
    store.save_explanation(conn, explanation)
    return explanation
