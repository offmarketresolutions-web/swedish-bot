"""Prompt-contract SHAPE tests: the agent JSON keys the backend reads must survive
the write to the typed crm.Session columns.

The specialist prompt declares `extracted_facts.onset` as an enum
(sudden|gradual|always) and `installer` as (nordland|bylunds|nordborr|other), but the
reader (chat.orchestrator._apply_extracted_facts) accepts ANY string up to 200 chars
and drops it straight into the slots. Session.onset is varchar(16),
Session.installer varchar(32), Session.error_code varchar(64), Session.severity
varchar(16) — so an off-contract value from the model blows up flush_to_session with
a DataError and kills the whole escalation turn.
"""
import pytest

from chat import casestate
from chat.casestate import flush_to_session, new_case_state
from chat.models import Conversation
from crm.models import Session

pytestmark = pytest.mark.django_db


def _conv():
    return Conversation.objects.create(case_state=new_case_state())


def test_flush_survives_off_contract_onset_and_installer():
    """Model answers the onset/installer enums in prose (as models do) — the flush
    must clamp, not raise."""
    conv = _conv()
    cs = conv.case_state
    cs["slots"]["onset"] = "sudden, right after the power cut last Tuesday evening"
    cs["slots"]["installer"] = "other — a local firm whose name the customer forgot"
    session = flush_to_session(conv, cs)
    assert len(session.onset) <= 16
    assert len(session.installer) <= 32
    session.refresh_from_db()


def test_flush_survives_off_contract_error_code_and_severity():
    """extracted_facts.error_code is merged raw (no clean_error_code) and the router's
    severity is never enum-checked; both reach short columns."""
    conv = _conv()
    cs = conv.case_state
    cs["slots"]["error_code"] = "E9 " * 40
    cs["severity"] = "extremely urgent — flooding right now"
    cs["decision"] = "solve but please also book a technician visit"
    session = flush_to_session(conv, cs)
    assert len(session.error_code) <= 64
    assert len(session.severity) <= 16
    assert len(session.decision) <= 16
    session.refresh_from_db()


def test_fit_limits_are_sourced_from_the_session_model_not_hardcoded():
    """chat.casestate._LIMITS must be read from Session._meta, not a second
    hand-maintained table that could drift from an actual column's max_length."""
    limits = casestate._limits()
    for name in ("manufacturer", "model", "serial", "error_code", "severity",
                 "decision", "postal_code", "onset", "installer"):
        assert limits[name] == Session._meta.get_field(name).max_length, name


def test_fit_raises_keyerror_on_unknown_column_name():
    """A typo'd column name must fail loudly, not silently skip the clamp."""
    with pytest.raises(KeyError):
        casestate._fit("no_such_column", "value")
