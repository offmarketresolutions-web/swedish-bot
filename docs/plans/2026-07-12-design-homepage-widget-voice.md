# Design: Nordland VVS Homepage Clone + Widget Voice Mode (ElevenLabs) + Photo Upload

Date: 2026-07-12. Planning only — no source code touched. Companion to
`docs/plans/2026-07-12-audit-current-state.md` (primary source of truth on the existing pipeline)
and `docs/plans/2026-07-12-audit-budtender-voice-reuse.md` (Vapi phone channel — **out of scope
here**, referenced only where a pattern is directly reusable).

Owner's hard requirement, restated because it drives every decision below: **voice mode must be a
different interface onto the SAME backend brain** — `chat/orchestrator.py`'s FSM, `kb/` content,
`chat/guardrails.py`, chip logic, and escalation — not a second bot with its own prompts or its own
notion of state.

---

## 1. Homepage clone

### 1.1 Approach

Add a new Django template + view, served by the existing app — **not** a standalone static site.
Reasons: (a) it needs to embed the real widget script tag pointed at this same backend, so serving it
from the same origin avoids a CORS round-trip and lets us demo "it's really live" convincingly; (b)
`templates/widget_demo.html` + `core/views.py::widget_demo` already exist as the pattern to extend —
this is additive, not a new subsystem; (c) it stays inside the same deploy (`docker-compose.prod.yaml`
→ Caddy → gunicorn), so no second hosting story, no second TLS cert, no second CI/CD path.

Concretely:
- New template `templates/homepage_demo.html` (Nordland-styled homepage shell, static site chrome
  only — no server-rendered dynamic content needed, it's a demo).
- New view `core/views.py::homepage_demo` + URL `core/urls.py` route, e.g. `/demo/homepage` (keep
  `/` and `/widget-demo` exactly as they are — this is additive, not a replacement, since
  `widget_demo.html` is already used as the "simulated WordPress site" reference and other docs may
  point at it).
- Static assets (any hero/service imagery, logo) go under `static/homepage/` — new directory,
  mirrors the existing `static/widget/` and `static/brand/` layout.
- The existing widget bubble embeds via the exact same script tag as today (§1.4) — this template
  does not touch `nordland-widget.js` at all for the chat-mode baseline; voice mode changes (§3) are
  additive to that same file.

### 1.2 Fidelity level

**Structure + brand, not pixel-perfect.** Goal is "recognizably Nordland VVS, good enough to hand a
client and say 'here's what it'll look like live on your site,'" not a scrape/clone of their real
HTML/CSS/JS. Concretely:
- Match: page structure (hero → services grid → regional-coverage blurb → water-test callout → CTA
  band → footer), Swedish copy tone (short, confident, "totalentreprenad" framing), nav labels,
  brand blue (`#1a74bf` / dark `#0f4570` — already the color pair baked into
  `templates/widget_demo.html` and the widget's own `BLUE`/`BLUE_DARK` constants, so this is free
  consistency, not a new choice).
- Do NOT: copy the real site's actual photography, copy exact CSS/markup byte-for-byte, or claim this
  is "the real site" anywhere in the demo chrome. Use placeholder imagery (royalty-free stock —
  heat-pump/plumbing-technician photography, e.g. from an already-licensed stock source the agency
  uses, or simple CSS-illustrated icons/gradients if no licensed stock is on hand) instead of
  downloading `nordlandvvs.se`'s real images. This avoids any copyright exposure and keeps the demo
  honestly labeled as a demo.
- A small "Demo — widget preview" badge/footer note is worth keeping (as `widget_demo.html` already
  implicitly is, being served at a `3dpresence.com` subdomain, not `nordlandvvs.se`) so nobody mistakes
  it for the production site.

### 1.3 Inventory of the real homepage (verified via fetch of `https://www.nordlandvvs.se`, 2026-07-12)

Page structure top to bottom, from the actual rendered content (Bricks-builder WordPress site):

1. **Hero** — H1 *"Din auktoriserade värmepumpsinstallatör"* (Your authorized heat pump installer),
   H3 subhead *"Din helhetsleverantör av VVS"* (Your full-service VVS supplier), body copy: *"Nordland
   VVS är ett komplett företag för installation av värme och vatten. Oavsett om du önskar uppdatera
   ditt värmesystem, borra efter vatten eller installera ett filter så är vi rätt partner för dig."*
   Two CTA buttons, both pointing at `/offert/`: **"Gratis offert"** (Free quote) and **"Boka service"**
   (Book service). Full-bleed hero photo (VVS/plumbing work).
2. **Regional coverage block** — H2/H3 *"Installation av värmepumpar och rörarbeten"* → *"Helhetslösningar
   i Kramfors, Härnösand, Sundsvall, Gävle och Älvkarleby"* — explains the totalentreprenad
   (turn-key/single-vendor) value prop: "Vi är en auktoriserad återförsäljare och installatör för IVT's
   heltäckande program av värmepumpar inom bergvärme, jordvärme, luft/vatten, luft/luft och frånluft."
   CTA: **"Se våra tjänster"** → `/vara-tjanster/`.
3. **"Specialister på VVS-installationer" — 3-up service card grid**, each card links out:
   - **Värmepumpar** (Heat pumps) → `/varmepump/` — "Vi är en auktoriserad återförsäljare och
     installatör för IVT's heltäckande program av värmepumpar." CTA: "Läs mer om värmepumpar".
   - **Vattenpumpar** (Water pumps) → `/vattenpump/`.
   - **Vattenbrunnar** (Water wells) → `/vattenpump/` (shares the water-pump page in the current
     site IA).
4. **"En unik lösning inom VVS"** — value-prop block: "Vi erbjuder dig allt från en enda källa, t.ex.
   luftkonditionering, ventilation, uppvärmning och VVS." CTA: **"Kontakta oss"** → `/kontakta-oss/`.
5. **Vattenprov (water test) callout** — "Allt börjar med en vattenanalys! Om vattnet ändrar lukt,
   smak eller färg är en vattenanalys på sin plats." Two CTAs: **"Gratis offert"** (`/offert/`) and
   **"Se alla våra tjänster"** (`/vara-tjanster/`).
6. Footer — not fully recoverable from the markdown-converted fetch (JS-rendered / below the crawl
   depth reached); **do not fabricate** a fake address/phone number for the clone. Use a clearly
   placeholder contact block (e.g. "Kontakt: se nordlandvvs.se" or blanked fields) rather than
   inventing real-looking Nordland contact details.

Site IA confirmed from internal links: `/offert/` (quote form), `/vara-tjanster/` (all services),
`/varmepump/`, `/vattenpump/`, `/vattenprov-vattenanalys/`, `/kontakta-oss/`.

**Brand color**: not independently re-verified from raw CSS (the fetch tool returns markdown, not
computed styles) — but `#1a74bf` / `#0f4570` is already what this project's own demo page and widget
use as "the Nordland blue," which is the pragmatic source of truth here since matching the *bot's*
brand chrome to the homepage chrome is the actual goal (not re-deriving it from scratch). If exact hex
matching matters before a client-facing demo, do one quick manual color-pick from a live screenshot of
`nordlandvvs.se` before shipping — flagged as an open question in §9.

Typography/imagery: system-UI-style sans-serif headings, warm documentary-style trade photography
(technicians on site, heat pump units), generous whitespace, rounded pill-shaped CTA buttons — all
already the visual language `widget_demo.html`'s inline CSS approximates (`border-radius:999px` pill
buttons, `--nl`/`--nl-d` variables). The homepage clone should extend that same small CSS vocabulary
rather than invent a new one.

