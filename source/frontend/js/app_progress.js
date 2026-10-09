/* Progress: polls the real run status, never a fake bar. */
(function () {
  "use strict";
  var timer = null;
  var runId = null;

  function $(id) { return document.getElementById(id); }
  function faNum(v) { return window.App.faNum(v); }

  function criteriaSummary(c) {
    var parts = [];
    if (c && c.minYears !== null && c.minYears !== undefined && c.minYears !== "") {
      parts.push("حداقل " + faNum(c.minYears) + " سال");
    }
    if (c && c.keywords && c.keywords.length) parts.push(c.keywords.join("، "));
    return parts.join(" · ") || "—";
  }

  function render(d) {
    var found = d.found || 0;
    var done = d.processed || 0;
    var pct = found > 0 ? Math.round((done / found) * 100) : 0;

    $("progress-fill").style.width = pct + "%";
    $("progress-fill").parentElement.setAttribute("aria-valuenow", String(pct));
    $("progress-text").textContent = faNum(done) + " از " + faNum(found) + " رزومه";

    $("c-processed").textContent = faNum(done);
    $("c-qualified").textContent = faNum(d.qualified || 0);
    $("c-not").textContent = faNum(d.notQualified !== undefined ? d.notQualified : (d.not_qualified || 0));
    $("c-und").textContent = faNum(d.undetermined || 0);

    var last = (d.results && d.results.length) ? d.results[d.results.length - 1] : null;
    $("progress-current").textContent = last && last.filename ? last.filename : "";

    $("pause-btn").textContent = d.state === "paused" ? "ادامه" : "توقف موقت";
  }

  function poll() {
    fetch("/api/runs/" + encodeURIComponent(runId))
      .then(function (r) {
        if (!r.ok) throw new Error("بررسی وضعیت ناموفق بود.");
        return r.json();
      })
      .then(function (d) {
        render(d);
        if (d.state === "finished" || d.state === "cancelled") {
          stop();
          window.App.results.show(d);
        }
      })
      .catch(function (e) {
        var el = $("progress-error");
        el.textContent = e.message || "ارتباط با سرور قطع شد.";
        el.hidden = false;
      });
  }

  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  function begin(id, folderName, criteria) {
    runId = id;
    stop();
    var err = $("progress-error");
    err.hidden = true; err.textContent = "";

    $("screen-setup").hidden = true;
    $("screen-results").hidden = true;
    $("screen-progress").hidden = false;

    $("progress-folder").textContent = folderName || "—";
    $("progress-criteria").textContent = criteriaSummary(criteria);

    poll();
    timer = setInterval(poll, 1500);
  }

  function togglePause() {
    if (!runId) return;
    var action = $("pause-btn").textContent === "ادامه" ? "resume" : "pause";
    fetch("/api/runs/" + encodeURIComponent(runId) + "/" + action, { method: "POST" })
      .then(poll)
      .catch(function () { poll(); });
  }

  function cancel() {
    if (!runId) return;
    if (!window.confirm("بررسی لغو شود؟ نتایج فایل‌های پردازش‌شده حفظ می‌شود.")) return;
    fetch("/api/runs/" + encodeURIComponent(runId) + "/cancel", { method: "POST" })
      .then(poll)
      .catch(function () { /* the next poll will surface any real failure */ });
  }

  function init() {
    $("pause-btn").addEventListener("click", togglePause);
    $("cancel-btn").addEventListener("click", cancel);
  }

  window.App = window.App || {};
  window.App.progress = { begin: begin };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();