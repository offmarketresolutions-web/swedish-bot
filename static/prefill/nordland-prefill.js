/* Nordland VVS — form prefill snippet (plan S6/D2).
 * Reads ?nl_case=<token> from the URL, fetches /api/prefill/<token>, and fills
 * form fields per FIELD_MAP. FIELD_MAP is the ONLY thing that needs to change
 * to point this at the real Bricks form on nordlandvvs.se — everything else is
 * generic. Fails soft: no token, expired token, or network error -> no-op.
 * See docs/plans/2026-07-13-prefill-install.md.
 */
(function () {
  "use strict";

  // selector -> dotted path into the /api/prefill response. Update this map (only
  // this map) for the real WordPress form's actual field names/selectors.
  var FIELD_MAP = {
    '[data-field="name"]': "contact.name",
    '[data-field="phone"]': "contact.phone",
    '[data-field="email"]': "contact.email",
    '[data-field="category"]': "technical.category",
    '[data-field="brand"]': "technical.brand",
    '[data-field="model"]': "technical.model",
    '[data-field="error_code"]': "technical.error_code",
    '[data-field="problem"]': "technical.problem",
    '[data-field="postal_code"]': "technical.postal_code",
  };

  function getParam(name) {
    try {
      return new URLSearchParams(window.location.search).get(name);
    } catch (e) {
      return null;
    }
  }

  function getPath(obj, path) {
    return path.split(".").reduce(function (o, k) {
      return o && typeof o === "object" ? o[k] : undefined;
    }, obj);
  }

  var token = getParam("nl_case");
  if (!token) return;

  fetch("/api/prefill/" + encodeURIComponent(token))
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data) return;
      var filled = false;
      Object.keys(FIELD_MAP).forEach(function (selector) {
        var el = document.querySelector(selector);
        if (!el) return;
        var value = getPath(data, FIELD_MAP[selector]);
        if (value === undefined || value === null || value === "") return;
        el.value = value;
        filled = true;
      });
      if (filled) {
        var banner = document.getElementById("prefillBanner");
        if (banner) banner.classList.add("show");
      }
    })
    .catch(function () { /* fail soft — no token, expired, network error */ });
})();