### 1.4 Embed snippet

Unchanged from the current widget contract (`static/widget/nordland-widget.js` derives its own API
origin from `document.currentScript.src`), so the demo page embeds it exactly the way `DEPLOY.md`
documents for the real WordPress site:

```html
<script src="https://nordland.3dpresence.com/static/widget/nordland-widget.js"
        data-lang="sv" defer></script>
```

Served same-origin from this Django app instead (`{% static 'widget/nordland-widget.js' %}`), no
`data-open` this time (the real homepage doesn't auto-open chat on load — that's specific to the
dedicated chat-landing demo page). Voice mode requires no new script tag or attribute — it's a UI
mode inside the same widget panel (§3), not a separate embed.

### 1.5 CORS / `WIDGET_ALLOWED_ORIGINS` change

None needed for the homepage-clone-on-same-origin case, since same-origin requests aren't subject to
the CORS allowlist at all (`core/middleware.py::WidgetCorsMiddleware` only matters for cross-origin
`fetch()` calls). `WIDGET_ALLOWED_ORIGINS` only needs a new entry if the clone is ever served from a
**different** origin than the Django app (e.g. a separate static host, or a staging subdomain) — in
that case add the clone's origin to the env var (comma-separated list, `config/settings.py:32`), same
mechanism already used for `nordlandvvs.se`/`www.nordlandvvs.se`.

### 1.6 Doubling as the client demo

This is the natural "sales demo" artifact: point the client at `https://nordland.3dpresence.com/demo/
homepage` (or whatever route is chosen) and they see something that looks like their own site with a
working, on-brand support widget already embedded — a much stronger pitch than the current bare
`widget_demo.html` "simulated WordPress site" placeholder. No additional infra: it's one more Django
template + view in an app that's already deployed.

---

## 2. Voice mode architecture — the core decision

### 2.1 What ElevenLabs actually offers (verified 2026-07-12)

Two materially different products, confirmed via ElevenLabs' own docs:

**ElevenAgents (the "Agents Platform")** — a hosted, turnkey conversational agent. Per
`elevenlabs.io/docs/eleven-agents/overview`, it "coordinates 4 core components: (1) a fine-tuned
Speech-to-Text (ASR) model, (2) your choice of language model or a custom LLM, (3) a low-latency TTS
model across 5k+ voices and 70+ languages, (4) a proprietary turn-taking model that handles
conversation timing." Deployment options include a pre-built **`<elevenlabs-convai>` web widget**
(script-tag embed, near-zero code), a **React/JS/Swift/Kotlin SDK**, and a raw **WebSocket API** for
custom implementations. It supports:
- **Custom LLM** (`docs/eleven-agents/customization/llm/custom-llm`) — point the agent at your own
  OpenAI-compatible endpoint (`/v1/chat/completions` or `/v1/responses` shape) instead of ElevenLabs'
  built-in model choices. This is the integration seam that *could* let our FSM drive the
  conversation content while ElevenLabs still owns ASR/TTS/turn-taking.
- **Webhook (server) tools** (`docs/eleven-agents/customization/tools/server-tools`) — the agent can
  call out to an HTTPS endpoint mid-conversation (Bearer/Basic/OAuth2/custom-header auth supported),
  get a result back, and speak it. This is the other integration seam — the FSM lives behind a tool
  call instead of behind the whole LLM slot.

**Raw ElevenAPI (TTS/STT primitives)** — no agent runtime at all, just:
- **Text-to-Speech streaming** (`/v1/text-to-speech/{voice_id}/stream`, plus a lower-latency
  WebSocket variant) — send text, get back streamed audio (`mp3_*`/`pcm_*`/`ulaw_*` formats), tunable
  latency-optimization levels 0–4.
- **Scribe** (Speech-to-Text) — two variants: **Scribe v2 (batch)**, best-in-class accuracy across 99
  languages; **Scribe v2 Realtime**, ~150ms-latency streaming STT across 30 languages, 93.5% accuracy.
  **Swedish is explicitly "Excellent Accuracy" (≤5% WER)** per ElevenLabs' own language support page —
  3.1% WER on the FLEURS benchmark, beating both Gemini and Whisper on Swedish in ElevenLabs' own
  comparison. This directly answers the "Swedish quality" evaluation criterion below: Scribe is a safe
  choice for Swedish STT specifically.

