# Prefill snippet — install on the real nordlandvvs.se form (plan S6/D2)

This is a follow-up for the owner once the bot is live and the widget hands off
to the real service-request form. It has three parts: a chat-side chip URL, a
signed token endpoint, and a ~40-line JS snippet that fills the real form.

## 1. What ships this sprint (demo only, nothing to install yet)
- `/api/prefill/<token>` — read-only JSON of what the bot already captured for a
  session (see `chat/prefill.py` + `chat/views.py::prefill`).
- `static/prefill/nordland-prefill.js` — the snippet itself.
- `templates/demo_form.html` at `/demo/form` — a replica of the real form, wired
  up to prove the whole flow end-to-end before touching the live site.

## 2. When you're ready to install on the real WordPress/Bricks form

1. **Copy the script tag.** Paste this near the end of the form's `<body>` (Bricks:
   the page's "Custom code / footer scripts" area, or a Code element right after
   the form):
   ```html
   <script src="https://<your-django-host>/static/prefill/nordland-prefill.js?v=1" defer></script>
   ```
   Bump the `?v=` number whenever you update the snippet, so browsers don't serve
   a stale cached copy.

2. **Update `FIELD_MAP` — the only edit you'll ever need.** Open
   `static/prefill/nordland-prefill.js` and change the CSS selectors on the left
   to match the real Bricks form's field names/IDs (right-click a field → Inspect
   to find its `name` or `id`). The dotted paths on the right (`contact.name`,
   `technical.brand`, etc.) already match the `/api/prefill/<token>` response
   shape — don't change those unless the API response shape changes too.

3. **Set `PREFILL_ALLOWED_ORIGIN`.** The endpoint is same-origin on the Django
   demo, but the real form lives on a different origin (WordPress). Set the env
   var on the Django host so the browser is allowed to fetch cross-origin:
   ```
   PREFILL_ALLOWED_ORIGIN=https://www.nordlandvvs.se
   ```
   (This is already the default — only change it if the real domain differs.)

4. **How the token gets into the URL.** The chat widget's chips (S6) point at a
   `FormButton` URL with `?nl_case=<token>` appended by
   `chat.prefill.build_form_url(base_url, session)` — this happens automatically
   once a `FormButton` row exists for the category (Dashboard → Settings →
   Website & forms). No action needed here beyond configuring those 4 URLs.

5. **Token lifetime.** 30 minutes from issue (`chat/prefill.py::PREFILL_MAX_AGE`).
   After that the endpoint 404s and the snippet just leaves the form blank —
   nothing breaks, the customer just types it in themselves.

## 3. What's intentionally NOT captured yet
`alarm_text` is not currently persisted as its own `Session` field (only
`category`, `problem_category.label`, `manufacturer`, `model`, `error_code`,
`postal_code`, `onset` are). The `/api/prefill` response includes an
`alarm_text` key for forward-compatibility but it is always `null` today.
