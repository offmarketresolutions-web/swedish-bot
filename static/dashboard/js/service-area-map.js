/* Service-area map: draw a coverage polygon and see which postcodes it actually covers.
 *
 * The coverage answer comes from crm.PostcodeArea (18,870 Swedish postcodes already on
 * disk), not a geocoding service — instant, no rate limit, and no service area or
 * customer address ever leaves the server. OpenStreetMap supplies only the backdrop.
 *
 * Progressive enhancement: the GeoJSON textarea remains the source of truth for the form,
 * so the page still works with this file blocked or JS off. Drawing writes into it.
 */
(function () {
  "use strict";

  var root = document.getElementById("sa-map");
  if (!root || typeof L === "undefined") return; // no map element, or Leaflet blocked

  var field = document.getElementById("sa-polygon-field");
  var coverageBox = document.getElementById("sa-coverage");
  var searchInput = document.getElementById("sa-place-search");
  var searchResults = document.getElementById("sa-place-results");
  var clearBtn = document.getElementById("sa-clear");
  var urls = root.dataset;

  // Sundsvall — the middle of the documented corridor, a sane default view.
  var map = L.map(root).setView([62.39, 17.31], 8);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  var drawn = new L.FeatureGroup().addTo(map);
  var existing = new L.FeatureGroup().addTo(map);

  // Existing saved areas, for context while drawing a new one.
  var hasExisting = false;
  try {
    var saved = JSON.parse(root.dataset.existing || "[]");
    saved.forEach(function (a) {
      var layer = L.geoJSON({ type: "Feature", geometry: a.polygon, properties: {} }, {
        style: { color: a.kind === "extension" ? "#B45309" : "#1A74BF", weight: 2, fillOpacity: 0.08, dashArray: a.kind === "extension" ? "5,5" : null },
      });
      layer.bindTooltip(a.name + " (" + a.kind + ")");
      existing.addLayer(layer);
    });
    hasExisting = saved.length > 0;
  } catch (e) { /* malformed stored polygon must never break the editor */ }

  // Fit only once the container has real height. Leaflet computes zoom from the pixel
  // size it can see, so fitting a 350 km corridor into a container that is still 0px
  // tall — CSS not yet applied, a background tab, fonts reflowing — snaps the map to
  // zoom 18 over open water, which looks exactly like a broken basemap.
  function fitToContent() {
    if (root.getBoundingClientRect().height < 50) return false;
    map.invalidateSize();
    var group = drawn.getLayers().length ? drawn : (hasExisting ? existing : null);
    if (group) {
      var b = group.getBounds();
      if (b && b.isValid()) map.fitBounds(b, { padding: [30, 30], maxZoom: 13 });
    }
    return true;
  }

  if (!fitToContent()) {
    var tries = 0;
    var poll = setInterval(function () {
      if (fitToContent() || ++tries > 20) clearInterval(poll);
    }, 150);
  }
  window.addEventListener("resize", function () { map.invalidateSize(); });

  map.addControl(new L.Control.Draw({
    edit: { featureGroup: drawn, remove: true },
    draw: {
      polygon: { allowIntersection: false, showArea: true, shapeOptions: { color: "#1A74BF", weight: 2 } },
      rectangle: { shapeOptions: { color: "#1A74BF", weight: 2 } },
      polyline: false, circle: false, marker: false, circlemarker: false,
    },
  }));

  function geometryOf(layer) {
    var gj = layer.toGeoJSON();
    return gj.geometry;
  }

  function setStatus(html, tone) {
    if (!coverageBox) return;
    coverageBox.className = "text-sm rounded-md px-3 py-2 " + (tone || "");
    coverageBox.innerHTML = html;
  }

  function describeCoverage(d) {
    if (!d.postcodes) {
      return "<strong>No postcodes inside this shape.</strong> Draw around a populated " +
             "area, or check the shape is in Sweden.";
    }
    var cities = d.cities.slice(0, 8).join(", ");
    var more = d.city_count > 8 ? " +" + (d.city_count - 8) + " more" : "";
    return "<strong>" + d.postcodes + " postcodes</strong> across <strong>" +
           d.city_count + "</strong> places — " + cities + more;
  }

  function refreshCoverage(geometry) {
    if (!geometry) { setStatus("Draw a shape to see which postcodes it covers.", "text-nl-base/60"); return; }
    setStatus("Checking coverage…", "text-nl-base/60");
    fetch(urls.coverageUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": urls.csrf },
      body: JSON.stringify({ polygon: geometry }),
    })
      .then(function (r) { return r.ok ? r.json() : r.json().then(function (e) { throw new Error(e.error || "failed"); }); })
      .then(function (d) { setStatus(describeCoverage(d), "bg-nl-accent/5 text-nl-base"); })
      .catch(function (e) { setStatus("Couldn't check coverage: " + e.message, "text-red-700"); });
  }

  function adopt(layer) {
    drawn.clearLayers();
    drawn.addLayer(layer);
    var geometry = geometryOf(layer);
    if (field) field.value = JSON.stringify(geometry);
    refreshCoverage(geometry);
  }

  map.on(L.Draw.Event.CREATED, function (e) { adopt(e.layer); });
  map.on(L.Draw.Event.EDITED, function (e) { e.layers.eachLayer(adopt); });
  map.on(L.Draw.Event.DELETED, function () {
    drawn.clearLayers();
    if (field) field.value = "";
    refreshCoverage(null);
  });

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      drawn.clearLayers();
      if (field) field.value = "";
      refreshCoverage(null);
    });
  }

  // ── place search: type a town/municipality, jump the map there ──────────────
  var searchTimer = null;
  function renderMatches(matches) {
    if (!searchResults) return;
    searchResults.innerHTML = "";
    if (!matches.length) {
      searchResults.innerHTML = '<li class="px-2 py-1 text-nl-base/60">No place by that name.</li>';
      searchResults.hidden = false;
      return;
    }
    matches.forEach(function (m) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "w-full text-left px-2 py-1 hover:bg-nl-accent/10 rounded";
      btn.setAttribute("data-testid", "sa-place-result");
      btn.textContent = m.name + " — " + m.postcodes + " postcodes (" + m.kind + ")";
      btn.addEventListener("click", function () {
        map.fitBounds([[m.bbox[0], m.bbox[1]], [m.bbox[2], m.bbox[3]]], { padding: [40, 40], maxZoom: 12 });
        searchResults.hidden = true;
        if (searchInput) searchInput.value = m.name;
      });
      li.appendChild(btn);
      searchResults.appendChild(li);
    });
    searchResults.hidden = false;
  }

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      var q = searchInput.value.trim();
      clearTimeout(searchTimer);
      if (q.length < 2) { if (searchResults) searchResults.hidden = true; return; }
      searchTimer = setTimeout(function () {
        fetch(urls.placesUrl + "?q=" + encodeURIComponent(q))
          .then(function (r) { return r.json(); })
          .then(function (d) { renderMatches(d.matches || []); })
          .catch(function () { renderMatches([]); });
      }, 250);
    });
    searchInput.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && searchResults) searchResults.hidden = true;
    });
  }

  // If the textarea already holds a polygon (paste, or a failed submit), show it.
  if (field && field.value.trim()) {
    try {
      var g = JSON.parse(field.value);
      var l = L.geoJSON({ type: "Feature", geometry: g.geometry || g, properties: {} });
      l.eachLayer(function (sub) { drawn.addLayer(sub); });
      fitToContent();
      refreshCoverage(g.geometry || g);
    } catch (e) { /* leave the textarea as the operator typed it */ }
  } else {
    refreshCoverage(null);
  }
})();
