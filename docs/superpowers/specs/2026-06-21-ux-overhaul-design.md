# Nordland VVS — UX overhaul to familiar, common UI

Status: APPROVED (user: "just do it all" — proceed autonomously). Grounded in a
research+audit pass (support-chat conventions, SaaS-admin conventions, current-UI
gap audit). Goal: make every surface feel like a conventional, familiar web product.

## Principles
- Adopt the patterns users already expect; invent nothing novel.
- Keep the brand (blue #1a74bf, action #d9370c, etc.) and the existing stack
  (Django + Tailwind-CLI + HTMX + Alpine, vanilla-JS widget). No new heavy deps.
- YAGNI: no Cmd-K palette, no django-unfold, no dark mode, no realtime, no
  saved-filters/column-manager, no bulk-select unless a real bulk action exists.

## A. Staff app shell  (templates/dashboard/base.html + partials)
- **Left sidebar** (~240px, fixed, full height): logo top; grouped nav with
  active-state (`aria-current=page`): **Overview**; group "Support" → Sessions,
  Customers; group "Knowledge" → Knowledge Base, Agents; **Playground**; a divider
  then **Django Admin** (opens /admin/). Collapses to an off-canvas drawer below
  `lg` via an Alpine hamburger in the top bar; overlay + body-scroll-lock.
- **Top bar** (sticky, ~56px) in the content area: left = breadcrumb/page title;
  right = "View site" + the user. Skip-link ("Skip to content") + `<main id=main>`.
- **Page-header partial** `_page_header.html`: H1 + optional sub/count on the left,
  a primary-action slot top-right. Used by every page.
- **Toasts**: an Alpine store + a fixed top-right stack (success/error/info,
  auto-dismiss ~4s, `aria-live=polite`), fired from HTMX responses via
  `HX-Trigger: {"toast": {...}}`. A tiny `_toasts.html` + JS in base.
- Semantic button classes (`.btn`, `.btn-primary`, `.btn-secondary`, `.btn-danger`)
  in the compiled CSS for consistency.

## B. Data tables  (session_list.html, customer_list.html + dashboard/views.py)
- Reusable look: card container, sticky header, row hover, zebra optional.
- **Search** box (debounced GET `q=`), **sortable** column headers (GET `sort=` with
  ▲/▼ + `aria-sort`), **pagination** (Django Paginator, replace the `[:200]` slice),
  result count. **Empty state** (icon + heading + one-line guidance + CTA).
- **Mobile**: collapse to a card stack (`data-label` cells) below `md`.
- Views gain `q`/`sort`/`page` handling with a small allowlist of sortable fields.

## C. Forms & feedback
- agent_config / KB upload / note add: success → toast (HX-Trigger) instead of (or
  in addition to) the inline pill; keep `hx-disabled-elt` spinners.
- Long forms (Agent card): a sticky save bar; labels already top-aligned; keep
  fieldset grouping. KB upload: a styled drop-zone affordance (progressive — the
  plain file input still works) + focus the note input after add.

## D. Chat widget  (static/widget/nordland-widget.js) — Intercom conventions
- **Launcher**: real `<button>` (aria-label, aria-expanded), brand-blue circle with
  an inline SVG chat glyph that morphs to ✕ when open; bottom-right, 20px margin.
  Unread badge when the bot replies while minimized.
- **Header**: avatar + "Nordland VVS" + status sub-line ("Svarar oftast inom några
  minuter"); minimize (chevron) + close (✕). Brand background; logo kept.
- **Messages**: user right (brand) / bot left (neutral) with avatar on first of a
  run; grouped; comfortable bubbles; hover/relative timestamps (not per-bubble).
- **Typing**: animated three-dot bubble until streaming text replaces it; static
  under `prefers-reduced-motion`.
- **Composer**: auto-grow `<textarea>` (Enter=send, Shift+Enter=newline), disabled
  send until non-empty, paperclip → file picker (image/pdf) with a remove-able
  thumbnail/filename chip + size/type guard.
- **Persistence**: conversation + open state in sessionStorage; restore on reopen.
- **Mobile**: near-fullscreen panel (safe-area insets), auto-scroll to newest with a
  "jump to latest" affordance if scrolled up.
- **A11y**: panel `role=dialog`/`aria-modal`, transcript `role=log`/`aria-live=polite`,
  focus moves into panel on open and back to launcher on close; honor reduced-motion.
- Keep the existing API + `data-testid` hooks so E2E + tests stay green.

## E. Playground (templates/playground.html)
- Re-skin to the new shell look; scenario buttons get risk styling (danger = red);
  inspector field labels get tooltips explaining match_confidence vs
  specialist_confidence vs state/decision; loading spinner on turns.

## F. Django admin
- Keep last turn's branded theme (it uses Django's native left nav). Add a "← Back to
  dashboard" link. No structural change. (django-unfold noted as a future option.)

## Verification
- 122 mocked tests stay green (+ new tests for table sort/search/paginate + toast
  HX-Trigger). `manage.py check` clean.
- Playwright: screenshot every surface (shell, sessions table w/ search+sort+empty,
  widget open + conversation, playground, admin); E2E widget flow still 14/14;
  boundary battery still 7/7 (chat path logic unchanged).
- Adversarial review of the new shell/tables/widget for correctness + a11y.

## Rollout (parallel where file-disjoint)
1. **Shell first** (base.html + partials + CSS) — foundational; verify pages render.
2. **Parallel**: (a) data tables + views, (b) widget rewrite, (c) playground+toasts.
3. Verify + review.
