(function () {
  "use strict";
  var INTERVAL = Math.max(3, parseFloat(document.body.dataset.interval) || 5) * 1000;
  var SERIES_COLORS = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"];
  var GLYPH = { LOW: "●", MEDIUM: "◆", HIGH: "▲" };      // shape + label, never colour alone
  var $ = function (id) { return document.getElementById(id); };
  var roadOrder = [];            // fixed order => a road keeps its colour
  var hidden = {};               // legend toggles
  var lastTrends = null;
  var failures = 0, lastGoodAt = 0;

  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]; }); }
  function badge(s) { return '<span class="badge ' + esc(s) + '"><span aria-hidden="true">' + (GLYPH[s] || "") + "</span>" + esc(s) + "</span>"; }
  function colorOf(road) { var i = roadOrder.indexOf(road); return SERIES_COLORS[(i < 0 ? 0 : i) % 4]; }
  function getJSON(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(url + " " + r.status);
      return r.json();
    });
  }

  /* ---------- summary ---------- */
  function renderSummary(s) {
    $("empty").hidden = s.has_data;
    $("empty-int").textContent = INTERVAL / 1000;
    if (!s.has_data) {
      ["k-cars", "k-speed", "k-high", "k-co2"].forEach(function (id) { $(id).textContent = "–"; });
      $("roads").innerHTML = '<p class="muted">No readings yet.</p>';
      return;
    }
    $("k-cars").textContent = s.total_vehicles;
    $("k-speed").textContent = s.average_speed;
    $("k-high").textContent = s.congested_roads;
    $("k-total").textContent = s.monitored_roads;
    $("k-co2").textContent = s.total_carbon_kg;
    s.roads.forEach(function (r) { if (roadOrder.indexOf(r.road) < 0) roadOrder.push(r.road); });
    roadOrder.sort();
    $("roads").innerHTML = s.roads.map(function (r) {
      return '<div class="road s-' + esc(r.status) + '"><div class="road-name">' + esc(r.road) + badge(r.status) + "</div>" +
        '<div class="road-stats"><span><b>' + r.cars + "</b> vehicles</span><span><b>" + r.speed + "</b> km/h</span></div>" +
        '<div class="road-stats"><span class="aq ' + esc(r.air_quality) + '">Air (est.): ' + esc(r.air_quality) + "</span><span>" + r.carbon_kg + " kg CO₂</span></div></div>";
    }).join("");
    var e = s.emergency;
    if (e) {
      var rec = e.recommended;
      $("em-body").innerHTML = '<div class="em-main">' + esc(rec.road) + "</div>" +
        '<div class="em-meta">Est. ' + rec.eta_minutes + " min per km &middot; " + rec.speed + " km/h &middot; " + badge(rec.status) + "</div>" +
        '<ol class="rank">' + e.ranking.map(function (x) {
          return "<li><span>" + esc(x.road) + "</span><span>" + x.eta_minutes + " min/km &middot; " + esc(x.status) + "</span></li>";
        }).join("") + "</ol>";
    }
  }

  /* ---------- records table ---------- */
  function renderRecords(d) {
    var rows = d.records;
    $("rec-body").innerHTML = rows.length ? rows.map(function (r) {
      return "<tr><td>" + r.id + "</td><td>" + esc(r.recorded_at.slice(11, 19)) + "</td><td>" + esc(r.road) + '</td><td class="num">' + r.cars +
        '</td><td class="num">' + r.speed + "</td><td>" + badge(r.status) + '</td><td class="aq ' + esc(r.air_quality) + '">' + esc(r.air_quality) +
        '</td><td class="num">' + r.carbon_kg + "</td></tr>";
    }).join("") : '<tr><td colspan="8" class="muted">No records yet.</td></tr>';
  }

  /* ---------- SVG line chart with hover ---------- */
  function lineChart(el, points, key, unit) {
    var W = 560, H = 230, m = { l: 38, r: 10, t: 8, b: 24 };
    var times = [], byRoad = {};
    points.forEach(function (p) {
      var t = p.t; if (times.indexOf(t) < 0) times.push(t);
      (byRoad[p.road] = byRoad[p.road] || {})[t] = p[key];
    });
    if (times.length < 2) { el.innerHTML = '<p class="muted">Collecting data – the chart appears after a few readings.</p>'; return; }
    var roads = roadOrder.filter(function (r) { return byRoad[r] && !hidden[r]; });
    var max = 1;
    roads.forEach(function (r) { times.forEach(function (t) { if (byRoad[r][t] > max) max = byRoad[r][t]; }); });
    max = Math.ceil(max / 10) * 10;
    var x = function (i) { return m.l + (W - m.l - m.r) * i / (times.length - 1); };
    var y = function (v) { return m.t + (H - m.t - m.b) * (1 - v / max); };
    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + esc(unit) + ' by road over time">';
    for (var g = 0; g <= 4; g++) {
      var gv = max * g / 4;
      svg += '<line class="grid-line" x1="' + m.l + '" x2="' + (W - m.r) + '" y1="' + y(gv) + '" y2="' + y(gv) + '"/><text x="' + (m.l - 6) + '" y="' + (y(gv) + 4) + '" text-anchor="end">' + Math.round(gv) + "</text>";
    }
    svg += '<text x="' + m.l + '" y="' + (H - 6) + '">' + esc(times[0].slice(11, 19)) + '</text><text x="' + (W - m.r) + '" y="' + (H - 6) + '" text-anchor="end">' + esc(times[times.length - 1].slice(11, 19)) + "</text>";
    roads.forEach(function (r) {
      var d = "";
      times.forEach(function (t, i) { if (byRoad[r][t] != null) d += (d ? "L" : "M") + x(i).toFixed(1) + " " + y(byRoad[r][t]).toFixed(1); });
      svg += '<path d="' + d + '" fill="none" stroke="' + colorOf(r) + '" stroke-width="2" stroke-linejoin="round"/>';
    });
    svg += '<line id="cross" y1="' + m.t + '" y2="' + (H - m.b) + '" stroke="var(--muted)" stroke-width="1" visibility="hidden"/><rect class="hit" x="' + m.l + '" y="0" width="' + (W - m.l - m.r) + '" height="' + H + '" fill="transparent"/></svg><div class="tip" hidden></div>';
    el.innerHTML = svg;
    var svgEl = el.querySelector("svg"), tip = el.querySelector(".tip"), cross = el.querySelector("#cross");
    function show(evt) {
      var box = svgEl.getBoundingClientRect(), cx = (evt.clientX - box.left) / box.width * W;
      var i = Math.round((cx - m.l) / (W - m.l - m.r) * (times.length - 1));
      i = Math.min(times.length - 1, Math.max(0, i));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      tip.innerHTML = "<div><b>" + esc(times[i].slice(11, 19)) + " UTC</b></div>" + roads.map(function (r) {
        var v = byRoad[r][times[i]];
        return '<div><i style="background:' + colorOf(r) + '"></i>' + esc(r) + ": " + (v == null ? "–" : v + " " + unit) + "</div>";
      }).join("");
      tip.hidden = false;
      var left = x(i) / W * box.width + 12; if (left > box.width - 170) left = x(i) / W * box.width - 170;
      tip.style.left = left + "px"; tip.style.top = "8px";
    }
    function hide() { tip.hidden = true; cross.setAttribute("visibility", "hidden"); }
    svgEl.addEventListener("mousemove", show); svgEl.addEventListener("mouseleave", hide);
    svgEl.addEventListener("touchstart", function (e) { show(e.touches[0]); }, { passive: true });
  }

  function renderLegends() {
    document.querySelectorAll(".legend").forEach(function (box) {
      box.innerHTML = roadOrder.map(function (r) {
        return '<button type="button" aria-pressed="' + (!hidden[r]) + '" data-road="' + esc(r) + '"><i style="background:' + colorOf(r) + '"></i>' + esc(r) + "</button>";
      }).join("");
    });
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest(".legend button"); if (!b) return;
    var r = b.dataset.road, visible = roadOrder.filter(function (x) { return !hidden[x]; });
    if (!hidden[r] && visible.length === 1) return;          // keep at least one road visible
    hidden[r] = !hidden[r]; renderLegends(); if (lastTrends) drawCharts(lastTrends);
  });

  function drawCharts(t) {
    lineChart($("chart-cars"), t.points, "cars", "vehicles");
    lineChart($("chart-speed"), t.points, "speed", "km/h");
  }

  function renderTrends(t) {
    lastTrends = t;
    t.points.forEach(function (p) { if (roadOrder.indexOf(p.road) < 0) roadOrder.push(p.road); });
    roadOrder.sort(); renderLegends(); drawCharts(t);
    var total = t.statuses.reduce(function (a, s) { return a + t.status_counts[s]; }, 0);
    if (!total) { $("dist").innerHTML = '<p class="muted">No readings yet.</p>'; return; }
    $("dist").innerHTML = '<div class="bar" role="img" aria-label="Share of LOW, MEDIUM and HIGH readings">' +
      t.statuses.map(function (s) { return '<span class="' + s + '" style="width:' + (100 * t.status_counts[s] / total) + '%"></span>'; }).join("") + "</div>" +
      '<ul class="dist-list">' + t.statuses.map(function (s) {
        return "<li>" + badge(s) + "<span>" + t.status_counts[s] + " readings (" + Math.round(100 * t.status_counts[s] / total) + "%)</span></li>";
      }).join("") + "</ul>";
  }

  /* ---------- model panel ---------- */
  function renderModel(m) {
    var line, detail;
    if (m.active === "ml_model" && m.metrics) {
      var x = m.metrics;
      line = "Decision tree on vehicles and speed. Held-out score on rule-labelled synthetic data: " + (x.test_accuracy * 100).toFixed(1) + "% (" + x.test_samples + " test samples).";
      detail = x.limitations + " Features: " + x.features.join(", ") + ". Classes: " + x.classes.join(", ") + ". Training: " + x.training_data + ". Trained " + x.trained_at + ".";
    } else if (m.active === "ml_model") {
      line = "Decision tree is active, but its evaluation report was not found. Run python train_model.py.";
      detail = "Features: vehicles, speed. Classes: LOW, MEDIUM, HIGH.";
    } else {
      line = "The trained model is unavailable, so the dashboard is using the rule-based classifier (" + (m.error || "unknown reason") + ").";
      detail = "Run python train_model.py to create the model.";
    }
    $("ml-line").textContent = line; $("ml-detail").textContent = detail;
  }

  $("whatif").addEventListener("submit", function (e) {
    e.preventDefault();
    var out = $("whatif-out"), c = $("in-cars").value, s = $("in-speed").value;
    if (c === "" || s === "") { out.textContent = "Enter both a vehicle count and a speed."; return; }
    getJSON("/api/predict?cars=" + encodeURIComponent(c) + "&speed=" + encodeURIComponent(s)).then(function (p) {
      out.innerHTML = badge(p.status) + " &nbsp;by " + (p.predicted_by === "ml_model" ? "the ML model" : "the rules") +
        (p.status !== p.rule_status ? " (rules say " + esc(p.rule_status) + ")" : " (matches the rules)") +
        " &middot; est. " + p.carbon_kg + " kg CO₂, air " + esc(p.air_quality);
    }).catch(function () { out.textContent = "Values must be a vehicle count of 0–500 and a speed of 0–150 km/h."; });
  });

  /* ---------- polling ---------- */
  function setLive(state, text) { var el = $("live"); el.className = "live live-" + state; $("live-text").textContent = text; }
  function refresh() {
    if (document.hidden) return;
    Promise.all([getJSON("/api/summary"), getJSON("/api/records?limit=15"), getJSON("/api/trends")]).then(function (r) {
      renderSummary(r[0]); renderRecords(r[1]); renderTrends(r[2]);
      failures = 0; lastGoodAt = Date.now();
      if (!r[0].has_data) setLive("stale", "Simulated data · no readings yet");
      else if (r[0].data_age_seconds > INTERVAL / 1000 * 3 + 5) setLive("stale", "Simulated data · stalled (last reading " + r[0].data_age_seconds + " s ago)");
      else setLive("ok", "Simulated data · updating every " + INTERVAL / 1000 + " s");
    }).catch(function () {
      failures++; setLive("bad", "Connection lost · retrying");
    });
  }
  getJSON("/api/model").then(renderModel).catch(function () { $("ml-line").textContent = "Model details are unavailable."; });
  refresh(); setInterval(refresh, INTERVAL);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
})();
