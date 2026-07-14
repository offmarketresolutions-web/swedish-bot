"""Shared controlled vocabularies (plan §7 — one enum per concept, everywhere).

Values are stable English codes; display labels localize separately (plan §11).
"""

LANG_CHOICES = [("en", "English"), ("sv", "Svenska")]

# Severity — used by the router output, crm.Session, lead payloads, dashboard.
SEVERITY_URGENT = "urgent"
SEVERITY_NORMAL = "normal"
SEVERITY_SERVICE = "service"
SEVERITY_CHOICES = [
    (SEVERITY_URGENT, "Urgent — safety risk / active property damage"),
    (SEVERITY_NORMAL, "Normal — broken/degraded, no immediate danger"),
    (SEVERITY_SERVICE, "Service — maintenance / advisory / quote"),
]

DOC_KIND_CHOICES = [
    ("manual", "Manual"),
    ("brochure", "Brochure"),
    ("wiring", "Wiring diagram"),
]

# The fixed agent roles (the graph is code; each role's prompt + model is data).
AGENT_ROLE_CHOICES = [
    ("intake", "Intake agent"),
    ("router", "Router agent"),
    ("specialist", "Specialist agent"),
    ("intelligent_intake", "Intelligent intake specialist (unsupported)"),
    ("intelligent_specialist", "Intelligent specialist (serviced category, no manual)"),
    ("heat_pump_specialist", "Heat-pump general specialist (no manual)"),
    ("water_pump_specialist", "Water-pump / well general specialist (no manual)"),
    ("water_filtration_specialist", "Water-filtration general specialist (no manual)"),
    ("summarizer", "Session summarizer"),
    ("safety", "Safety classifier (guardrail backstop)"),
    ("qa", "QA / assessment agent (v2)"),
]

# Orchestrator session states (plan §6).
STATE_INTAKE = "INTAKE"
STATE_ROUTING = "ROUTING"
STATE_SPECIALIST = "SPECIALIST"
STATE_UNSUPPORTED = "UNSUPPORTED_INTAKE"
STATE_ESCALATE = "ESCALATE"
STATE_RESOLVED = "RESOLVED"
