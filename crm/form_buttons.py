"""Website form-button chip selection (plan S6/D2 — conversation side).

The bot never invents URLs: a form chip is built ONLY from an active
crm.FormButton row picked by the case's category (falling back to the
quote_request row). The service-area gate wins — no chip is offered once a case
has resolved to outside_area (after the installer override).
"""
from __future__ import annotations

FAMILIES = {"heat_pump", "water_pump_well", "water_filtration"}


def _family_slug(cs: dict) -> str | None:
    """Resolve the case's category/subtype leaf to a top-level serviced family slug
    (heat_pump / water_pump_well / water_filtration), or None."""
    from kb.models import Category

    slots = cs.get("slots", {})
    for slug in (slots.get("category"), slots.get("subtype")):
        if not slug:
            continue
        if slug in FAMILIES:
            return slug
        c = Category.objects.filter(slug=slug).select_related("parent").first()
        if c:
            if c.slug in FAMILIES:
                return c.slug
            if c.parent and c.parent.slug in FAMILIES:
                return c.parent.slug
    return None


def form_button_for(cs: dict):
    """Return the active FormButton for this case (category match, else the
    quote_request fallback row), or None. Honors the service-area gate: no button
    once the case resolved to outside_area."""
    from crm.models import FormButton

    if cs.get("service_area") == "outside_area":
        return None
    fam = _family_slug(cs)
    btn = FormButton.objects.filter(category_slug=fam, is_active=True).first() if fam else None
    return btn or FormButton.objects.filter(category_slug="quote_request", is_active=True).first()


def form_chip_for(cs: dict) -> dict | None:
    """Build the widget chip for the active FormButton, or None. Shape:
    {"value": "open_form", "label": <button label>, "url": <button url>}."""
    btn = form_button_for(cs)
    if btn is None:
        return None
    # TODO(merge): token added at merge via chat.prefill.build_form_url(btn.url, session)
    # (S6 sibling scope — absent in this worktree; emit the plain URL for now).
    return {"value": "open_form", "label": btn.label, "url": btn.url}
