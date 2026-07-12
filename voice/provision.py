"""Everything-as-code Vapi provisioning + the zero-drift reconcile engine (design §4/§7).

Single-tenant: ONE Nordland assistant + its 6 server tools + the inbound phone-number attach. The
``build_*_payload`` builders are the single source of truth for the Vapi JSON shapes — shared with
``dashboard/publish.py`` (one shape, two callers). A re-run with no edits is a proven no-op: the
``VapiObject.last_provision_hash`` sha256 oracle short-circuits with zero Vapi writes.

The assistant system prompt is DERIVED from the web ``specialist`` AgentPrompt (design decision B):
persona/scope/guardrail spine + the voice-delta preamble + the code-owned immutable safety block.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings

from core.services import vapi
from voice import constants as C

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/api/voice/vapi"

ASSISTANT_ROLE = "specialist"  # the web persona the voice prompt derives from
DERIVE_ROLE = ASSISTANT_ROLE


# ── Report shapes ──────────────────────────────────────────────────────────────
@dataclass
class ReconcileResult:
    kind: str
    name: str
    vapi_id: str = ""
    action: str = "nodrift"  # created|patched|nodrift|skipped|error
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class ProvisionReport:
    ok: bool = True
    dry_run: bool = False
    results: list[ReconcileResult] = field(default_factory=list)
    error: str | None = None

    @property
    def created(self) -> int:
        return sum(r.action == "created" for r in self.results)

    @property
    def patched(self) -> int:
        return sum(r.action == "patched" for r in self.results)

    @property
    def nodrift(self) -> int:
        return sum(r.action == "nodrift" for r in self.results)

    @property
    def errors(self) -> int:
        return sum(r.action == "error" for r in self.results)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "dry_run": self.dry_run, "error": self.error,
            "created": self.created, "patched": self.patched,
            "nodrift": self.nodrift, "errors": self.errors,
            "results": [
                {"kind": r.kind, "name": r.name, "id": r.vapi_id, "action": r.action,
                 "warnings": r.warnings, "error": r.error}
                for r in self.results
            ],
        }


# ── payload builders (the single source of truth) ──────────────────────────────
def _server_block() -> dict:
    base = getattr(settings, "PUBLIC_BASE_URL", "").rstrip("/")
    return {"url": f"{base}{WEBHOOK_PATH}", "secret": getattr(settings, "VAPI_WEBHOOK_SECRET", "")}


def _voice_block() -> dict:
    block = dict(C.ELEVENLABS_VOICE)
    override = getattr(settings, "VAPI_VOICE_ID", "") or ""
    if override:
        block["voiceId"] = override
    return block


def compose_system_prompt() -> str:
    """The voice system prompt: voice-delta preamble + the web specialist persona + immutable
    safety. Derived from the live ``AgentPrompt(role='specialist')`` row (design decision B)."""
    from kb.models import AgentPrompt

    row = AgentPrompt.objects.filter(role=DERIVE_ROLE, is_active=True).first()
    persona = (row.body if row else "").strip()
    return f"{C.VOICE_PREAMBLE}{persona}{C.IMMUTABLE_SAFETY}"


def build_tool_payload(name: str) -> dict:
    spec = C.TOOL_SPECS[name]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": spec["description"],
            "parameters": spec["parameters"],
        },
        "server": _server_block(),
        "async": spec.get("async", False),
    }


def _tool_ids(warnings: list[str]) -> tuple[list[str], bool]:
    from voice.models import VapiObject

    ids: list[str] = []
    ok = True
    for name in C.TOOL_SPECS:
        rec = VapiObject.objects.filter(kind="tool", name=name).first()
        if rec and rec.vapi_id:
            ids.append(rec.vapi_id)
        else:
            warnings.append(f"tool not provisioned: {name}")
            ok = False
    return ids, ok


def build_assistant_payload(name: str | None = None) -> tuple[dict, list[str]]:
    """The full ``POST/PATCH /assistant`` body. Returns ``(payload, warnings)``."""
    warnings: list[str] = []
    tool_ids, _ok = _tool_ids(warnings)
    from kb.models import AgentPrompt

    if not AgentPrompt.objects.filter(role=DERIVE_ROLE, is_active=True).exists():
        warnings.append(f"no AgentPrompt(role={DERIVE_ROLE}) — system prompt spine is empty")

    model = {
        "provider": C.ASSISTANT_PROVIDER,
        "model": getattr(settings, "VAPI_ASSISTANT_MODEL", "") or C.ASSISTANT_MODEL,
        "temperature": C.ASSISTANT_TEMPERATURE,
        "maxTokens": C.ASSISTANT_MAX_TOKENS,
        "messages": [{"role": "system", "content": compose_system_prompt()}],
        "toolIds": tool_ids,
    }
    payload = {
        "name": name or C.ASSISTANT_NAME,
        "model": model,
        "voice": _voice_block(),
        "transcriber": dict(C.DEEPGRAM_TRANSCRIBER),
        "server": _server_block(),
        "serverMessages": list(C.SERVER_MESSAGES),
        "firstMessageMode": "assistant-speaks-first",
        "firstMessage": C.ENTRY_FIRST_MESSAGE,
    }
    return payload, warnings


# ── zero-drift reconcile ────────────────────────────────────────────────────────
def payload_hash(payload: dict) -> str:
    """Stable sha256 of the redacted canonical JSON — the zero-drift oracle."""
    canonical = json.dumps(vapi.redact_payload(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _reconcile(kind: str, name: str, payload: dict, *,
               find_by_name: Callable[[str], dict | None],
               get_by_id: Callable[[str], dict],
               create: Callable[[dict], dict],
               patch: Callable[[str, dict], dict],
               warnings: list[str] | None = None) -> ReconcileResult:
    from voice.models import VapiObject

    warnings = warnings or []
    h = payload_hash(payload)
    try:
        rec = VapiObject.objects.filter(kind=kind, name=name).first()
        obj = None
        if rec and rec.vapi_id:
            try:
                obj = get_by_id(rec.vapi_id)
            except vapi.VapiError as exc:
                if exc.status == 404:
                    obj = None
                else:
                    raise
        if obj is None:
            obj = find_by_name(name)

        if obj and rec and rec.last_provision_hash == h:
            return ReconcileResult(kind, name, obj.get("id", ""), action="nodrift", warnings=warnings)

        if obj is None:
            obj = create(payload)
            action = "created"
        else:
            obj = patch(obj["id"], payload)
            action = "patched"

        VapiObject.objects.update_or_create(
            kind=kind, name=name,
            defaults={"vapi_id": obj.get("id", ""), "last_provision_hash": h},
        )
        return ReconcileResult(kind, name, obj.get("id", ""), action=action, warnings=warnings)
    except vapi.VapiError as exc:
        return ReconcileResult(kind, name, action="error", error=str(exc), warnings=warnings)


# ── deploy steps ─────────────────────────────────────────────────────────────────
def ensure_tool(name: str) -> ReconcileResult:
    return _reconcile("tool", name, build_tool_payload(name),
                      find_by_name=vapi.find_tool_by_name, get_by_id=vapi.get_tool,
                      create=vapi.create_tool, patch=vapi.patch_tool)


def ensure_assistant() -> ReconcileResult:
    payload, warnings = build_assistant_payload()
    if any(w.startswith("tool not provisioned") for w in warnings):
        return ReconcileResult("assistant", C.ASSISTANT_NAME, action="skipped", warnings=warnings)
    return _reconcile("assistant", C.ASSISTANT_NAME, payload,
                      find_by_name=vapi.find_assistant_by_name, get_by_id=vapi.get_assistant,
                      create=vapi.create_assistant, patch=vapi.patch_assistant, warnings=warnings)


def ensure_phone_number() -> ReconcileResult:
    from voice.models import VapiObject

    number_id = getattr(settings, "VAPI_PHONE_NUMBER_ID", "") or ""
    if not number_id:
        return ReconcileResult("phone_number", "Nordland inbound", action="skipped",
                               warnings=["VAPI_PHONE_NUMBER_ID not configured"])
    asst = VapiObject.objects.filter(kind="assistant", name=C.ASSISTANT_NAME).first()
    if not (asst and asst.vapi_id):
        return ReconcileResult("phone_number", "Nordland inbound", action="skipped",
                               warnings=["assistant not provisioned yet"])
    payload = {"assistantId": asst.vapi_id, "name": "Nordland inbound", "server": _server_block()}
    return _reconcile("phone_number", number_id, payload,
                      find_by_name=lambda _n: vapi.find_phone_number(number_id),
                      get_by_id=vapi.get_phone_number,
                      create=lambda _b: (_ for _ in ()).throw(
                          vapi.VapiError("phone numbers are owner-provisioned; cannot create")),
                      patch=vapi.patch_phone_number)


def provision_all(*, dry_run: bool = False) -> ProvisionReport:
    """Stand up the Vapi stack from DB/env; a re-run with no edits is a proven no-op.
    Order: tools → assistant → phone. Auto-engages dry-run when VAPI_PRIVATE_KEY is unset."""
    if not vapi.configured():
        dry_run = True
    vapi.set_dry_run(dry_run)

    report = ProvisionReport(dry_run=dry_run)
    if not dry_run:
        auth = vapi.auth_ok()
        if not auth["ok"]:
            report.ok = False
            report.error = auth["error"] or "VAPI_PRIVATE_KEY not configured"
            return report

    for name in C.TOOL_SPECS:
        report.results.append(ensure_tool(name))
    report.results.append(ensure_assistant())
    report.results.append(ensure_phone_number())
    report.ok = report.errors == 0
    return report
