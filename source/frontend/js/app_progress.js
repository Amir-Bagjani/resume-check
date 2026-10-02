/* Progress: poll GET /api/runs/{id} every 2s, pause/resume/cancel. */
(function () {
  "use strict";
  var timer = null;
  var runId = null;
  var criteriaText = "";

  function $(id) { return document.getElementById(id); }
  function show(id, visible) { $(id).hidden = !visible; }
  function pct(done, total) { return total > 0 ? Math.round((done / total) * 100) : 0; }

  function criteriaSummary(c) {
    var parts = [];
    if (c && c.minYears !== null && c.minYears !== undefined && c.minYears !== "") parts.push("min " + c.minYears + " yrs");
    if (c && c.keywords && c.keywords.length) parts.push("keywords: " + c.keywords.join(", "));
    return parts.join(" · ") || "—";
  }

  function render(data) {
    var found = data.found || 0;
    var processed = data.processed || 0;
    var p = pct(processed, found);
    $("progress-fill").style.width = p + "%";
    $("progress-bar").setAttribute("aria-valuenow", String(p));
    $("progress-text").textContent = processed + " / " + found + " (" + p + "%)";
    $("c-processed").textContent = processed;
    $("c-qualified").textContent = data.qualified || 0;
    $("c-not").textContent = data.notQualified || 0;
    $("c-und").textContent = data.undetermined || 0;
    if (data.results && data.results.length) {
      var last = data.results[data.results.length - 1];
      $("progress-current").textContent = last.filename || "—";
    }
    $("pause-btn").textContent = data.state === "paused" ? "Resume" : "Pause";
  }

  function poll() {
    fetch("/api/runs/" + encodeURIComponent(runId)).then(function (res) {
      if (!res.ok) throw new Error("Status check failed (" + res.status + ")");
      return res.json();
    }).then(function (data) {
      // Backend may use notQualified or not_qualified; normalize.
      if (data.not_qualified !== undefined && data.notQualified === undefined) data.notQualified = data.not_qualified;
      render(data);
      if (data.state === "finished" || data.state === "cancelled") {
        stop();
        window.App.results.show(data);
      }
    }).catch(function (err) {
      var el = $("progress-error");
      el.textContent = err.message || "Progress update failed.";
      el.hidden = false;
    });
  }

  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  function begin(id, folderPath, criteria) {
    runId = id;
    criteriaText = criteriaSummary(criteria);
    stop();
    var err = $("progress-error");
    err.hidden = true; err.textContent = "";
    $("screen-setup").hidden = true;
    $("screen-results").hidden = true;
    $("screen-progress").hidden = false;
    $("progress-folder").textContent = folderPath;
    $("progress-criteria").textContent = criteriaText;
    poll();
    timer = setInterval(poll, 2000);
  }

  function pauseToggle() {
    if (!runId) return;
    fetch("/api/runs/" + encodeURIComponent(runId) + "/pause", { method: "POST" }).then(function (res) {
      // Resume path: if already paused, backend exposes /resume; try it on conflict.
      if (res.status === 409) throw new Error("paused");
      if (!res.ok) throw new Error("Pause failed (" + res.status + ")");
      poll();
    }).catch(function () {
      fetch("/api/runs/" + encodeURIComponent(runId) + "/resume", { method: "POST" }).then(poll);
    });
  }

  function cancel() {
    if (!runId) return;
    if (!window.confirm("Cancel screening? Processed files keep partial results and a report.")) return;
    fetch("/api/runs/" + encodeURIComponent(runId) + "/cancel", { method: "POST" }).then(function () {
      poll(); // next poll lands on results with partial data
    });
  }

  function init() {
    $("pause-btn").addEventListener("click", pauseToggle);
    $("cancel-btn").addEventListener("click", cancel);
  }

  window.App = window.App || {};
  window.App.progress = { begin: begin };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