Pricing (verified via ElevenLabs' pricing/help pages, 2026-07-12): ElevenAgents call minutes run
$0.08/min beyond plan-included minutes (burst $0.16/min over concurrency limits), **LLM and telephony
costs are billed separately on top** — i.e. even on the Agents Platform, a custom-LLM setup still pays
LLM inference cost independently of the per-minute agent fee. Plan tiers bundle minutes + concurrency
(Free 15min/4 concurrent → Business 12,375min/40 concurrent).

### 2.2 Option A — ElevenLabs Agents Platform (hosted agent + server-tool bridge to our backend)

**Shape**: Provision one ElevenAgent (Swedish + English voice, e.g. via the dashboard control-plane
pattern already proven in the Vapi audit — `provision.py`'s "everything-as-code, zero-drift reconcile"
is a directly reusable *pattern*, not code, since it's Vapi-API-shaped not ElevenLabs-API-shaped).
The agent's system prompt is deliberately thin ("you are a pass-through voice interface; for every
user utterance, call the `nordland_turn` tool with the transcript and speak back exactly what it
returns — do not improvise answers yourself"). Every user turn becomes one **server-tool call** back
into Django (`POST /api/voice/turn` or similar), which internally calls the *exact same*
`chat.orchestrator.process_turn()` used by text chat, and returns `{message, chips}` as the tool
result for ElevenLabs to speak.

**Pros**: ElevenLabs owns ASR + turn-taking + interruption/barge-in + TTS streaming — genuinely hard
real-time-audio engineering we get for free. Swedish STT (Scribe) is already proven good. One widget
SDK (`<elevenlabs-convai>` or the JS/React SDK) handles mic capture, WebRTC/WebSocket plumbing,
reconnects.

**Cons — and these are why this is not the primary recommendation**:
- **Fighting the platform to keep it "pass-through."** ElevenAgents is designed to *be* the
  conversational brain (its own LLM turn, its own tool-choice reasoning, its own knowledge base RAG).
  Forcing it into "always call exactly one tool, never answer directly" works but is an unnatural
  shape for the platform and adds a full extra LLM hop (ElevenLabs' LLM decides "call the tool" →
  Django's own Gemini-driven FSM does the real work → ElevenLabs' LLM/TTS speaks the tool result) —
  latency and cost stack on top of, not instead of, the existing pipeline.
- **Custom LLM is the "more correct" seam but is heavier to stand up.** Routing ElevenLabs' *model*
  slot itself at our `chat/orchestrator.py` (via the custom-LLM OpenAI-compatible endpoint) is closer
  to "one clean brain" than the tool-call-pass-through hack, but it requires wrapping the entire FSM
  behind a fake `/v1/chat/completions` endpoint, translating multi-turn FSM state into OpenAI chat
  message history on every call, and reconciling ElevenLabs' streaming-token expectations against our
  orchestrator's "compute the full reply, then return" design (per the audit, `process_turn()` has no
  real token streaming today — §2.3 covers this constraint in more depth). This is a nontrivial adapter
  layer, not a config change.
- **WSGI/gunicorn mismatch.** Whichever seam is used, ElevenLabs will hold open either a webhook HTTP
  request or a synchronous-LLM-style request against our backend per turn. Per the audit's constraint
  #1, the current deploy (`gunicorn config.wsgi:application --workers 3`) already ties up one worker
  thread per open SSE chat connection; adding voice-turn traffic on the same three workers needs either
  more workers or a move toward async — solvable, but real ops work, not zero-cost.
- **GDPR/EU-residency posture needs an explicit answer.** The audit flags Vertex AI is fail-closed to
  `europe-*` region in prod. ElevenLabs' infrastructure region/data-residency posture for Agents needs
  the same explicit check before this ships (not assumed compliant by default) — see §7.

### 2.3 Option B — "Bring-your-own-brain": browser STT/mic capture + existing `/api/chat` pipeline + ElevenLabs TTS streamed back (RECOMMENDED)

**Shape**: The widget's voice mode does three things, all client-driven, none requiring a new hosted
agent:
1. **Capture speech → text.** Two sub-choices, in order of recommendation:
   - **(B1, recommended) ElevenLabs Scribe v2 Realtime** via a short-lived signed session (mint a
     scoped token server-side per §4, browser opens a WebSocket directly to ElevenLabs' STT endpoint,
     streams mic audio, gets back a live transcript). Chosen for the verified Swedish accuracy
     advantage (§2.1) over the browser-native alternative.
   - **(B2, fallback) Web Speech API (`webkitSpeechRecognition`)** — zero backend involvement, free,
     built into Chrome/Edge/Safari, has a `lang="sv-SE"` mode. Materially worse Swedish accuracy than
     Scribe and inconsistent cross-browser support (notably weak/absent on Firefox), but is the
     zero-infra fallback if Scribe integration proves too heavy for a first ship, or as a client-side
     circuit-breaker if the ElevenLabs STT session fails to establish.
2. **Send the transcribed text through the existing, completely unmodified turn API** —
   `POST /api/chat/<uuid:public_id>/message` with `{"message": "<transcript>"}`, exactly the JSON path
   the text-chat widget already uses today. **This is the entire point of Option B**: the FSM, the
   guardrails, the chip logic, the escalation flow, the DB-editable prompts — all of it runs completely
   unaware that the input arrived by voice. Zero orchestrator changes.
3. **Speak the reply.** Once the SSE stream's final `{"type":"message", "message": "..."}` frame
   arrives, send that text to **ElevenLabs TTS streaming** (`/v1/text-to-speech/{voice_id}/stream` or
   the WebSocket variant for lower latency) via a thin backend proxy (§4 — never expose the ElevenLabs
   API key to the browser), stream the returned audio back to the browser, and play it.

**Pros** (evaluated against the four criteria the owner cares about):
- **Reuses the FSM/guardrails 100% unchanged** — this is not a "mostly" or "with adapters," it's the
  literal same HTTP call the chat widget makes today. Zero risk of behavioral drift between chat mode
  and voice mode; a single dashboard-edited prompt change updates both instantly, same as today.
- **Latency**: worse than a fully-native voice pipeline (this is the honest tradeoff — see §8's
  budget), because it's "record → transcribe → wait for full text reply → synthesize → play," not a
  token-streamed, duplex, barge-in-native pipeline. But it is *predictable* latency built from
  well-understood pieces, not a new unknown.
- **Cost**: pay ElevenLabs for STT-minutes and TTS-characters only, no $0.08/min "agent" fee layered
  on top, no second LLM hop. Cheaper per-turn than Option A for a bot that's already paying for Gemini
  calls per turn regardless of the voice interface.
- **Complexity on a WSGI backend**: the *only* new backend surface is a thin TTS-proxy endpoint and a
  short-lived STT-token-mint endpoint (§4) — both request/response, not long-lived duplex connections
  held open by Django itself (the actual audio streaming happens directly between the browser and
  ElevenLabs, browser↔Django only for token minting and text/reply exchange, which is exactly what the
  chat widget already does). This is the lowest-risk fit for the existing `gunicorn --workers 3` WSGI
  deploy of the three options considered.

**Cons**: no native barge-in/interruption during bot speech (must be built in the widget: stop
playback + cancel the in-flight STT/turn cycle on new mic activity — doable, but DIY, not "comes free"
the way it does on ElevenAgents' proprietary turn-taking model, §3.3). Also no live token-by-token TTS
of a streaming LLM reply (the orchestrator doesn't stream text today per the audit — voice mode
inherits that "wait for the full reply, then speak" property rather than fixing it, which Option A
would also inherit if a custom-LLM seam were used).

### 2.4 Recommendation

**Ship Option B (bring-your-own-brain: browser/Scribe STT + existing `/api/chat` + ElevenLabs TTS
proxy) as the primary architecture.** It is the only option that reuses the FSM with zero risk of
behavioral drift, fits the current WSGI deploy with the smallest new backend surface, and is cheapest
per-turn. Keep **Option A (ElevenLabs Agents Platform via a thin pass-through tool)** as the documented
fallback/runner-up — revisit it specifically if: (a) DIY barge-in/turn-taking in the widget proves too
janky in practice, (b) the client wants a phone-quality "always-listening" experience closer to what
ElevenAgents' turn-taking model gives for free, or (c) this eventually converges with the Vapi phone
channel (a separate, not-yet-built surface per the companion audit) and a single hosted-agent platform
for both phone and web voice becomes attractive to avoid maintaining two voice stacks.

---

## 3. Widget changes

### 3.1 Mode toggle

Add a two-state segmented control in the widget header (next to the existing language selector),
`Chat | Voice` — pure client-side UI state, no new session concept. Switching to Voice mode does
**not** open a new `Conversation` — it's the same `sessionId`/`public_id` already open, same
`STORE_KEY` transcript. A user can free-switch mid-conversation: type a message in Chat mode, then
tap Voice and speak the next turn into the same thread. This matters because it means voice mode is
additive UI on the existing turn loop, not a parallel state machine.

### 3.2 UI states

Four states, rendered as a status indicator + mic button visual (replacing/augmenting the composer
row when Voice mode is active):
1. **Idle** — mic button visible, ready to tap-to-talk (or hold-to-talk, per §3.4). Status text: the
   existing `"Usually replies within a few minutes"` line swaps to something like `"Tap to speak"`.
2. **Listening** — mic actively capturing + streaming to Scribe, live partial-transcript text shown
   above the mic button (if Scribe's realtime partials are used) so the user gets visual confirmation
   they're being heard — critical trust signal for voice UIs. Waveform/pulse animation on the mic
   button.
3. **Thinking** — after the user stops speaking (silence-detected or the user releases hold-to-talk),
   the transcript is finalized and sent to `/api/chat/.../message`; reuse the existing typing-dots
   bubble animation already in the widget for this state (no new visual language needed).
4. **Speaking** — TTS audio is playing; mic button shows a "stop/interrupt" affordance instead of the
   record icon (tap to barge-in, §3.3). A simple audio-level indicator (even a static "speaking" icon
   is fine for v1) communicates "the bot is talking now."

Any state can fall back to an **Error** sub-state (mic permission denied, STT/TTS session failed,
network drop) — always with a one-tap "Switch to chat" affordance that flips the mode toggle back to
Chat without losing the conversation (§3.6).

### 3.3 Barge-in / interrupt behavior

Since Option B has no proprietary turn-taking model, barge-in must be built explicitly:
- While **Speaking**, any new mic activity above a simple volume threshold (or an explicit tap on the
  mic/stop button) immediately: stops TTS audio playback (`<audio>.pause()` / cancel the fetch
  stream), cancels any in-flight TTS request, and transitions straight to **Listening**.
- While **Thinking** (waiting on the `/api/chat` SSE response), a new tap on the mic is treated as
  "cancel this turn" — abort the in-flight `fetch`, discard the pending assistant reply, return to
  **Idle**. (The turn was already durably persisted as a user `Message` server-side regardless — no
  data loss, just no spoken reply for that abandoned turn; this matches how the FSM already handles
  reply generation being independent of transport.)
- No barge-in needed *during* Listening itself — the user is already the one talking.

### 3.4 Mic permission & capture UX

- Request `getUserMedia({audio: true})` **only on first tap of the Voice toggle**, not on widget load
  — avoids a jarring permission prompt before the user has even opened the chat.
- On denial: fall back to Chat mode automatically, show a small inline notice ("Voice needs microphone
  access — you can still type below") rather than a dead Voice tab.
- Tap-to-talk (tap once to start, tap again or auto-silence-detect to stop) is the recommended
  interaction over hold-to-talk for a support-chat context — mirrors how voice-memo UIs on messaging
  apps generally work and avoids "did I let go too early" anxiety mid-sentence. Silence-based
  auto-stop (e.g. ~1.2s of quiet after speech) as a convenience on top, always overridable by an
  explicit tap-to-stop.

### 3.5 Chips and buttons in voice mode

Chips (quick-reply buttons from `chips_for()`, per the audit) **stay visually present and tappable**
in voice mode — do not hide them. Additionally, **read them aloud** as part of the spoken reply: when
the turn response includes chips, append a short spoken enumeration after the main message (e.g. "Do
you mean IVT, Bosch, or something else?" — ideally the specialist/intake prompts already phrase
follow-up questions this way per the existing i18n templates in `chat/i18n.py`, so this may need no
prompt change at all, just confirming the templated question text reads naturally as speech before
the chip list). Tapping a chip works exactly as in chat mode (fills `current_slot`, triggers the next
turn) — voice mode doesn't require the user to *say* the chip label, though saying it in free text
should also work since intake's chip-exact-match / LLM extraction (`intake.extract_answer`) already
handles free-text slot-filling today.

### 3.6 Transcript visibility

Keep the same scrolling bubble transcript visible at all times, including in Voice mode — every
spoken turn (both the user's finalized transcript and the bot's spoken reply text) appends to the
transcript exactly like a typed message would. This gives: (a) a fallback if audio playback fails —
the user can still read the reply, (b) continuity when switching Chat↔Voice mid-conversation, (c) an
accessibility win (deaf/HoH users or noisy environments can follow along visually even while "in"
voice mode).

### 3.7 Error / fallback to chat

Any of: mic permission denied, STT WebSocket fails to connect or drops mid-session, TTS proxy request
fails or times out, browser lacks `getUserMedia`/WebSocket support at all → the widget silently
degrades to Chat mode (toggle auto-switches, brief inline notice, the in-progress conversation and
its `public_id` session are completely unaffected since they're transport-agnostic). This is the same
philosophy the existing widget already applies to image-upload failures (`{"type":"notice", "message":
"Image not accepted: ..."}` per the audit) — never block the core chat loop on a peripheral feature
failing.

---

## 4. Backend additions

Two new thin endpoints, both request/response (no long-lived server-side duplex connections — actual
audio streaming happens browser↔ElevenLabs directly, per §2.3's WSGI-fit rationale). Proposed home:
new `chat/voice.py` module (or a `voice/` app if it grows — but start minimal, this is two endpoints
and some config plumbing, not a new subsystem on the scale of the Vapi phone layer).

### 4.1 `POST /api/chat/<uuid:public_id>/voice/stt-token`

**Purpose**: mint a short-lived, scoped credential the browser can use to open a direct WebSocket to
ElevenLabs Scribe Realtime — the ElevenLabs account API key never reaches the browser. (ElevenLabs
supports signed/short-lived token issuance for exactly this browser-direct-connection pattern; the
credentials dashboard config in §6 is where the long-lived `ELEVENLABS_API_KEY` lives, server-side
only.)

- **Request**: empty POST (session identified by `public_id` in the URL, same auth model as the
  existing message endpoint — anonymous, `public_id` is the bearer token).
- **Response**: `{"token": "...", "expires_at": "...", "ws_url": "wss://api.elevenlabs.io/..."}`.
- **Rate-limited** per session/IP using the exact same `_rate_ok` cache-counter mechanism
  `chat/views.py` already uses for `RATE_LIMIT_SESSION`/`RATE_LIMIT_MESSAGE` — add a
  `RATE_LIMIT_VOICE_TOKEN` env-configurable ceiling (a token mint is cheap to abuse if unmetered).
- Server-side: one outbound call to ElevenLabs' token-mint endpoint using `ELEVENLABS_API_KEY`
  (server-only env var / dashboard credential, §6), short TTL (minutes, not hours).

### 4.2 `POST /api/chat/<uuid:public_id>/voice/speak`

**Purpose**: TTS proxy — turns the bot's already-computed reply text into streamed audio without ever
handing the browser the ElevenLabs key.

- **Request**: `{"text": "<reply text from the last /message SSE 'message' frame>", "voice_id":
  "<optional override>"}`. In practice the widget calls this immediately after receiving the final
  `message` SSE frame from the existing `/message` endpoint — **this endpoint does not call the LLM
  or the orchestrator at all**, it is pure text-to-audio, keeping the FSM completely out of the voice
  layer per the core requirement.
- **Response**: `audio/mpeg` (or the negotiated format) streamed back via Django `StreamingHttpResponse`
  wrapping ElevenLabs' own streaming response — same "hold one worker thread open for the duration"
  cost profile as the existing SSE endpoint, which the current 3-worker gunicorn setup already
  tolerates for chat; voice adds turns of similar duration, not a fundamentally different load shape.
- Server-side: one streaming call to `/v1/text-to-speech/{voice_id}/stream` using
  `ELEVENLABS_API_KEY` + the dashboard-configured `voice_id` (§6) for the conversation's `language`
  (`Conversation.language` already exists — map `sv`→a Swedish ElevenLabs voice, `en`→an English one).
- **Text sanitization before synthesis**: strip any residual `wrap_untrusted()` delimiters or
  markdown the reply text might contain (the specialist/intake replies are meant to be plain
  conversational text already, but this is a cheap defensive pass before anything goes to a
  third-party TTS API) — reuse `chat/sanitize.py`'s existing control-char stripping utility rather
  than writing a new one.
- **No caching of the audio needed for v1** (replies are typically unique per turn); revisit only if
  repeated canned strings — like escalation boilerplate — turn out to dominate usage.

### 4.3 What does NOT change

`POST /api/chat/session` and `POST /api/chat/<uuid:public_id>/message` are **untouched** — this is
the load-bearing fact of the whole design. Voice mode is a client-side orchestration of three calls
(mint STT token → existing message endpoint → speak proxy) around the exact same turn contract chat
mode already uses.

### 4.4 SSE / turn-boundary mapping

Because `process_turn()` returns the complete reply before any SSE frame is sent (confirmed in the
audit — no real token streaming today), the natural turn boundary for voice is: **one finalized user
utterance → one complete `/message` SSE cycle → one `/voice/speak` call → one played-out audio
response.** There is no per-token TTS start; the widget waits for the `{"type":"message", ...}` frame
(same as it renders the chat bubble today) before kicking off `/voice/speak`. This is an accepted
latency tradeoff (§8), not a bug to fix in this design — genuine mid-reply TTS streaming would require
`gemini.generate_stream()` (exists, unused per the audit) to be wired into the orchestrator's
JSON-parsing specialist/router steps, which is a nontrivial FSM change out of scope here.

### 4.5 WSGI implications

Both new endpoints are short-lived request/response (token mint) or bounded-duration streaming
proxies (TTS, bounded by reply length — typically a few seconds of audio). Neither holds a connection
open indefinitely the way a duplex voice call would. The existing `gunicorn --workers 3 --timeout 120`
config likely tolerates this without changes for a demo/low-concurrency deployment; if voice usage
scales, the first lever is `--workers` count (cheap), not an ASGI migration (per the audit's
constraint #1, that's a bigger lift reserved for if/when true duplex phone-style voice — i.e. the Vapi
channel — is built).

---

## 5. Photo upload in both modes

### 5.1 Current coupling (per the audit)

Upload is **not** a standalone endpoint — it's a multipart field (`image`) on the same
`POST /api/chat/<uuid:public_id>/message` call, sanitized synchronously (`chat/uploads.py::
sanitize_image`), run through Gemini vision (`_run_vision()`) as part of the same FSM turn that
processes any accompanying text. This works fine for Chat mode (the file input is part of the same
form the text composer already submits through) but is awkward for Voice mode, where there's no
natural "text field" to attach a file to mid-conversation — the user is talking, not typing.

### 5.2 Proposal: keep the coupled endpoint, no new upload endpoint required for v1

Contrary to what might seem like an obvious "decouple the upload" ask, the *simplest* correct design
for voice mode is: **the camera/attach button in Voice mode still POSTs to the exact same
`/message` endpoint**, just with an empty or minimal `message` text field (or a short fixed caption
like `"[photo]"`) plus the `image` file — i.e. reuse the coupled endpoint as-is, don't add a new one.
This keeps the "one turn = one `_run_vision()` call = one FSM step" invariant completely intact and
avoids inventing a new async ingestion path (which the audit correctly flags as unbuilt, but that gap
exists for **WhatsApp** async media, a genuinely different problem — a synchronous "camera tap → file
picker → upload" flow in a live browser tab is not async in the same sense and doesn't need the same
fix).

**Only add a decoupled `POST /api/chat/<uuid:public_id>/voice/photo` endpoint if**, during
implementation, it turns out the widget's voice-mode camera flow genuinely can't share the existing
composer's submit path cleanly (e.g. because the "Thinking"/"Speaking" UI state machine makes it
awkward to also be mid-multipart-upload) — in that case, the endpoint should be a thin wrapper that
still funnels straight into `sanitize_image()` → `_run_vision()`, not a parallel implementation. Flag
this as a build-time judgment call, not a pre-committed architecture change — see open questions §9.

### 5.3 Verbal acknowledgment flow in voice mode

1. User taps the camera/attach icon (visible in Voice mode exactly as in Chat mode — same icon,
   same `fileInput.accept = "image/*,application/pdf"`, same 10 MB client guard).
2. Native file picker / camera capture opens (mobile: this naturally offers "Take Photo" vs "Choose
   from Library" — no extra widget code needed, this is native `<input type="file" capture>` browser
   behavior).
3. On file selection, the widget immediately POSTs to `/message` with the image attached (§5.2) and
   transitions the voice UI to **Thinking** — same visual state as a spoken turn, since from the FSM's
   perspective this *is* a turn.
4. The SSE response's early frames already include a `{"type":"notice", ...}` if the image was
   rejected (bad type/too large/decompression-bomb-guard tripped) — in voice mode, **speak that notice
   text via `/voice/speak`** exactly like any other bot reply, so a rejected photo gets a spoken
   explanation ("That photo couldn't be used — please try a JPEG or PNG under 8 MB") rather than a
   silently-failed upload the user has no audio cue about.
5. On success, `_run_vision()`'s extracted facts (`manufacturer`/`model`/`serial`/`error_code`) flow
   into `CaseState.slots` exactly as today, and whatever the orchestrator's next spoken reply is (a
   follow-up question, a routing confirmation, etc.) gets synthesized and played — this is the
   "bot acknowledges verbally" requirement, achieved for free by the fact that voice mode always
   speaks whatever `/message` returns, regardless of whether that turn originated from speech or a
   photo.

No new vision/OCR logic, no new sanitization logic — 100% reuse of `chat/uploads.py` and
`orchestrator._run_vision()`, satisfying the "same brain" requirement identically to how text turns
do.

---

## 6. Dashboard config

`dashboard/` currently has no credentials/integrations page at all (confirmed in both audits — the
Vapi-reuse audit explicitly flags this as "the biggest single feature gap," and its source project's
`dashboard/credentials.py` is a directly reusable *pattern*, though ElevenLabs-shaped, not
Vapi-shaped). Add:

### 6.1 New `Credential`-style dashboard page (or extend an existing one)

A small, catalog-driven staff-only page (`@staff_member_required`, same pattern as every other
dashboard view) exposing:
- **`ELEVENLABS_API_KEY`** (secret, masked in the UI, write-only display like a password field) —
  server-side only, never rendered back to the browser in plaintext after save.
- **Voice selection** — per-language `voice_id` (Swedish voice + English voice at minimum; ElevenLabs
  supports 5k+ voices across 70+ languages per the docs, so this is a dropdown/searchable picker
  ideally backed by a live `GET /v1/voices` call cached briefly, or a simple free-text `voice_id`
  field for v1 if wiring a live voice browser is out of scope).
- **Voice settings** (stability/similarity/style knobs — ElevenLabs' standard per-voice tuning
  parameters) as a small JSON field, mirroring the `voice_settings JSON` "the field IS the extension
  seam" pattern the Vapi-reuse audit flags as a good precedent from the sibling project.
- **Enable/disable voice mode per widget** — a simple boolean toggle (e.g. `VOICE_MODE_ENABLED` as
  either a dashboard-editable setting or, if per-widget-instance granularity is ever needed beyond a
  single global toggle, a field on whatever "widget config" model exists — today there isn't one, so
  start with a single global on/off switch scoped to the whole deployment, matching the fact that
  today there's exactly one widget/one client).
- This page reads/writes through the exact same "DB row + live `os.environ`/`settings` apply, no
  redeploy" mechanism `dashboard/credentials.py` demonstrates in the sibling project — a `Credential`
  model (`name`, `value` encrypted-at-rest or at minimum masked-in-UI, `group`) plus an `apply_all()`
  called at Django app-ready time, so a staff member pasting in an ElevenLabs key takes effect
  immediately.

### 6.2 Where it plugs into existing structure

Natural home: alongside **Agent Config** (`/dashboard/agents/`) since that's already "per-role model/
prompt/temperature editing, DB-driven, no redeploy" — a new "Voice" tab or a new top-level
`/dashboard/voice/` page fits the same navigation pattern as Agents/Guardrails/Flow/KB/Sessions/etc.
already listed in `dashboard/urls.py`.

### 6.3 What deliberately stays out of the dashboard

Per-turn TTS voice **selection logic** (which language → which `voice_id`) is a two-row mapping, not
something that needs a full admin UI — a simple settings dict keyed by `Conversation.language` is
fine for v1, exposed as the two voice-id fields above rather than a generalized "voice routing rules"
system (avoid over-building a config surface for a two-language bot).

---

## 7. Security & privacy

### 7.1 API key handling

`ELEVENLABS_API_KEY` lives **server-side only** — in the dashboard `Credential` store (§6) and/or as
an env var fallback, following the exact same discipline `GEMINI_API_KEY`/`GOOGLE_CLOUD_PROJECT`
already follow in this codebase. The browser only ever receives:
- A **short-lived, scoped STT session token** (§4.1) — not the account API key. If ElevenLabs'
  token-mint API for Scribe Realtime doesn't support fine-grained short-lived scoping by the time this
  is built, the fallback is to **not** let the browser talk to ElevenLabs directly at all for STT —
  instead proxy raw audio frames through a Django WebSocket/chunked-upload relay (more backend work,
  breaks the "no long-lived connection" WSGI-friendliness of §2.3, but strictly safer) — flagged as an
  implementation-time decision in §9, not resolved here, since it depends on exactly what ElevenLabs'
  token API supports at build time.
- **Streamed audio bytes** from the `/voice/speak` proxy (§4.2) — never a key, never a credential.

### 7.2 Mic-consent UX

Standard browser permission prompt (`getUserMedia`) is the actual consent mechanism — the widget adds
a **pre-prompt affordance** (a short line of copy before the OS/browser permission dialog fires, e.g.
"Tap to allow microphone access so you can talk to us") so the user isn't surprised by a bare browser
permission popup with no context, and a **post-denial recovery path** (§3.4 — clean fallback to Chat,
never a dead-end Voice tab). No separate "I consent to voice processing" checkbox is proposed beyond
the browser's own permission grant, since ElevenLabs processing is functionally equivalent to any
other third-party API call this bot already makes (Gemini) from a consent-model standpoint — but see
§7.3 for the GDPR-specific recommendation, which is a slightly different question (data handling, not
UI consent).

### 7.3 GDPR — is voice audio stored? Recommendation: **no**

- **Raw audio is never persisted to this app's own storage.** The STT leg is browser→ElevenLabs
  directly (§2.3/§4.1) — Django never receives or stores raw audio bytes for the user's speech at all
  in the recommended Option B architecture. The TTS leg (`/voice/speak`) streams synthesized audio
  through Django but there is **no reason to write it to disk** — it's a pure pass-through proxy,
  should stream and discard, exactly like the existing SSE endpoint doesn't persist its own frames
  beyond the `Message` row it already writes for the *text* content.
- **What IS already persisted, unchanged**: the `Message` row for the turn (text content — the
  finalized transcript, treated identically to a typed message) and the bot's reply text — this is
  no different from today's chat-mode persistence and is already covered by the existing
  `purge_pii.py` GDPR retention sweep (§3 of the audit, cascades `Conversation`→`Message`).
- **ElevenLabs' own retention** is outside this app's control but should be explicitly checked at
  contract/account-setup time (ElevenLabs' own DPA and any configurable "don't retain audio" account
  setting) before this ships to a real client — flagged as an open question (§9) rather than assumed.
- **EU data residency**: per the audit's constraint #7, Vertex AI is fail-closed to `europe-*` region
  in production. **This same posture does not automatically extend to ElevenLabs** — their processing
  region needs an explicit account-level check (ElevenLabs does publish EU-hosted options for
  enterprise-tier customers per their own compliance docs, but this needs verifying against whatever
  tier the account actually is before claiming GDPR-equivalent handling) — another explicit open
  question, not an assumption, per §9.

---

## 8. NFRs

### 8.1 End-to-end voice turn latency budget (Option B)

Rough, additive budget for one full round-trip (user stops speaking → bot starts speaking), based on
the pieces involved — **not measured, this is a planning estimate to sanity-check the architecture,
not a committed SLA**:

| Stage | Est. latency | Notes |
|---|---|---|
| Silence-detection / STT finalization | 150–400 ms | Scribe Realtime advertises ~150ms streaming latency; add margin for the client-side silence-detection window itself (the ~1.2s auto-stop threshold from §3.4 is *before* this — it's "how long we wait to decide you're done talking," a UX tuning knob, not counted as pipeline latency here since it's inherent to any tap/silence-based capture) |
| `/message` full turn (existing chat pipeline) | 1–4 s | Unchanged from today's chat-mode latency — one or more Gemini calls (intake extraction, routing, specialist), per the audit's existing (non-streaming) `process_turn()` behavior; this is the dominant cost and is **identical** to what chat-mode users already experience today, not a voice-specific regression |
| `/voice/speak` TTS request → first audio byte | 200–600 ms | ElevenLabs TTS streaming with latency-optimization flags enabled (§2.1's "0–4" latency-optimization levels — use level 2–3 for a good speed/quality tradeoff) |
| Audio playback start (browser buffering) | ~100–200 ms | Standard `<audio>`/MediaSource buffering overhead |
| **Total (typical)** | **~2–5 s** | Comparable to "read a chat bubble as it appears" today, translated into "wait, then hear a reply" — acceptable for a support-chat use case, not acceptable for a natural back-and-forth phone-call feel (that's what the separate Vapi phone channel, with real duplex audio, is for) |

The dominant cost is the existing FSM turn (1–4s), not the voice-specific additions (~0.5–1s combined)
— meaning voice mode's perceived latency is mostly inherited from chat mode's existing behavior, and
any future work to speed up the FSM (e.g. wiring `gemini.generate_stream()`) benefits both modes
equally.

### 8.2 Browser support matrix

| Feature | Chrome/Edge (desktop+Android) | Safari (macOS+iOS) | Firefox |
|---|---|---|---|
| `getUserMedia` (mic capture) | Yes | Yes (iOS 14.3+) | Yes |
| WebSocket to ElevenLabs Scribe | Yes | Yes | Yes |
| Web Speech API (B2 fallback) | Yes | Partial/inconsistent | No (historically unsupported) |
| `<audio>` streaming playback | Yes | Yes (some autoplay-policy quirks on iOS) | Yes |

Since Option B doesn't depend on the Web Speech API for the primary path (Scribe is used instead),
the practical support matrix is good across all major evergreen browsers — the B2 fallback's weaker
Firefox/Safari support is a non-issue for the primary architecture, only relevant if Scribe itself is
unreachable and the widget degrades further than Chat mode (in which case, per §3.7, it just falls
back to Chat mode entirely rather than chaining fallback-STT-engines, keeping the failure story simple).

### 8.3 Mobile behavior

- iOS Safari requires a **user gesture** to start both `getUserMedia` and `<audio>` playback — already
  satisfied naturally since both are gated behind explicit taps (mode toggle → mic tap) per §3.4, not
  auto-initiated on load.
- Camera capture (`<input type="file" capture="environment">`) works identically to the existing
  chat-mode attach flow already deployed — no new mobile-specific code needed for photo upload in
  voice mode beyond what §5 already covers.
- The widget's existing `.nl-panel` sizing (`max-width:calc(100vw - 32px)`, mobile-sheet-style) needs
  no structural change for voice mode — the mic button/status states replace the composer row within
  the same panel chrome, not a new layout.
- Background/lock-screen behavior: if the tab is backgrounded mid-voice-turn (common on mobile), the
  browser will likely suspend the mic stream — treat this the same as any other connection drop
  (§3.7's fallback-to-chat path), no special mobile-only handling proposed for v1.

---

## 9. Failure modes table + open questions

### 9.1 Failure modes

| Failure | Detection | Behavior |
|---|---|---|
| Mic permission denied | `getUserMedia` rejects | Auto-fallback to Chat mode, inline notice (§3.4, §3.7) |
| STT WebSocket fails to connect | Connection error/timeout on mint or connect | Fallback to Chat mode; do not silently retry indefinitely |
| STT session drops mid-utterance | WebSocket close event during Listening | Finalize whatever partial transcript exists (if any) and send it, or discard and re-prompt "Sorry, I didn't catch that — try again or type" |
| `/message` call fails/times out (existing chat-mode failure, inherited) | Existing widget error handling (`I18N.error`) | Same as today — no voice-specific change; voice UI shows the same error state, offers retry |
| `/voice/speak` TTS proxy fails or times out | Non-2xx / timeout on the fetch | **Do not fail the turn** — the reply text is already in the transcript (§3.6); show it as text, skip audio playback, optionally a small inline "🔇 audio unavailable" marker |
| Image upload rejected in voice mode | Existing `{"type":"notice"}` SSE frame | Speak the notice text via TTS (§5.3) in addition to showing it in the transcript |
| ElevenLabs account/quota exhausted | 4xx/429 from ElevenLabs on token-mint or TTS call | Same as any other provider outage — fallback to Chat mode, do not block the underlying chat pipeline (mirrors "sinks fail independently" philosophy already used for CRM lead delivery per the audit) |
| Browser lacks WebSocket/getUserMedia entirely (very old browser) | Feature-detect on Voice toggle tap | Voice toggle either hidden or disabled with a tooltip, rather than presented and then failing |

### 9.2 Open questions for the owner

1. **Exact hex/typography match for the homepage clone** — is "brand blue we already use in the demo
   (`#1a74bf`/`#0f4570`) plus placeholder trade photography" good enough, or does this need a
   pixel-level pass against a live screenshot of `nordlandvvs.se` before a client sees it?
2. **Real footer/contact details** — the actual fetch didn't surface footer content (address/phone/
   social links); should the clone use genuinely placeholder contact info, or is it acceptable/desired
   to reproduce the real Nordland VVS public contact details (which are, after all, public
   information, unlike copyrighted imagery)?
3. **ElevenLabs EU data residency** — does the account tier being used (or planned) offer EU-hosted
   processing, and is that a hard requirement here the way it already is for Vertex AI? This should be
   answered before any client-facing voice demo goes live with real (even if synthetic-test) audio.
4. **ElevenLabs audio retention** — confirm via ElevenLabs' account settings/DPA whether raw audio is
   retained on their side by default, and whether that's configurable to "do not retain," to fully
   close out the GDPR posture from §7.3.
5. **STT token-mint scoping** — does ElevenLabs' Scribe Realtime token API support the short-lived,
   narrowly-scoped tokens this design assumes for direct browser↔ElevenLabs connections (§4.1, §7.1)?
   If not, the fallback (proxy raw audio through Django) is materially more backend work and should be
   budgeted as such rather than discovered mid-build.
6. **Decoupled photo-upload endpoint** — confirmed as *not* pre-committed (§5.2); worth a quick spike
   during implementation to see whether the existing coupled endpoint really is clean to reuse from
   the voice UI's state machine, or whether the decoupled endpoint should be built proactively.
7. **Global vs. per-widget voice enable/disable** — is a single global on/off toggle sufficient (today
   there's exactly one client/one widget), or should this be designed for multi-tenant from day one
   given the broader Vapi/WhatsApp roadmap in the companion audit?
8. **Fallback to Option A** — does the owner want a time-boxed spike of the ElevenLabs Agents Platform
   pass-through-tool approach (§2.2) in parallel, purely to de-risk Option B's DIY barge-in UX before
   committing fully, or proceed straight to building Option B and treat Option A as a pure paper
   fallback unless Option B's UX genuinely disappoints in testing?

---

## Summary of recommendation

- **Homepage clone**: new Django template + view (`templates/homepage_demo.html`, extending the
  `widget_demo.html` pattern), same-origin embed of the unmodified widget script, brand-blue +
  placeholder imagery, no CORS change needed for the same-origin case.
- **Voice architecture**: **Option B — browser/ElevenLabs-Scribe STT + the existing, completely
  unmodified `/api/chat` pipeline + an ElevenLabs-TTS proxy endpoint** — chosen because it is the only
  approach that reuses the FSM/guardrails with zero behavioral-drift risk, fits the current WSGI
  deploy with minimal new backend surface (two thin endpoints, no long-lived connections held by
  Django), and is cheapest per-turn. **Option A (ElevenLabs Agents Platform via a pass-through server
  tool)** is the documented fallback if DIY barge-in/turn-taking proves too rough in practice.
- **Photo upload**: reuse the existing coupled `/message` endpoint as-is for both modes; voice mode
  adds verbal acknowledgment of whatever the turn's reply/notice text already is — no new vision
  pipeline.
- **Dashboard**: new credentials/voice-config page, following the sibling project's proven
  "DB row + live `settings`/`os.environ` apply, no redeploy" pattern.
