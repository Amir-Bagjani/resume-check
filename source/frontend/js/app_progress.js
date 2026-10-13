/* Progress: polls the real run status, never a fake bar. */
(function () {
  "use strict";
  var timer = null;
  var runId = null;
  var importId = null;

  function $(id) { return document.getElementById(id); }
  function faNum(v) { return window.App.faNum(v); }

  function criteriaSummary(c) {
    var parts = [];
    if (c && c.minYears !== null && c.minYears !== undefined && c.minYears !== "") {
      parts.push("حداقل " + faNum(c.minYears) + " سال");
    }
    return parts.join(" · ") || "—";
  }

  function render(d) {
    $("progress-heading").textContent = "در حال بررسی رزومه‌ها";
    $("progress-counters").hidden = false;
    $("pause-btn").disabled = false;
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
    if (importId && !runId) {
      fetch("/api/jobinja/imports/" + encodeURIComponent(importId))
        .then(function (response) { if (!response.ok) throw new Error("دریافت وضعیت جابینجا ناموفق بود."); return response.json(); })
        .then(function (data) {
          if (data.runId) { runId = data.runId; importId = null; poll(); return; }
          $("progress-heading").textContent = "در حال دریافت رزومه‌ها از جابینجا";
          $("progress-counters").hidden = true;
          $("pause-btn").disabled = true;
          var percent = data.total ? Math.round(data.completed / data.total * 100) : 0;
          $("progress-fill").style.width = percent + "%";
          $("progress-fill").parentElement.setAttribute("aria-valuenow", String(percent));
          $("progress-text").textContent = faNum(data.downloaded) + " رزومه از " + faNum(data.total) + " دریافت شد";
          $("progress-current").textContent = data.failed ? faNum(data.failed) + " خطای دریافت؛ جزئیات در گزارش نهایی" : "";
          if (data.state === "failed") { stop(); $("progress-back-btn").hidden = false; throw new Error(data.error || "دریافت رزومه‌ها ناموفق بود."); }
        })
        .catch(function (error) { $("progress-error").textContent = error.message; $("progress-error").hidden = false; });
      return;
    }
    fetch("/api/runs/" + encodeURIComponent(runId))
      .then(function (r) {
        if (!r.ok) throw new Error("بررسی وضعیت ناموفق بود.");
        return r.json();
      })
      .then(function (d) {
        render(d);
        if (d.state === "failed") {
          stop();
          var el = $("progress-error");
          el.textContent = d.error || "تولید گزارش ناموفق بود؛ جزئیات کامل در لاگ برنامه است.";
          el.hidden = false;
          $("progress-back-btn").hidden = false;
          return;
        }
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

  function begin(id, folderName, criteria, jobId) {
    runId = id;
    importId = jobId || null;
    stop();
    var err = $("progress-error");
    err.hidden = true; err.textContent = "";
    $("progress-back-btn").hidden = true;
    $("pause-btn").disabled = !!importId;
    $("progress-heading").textContent = importId ? "در حال دریافت رزومه‌ها از جابینجا" : "در حال بررسی رزومه‌ها";
    $("progress-counters").hidden = !!importId;
    $("progress-fill").style.width = "0%";
    $("progress-fill").parentElement.setAttribute("aria-valuenow", "0");
    $("progress-text").textContent = "در حال دریافت وضعیت…";
    $("progress-current").textContent = "";

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
    if (!runId && !importId) return;
    if (!window.confirm("دریافت یا بررسی لغو شود؟ فایل‌های دریافت‌شده و نتایج پردازش‌شده حفظ می‌شود.")) return;
    var endpoint = runId ? "/api/runs/" + encodeURIComponent(runId) + "/cancel"
      : "/api/jobinja/imports/" + encodeURIComponent(importId) + "/cancel";
    fetch(endpoint, { method: "POST" })
      .then(poll)
      .catch(function () { /* the next poll will surface any real failure */ });
  }

  function init() {
    $("pause-btn").addEventListener("click", togglePause);
    $("cancel-btn").addEventListener("click", cancel);
    $("progress-back-btn").addEventListener("click", function () { stop(); window.App.setup.resetToSetup(false); });
  }

  window.App = window.App || {};
  window.App.progress = { begin: begin, beginImport: function (id, label, criteria) { begin(null, label, criteria, id); } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
