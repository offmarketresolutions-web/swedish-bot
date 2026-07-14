"""Spike (2026-07-14, docs/plans/2026-07-14-thread-continuity.md): does the
installed google-genai SDK / Vertex project support server-side conversation
continuation (Interactions API `previous_interaction_id`, or SDK `chats`), and
would explicit context caching of conversation history ever pay for itself at
our conversation lengths (2-25 turns, MAX_TOTAL_TURNS=25)?

Verdict: NO on both. See the plan doc for the full measurement table. These
tests pin the evidence so a future SDK/project change that flips either answer
is caught instead of silently re-litigated from vibes.
"""
import pytest

from core.constants import CACHE_MIN_TOKENS

pytestmark = pytest.mark.django_db


def test_worst_case_history_token_count_stays_under_cache_floor():
    """25 turns (the hard ceiling, MAX_TOTAL_TURNS) of realistic Swedish
    customer/assistant exchanges must stay under CACHE_MIN_TOKENS — the whole
    justification for NOT building history caching. If a future accuracy fix
    balloons per-turn text enough to cross the floor, this test is the trip
    wire to revisit the plan's verdict."""
    from core.services import gemini

    sample_turn = (
        "Customer: Min varmvattenberedare läcker vatten från botten och gör "
        "ett konstigt ljud när den startar. "
        "Assistant: Tack för informationen. Kan du berätta vilken modell det "
        "är och hur gammal maskinen är? "
    )
    text = sample_turn * 25
    client, _ = gemini.make_client()
    resp = client.models.count_tokens(model="gemini-2.5-flash", contents=text)
    assert resp.total_tokens < CACHE_MIN_TOKENS, (
        f"25-turn history now costs {resp.total_tokens} tokens, at/above the "
        f"{CACHE_MIN_TOKENS}-token Vertex cache floor — the 'resend is optimal' "
        "verdict in docs/plans/2026-07-14-thread-continuity.md needs revisiting."
    )


@pytest.mark.live
def test_live_interactions_api_unsupported_for_our_models_on_vertex():
    """Confirms the Interactions API (`client.interactions.create`) is reachable
    on this Vertex project/SDK but rejects every model we actually use, with
    'Unsupported model interaction: <model>'. If this ever starts succeeding,
    the SDK/project has gained support and part 1 of the spike verdict flips."""
    from core.services import gemini

    client, _ = gemini.make_client()
    with pytest.raises(Exception) as exc_info:
        client.interactions.create(model="gemini-2.5-flash", input="Say OK.")
    assert "Unsupported model interaction" in str(exc_info.value)
