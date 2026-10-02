/* Results: summary cards, output path, filterable per-resume table. */
(function () {
  "use strict";
  var rows = [];
  var activeFilter = "all";
  var query = "";

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s === null || s === undefined ? "" : s); }
  function list(v) { return Array.isArray(v) ? v.join(", ") : esc(v); }

  function statusClass(s) {
    if (s === "Qualified") return "status-qualified";
    if (s === "Not Qualified") return "status-not";
    return "status-und";
  }

  function criteriaSummary(data) {
    if (data.criteria) {
      var c = data.criteria, parts = [];
      if (c.minYears !== null && c.minYears !== undefined && c.minYears !== "") parts.push("min " + c.minYears + " yrs");
      if (c.keywords && c.keywords.length) parts.push("keywords: " + c.keywords.join(", "));
      if (parts.length) return parts.join(" · ");
    }
    return esc(data.criteriaUsed || "—");
  }

  function renderTable() {
    var body = $("results-body");
    body.textContent = "";
    var q = query.trim().toLowerCase();
    var shown = 0;
    rows.forEach(function (r) {
      if (activeFilter !== "all" && r.finalStatus !== activeFilter) return;
      if (q) {
        var hay = ((r.filename || "") + " " + (r.candidateName || "") + " " + (r.reason || "")).toLowerCase();
        if (hay.indexOf(q) === -1) return;
      }
      shown++;
      var tr = document.createElement("tr");
      var years = (r.estimatedYears === null || r.estimatedYears === undefined) ? "Unknown" : r.estimatedYears;
      var cells = [
        r.filename, r.candidateName, years, r.experienceStatus,
        list(r.skillsDetected), list(r.requiredFound), list(r.requiredMissing),
      ];
      cells.forEach(function (text, i) {
        var td = document.createElement("td");
        td.textContent = esc(text) || (i === 1 ? "—" : "");
        if (i >= 4) {
          // ponytail: truncate long skill lists with a toggle, no lib.
          td.className = "skills-cell";
          if (td.textContent.length > 80) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = "Expand";
            btn.setAttribute("aria-label", "Expand skills list");
            btn.addEventListener("click", function () {
              td.classList.toggle("expanded");
              btn.textContent = td.classList.contains("expanded") ? "Collapse" : "Expand";
            });
            td.appendChild(document.createTextNode(" "));
            td.appendChild(btn);
          }
        }
        tr.appendChild(td);
      });
      var sTd = document.createElement("td");
      sTd.textContent = esc(r.finalStatus);
      sTd.className = statusClass(r.finalStatus);
      tr.appendChild(sTd);
      var reason = document.createElement("td");
      reason.textContent = esc(r.reason);
      tr.appendChild(reason);
      body.appendChild(tr);
    });
    $("results-count").textContent = shown + " of " + rows.length + " resume(s) shown.";
  }

  function show(data) {
    rows = data.results || [];
    $("screen-progress").hidden = true;
    $("screen-setup").hidden = true;
    $("screen-results").hidden = false;
    $("s-found").textContent = data.found || 0;
    $("s-processed").textContent = data.processed || 0;
    $("s-qualified").textContent = data.qualified || 0;
    $("s-not").textContent = (data.notQualified !== undefined ? data.notQualified : data.not_qualified) || 0;
    $("s-und").textContent = data.undetermined || 0;
    $("output-path").textContent = data.outputPath || "—";
    $("report-name").textContent = data.reportName || data.reportFile || "screening-report.xlsx";
    $("results-criteria").textContent = criteriaSummary(data);
    $("results-date").textContent = [data.screeningDateJalali, data.screeningDate].filter(Boolean).join(" / ") || "—";
    $("empty-qualified-notice").hidden = !(Number(data.qualified || 0) === 0);
    var err = $("results-error");
    if (data.error) { err.textContent = data.error; err.hidden = false; }
    else { err.hidden = true; err.textContent = ""; }
    renderTable();
    $("results-heading").setAttribute("tabindex", "-1");
    $("results-heading").focus();
  }

  function init() {
    document.querySelectorAll(".filter-chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        activeFilter = chip.getAttribute("data-filter");
        document.querySelectorAll(".filter-chip").forEach(function (c) {
          c.setAttribute("aria-pressed", c === chip ? "true" : "false");
        });
        renderTable();
      });
    });
    $("table-search").addEventListener("input", function (e) { query = e.target.value; renderTable(); });
    $("copy-path-btn").addEventListener("click", function () {
      var path = $("output-path").textContent;
      function done() { $("copy-confirm").textContent = "Output path copied."; }
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(path).then(done, done);
      else {
        var ta = document.createElement("textarea");
        ta.value = path; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); } catch (e) { /* ponytail: clipboard best-effort only */ }
        document.body.removeChild(ta); done();
      }
    });
    $("new-run-btn").addEventListener("click", function () {
      activeFilter = "all"; query = ""; $("table-search").value = "";
      document.querySelectorAll(".filter-chip").forEach(function (c) {
        c.setAttribute("aria-pressed", c.getAttribute("data-filter") === "all" ? "true" : "false");
      });
      window.App.setup.resetToSetup(true);
    });
  }

  window.App = window.App || {};
  window.App.results = { show: show };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
