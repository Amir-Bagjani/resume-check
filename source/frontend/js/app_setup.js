/* Setup: folder scan, criteria chips, start gating. Exposes window.App. */
(function () {
  "use strict";
  var state = {
    folderPath: "",
    folderValid: false,
    fileCount: 0,
    keywords: [],
    minYears: null,
    runId: null,
  };

  function $(id) { return document.getElementById(id); }
  function showError(msg) {
    var el = $("setup-error");
    el.textContent = msg;
    el.hidden = !msg;
    if (msg) el.focus();
  }

  function hasCriterion() {
    return state.keywords.length > 0 || (state.minYears !== null && state.minYears !== "");
  }

  function refreshStart() {
    var btn = $("start-btn");
    var ok = state.folderValid && state.fileCount > 0 && hasCriterion();
    btn.disabled = !ok;
    $("start-hint").textContent = ok
      ? "Ready: " + state.fileCount + " resume(s), criteria set."
      : "Select a valid folder with resumes and set at least one criterion to start.";
  }

  function renderChips() {
    var ul = $("keyword-chips");
    ul.textContent = "";
    state.keywords.forEach(function (kw) {
      var li = document.createElement("li");
      li.appendChild(document.createTextNode(kw + " "));
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "✕";
      btn.setAttribute("aria-label", "Remove " + kw);
      btn.addEventListener("click", function () {
        state.keywords = state.keywords.filter(function (k) { return k !== kw; });
        renderChips();
        refreshStart();
      });
      li.appendChild(btn);
      ul.appendChild(li);
    });
    refreshStart();
  }

  function addKeyword() {
    var input = $("keyword-input");
    var raw = input.value.trim();
    if (!raw) return;
    var dup = state.keywords.some(function (k) { return k.toLowerCase() === raw.toLowerCase(); });
    if (dup) { input.value = ""; input.focus(); return; }
    state.keywords.push(raw);
    input.value = "";
    input.focus();
    renderChips();
  }

  function scan() {
    var path = $("folder-path").value.trim();
    showError("");
    $("folder-status").textContent = "Scanning…";
    state.folderValid = false;
    state.fileCount = 0;
    refreshStart();
    fetch("/api/folders/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folderPath: path }),
    }).then(function (res) {
      if (!res.ok) return res.json().catch(function () { return {}; }).then(function (body) {
        throw new Error(body.detail || body.message || ("Scan failed (" + res.status + ")"));
      });
      return res.json();
    }).then(function (data) {
      state.folderPath = path;
      state.fileCount = data.fileCount || (data.files ? data.files.length : 0);
      if (state.fileCount === 0) {
        state.folderValid = false;
        $("folder-status").textContent = "No supported resumes found (top-level .pdf/.docx only).";
        showError("No resumes found in this folder. Nothing to screen — no output will be created.");
      } else {
        state.folderValid = true;
        $("folder-status").textContent = state.fileCount + " resume(s) found.";
      }
      refreshStart();
    }).catch(function (err) {
      state.folderValid = false;
      $("folder-status").textContent = "Folder invalid or unreadable.";
      showError(err.message || "Folder scan failed.");
      refreshStart();
    });
  }

  function start() {
    showError("");
    if (!state.folderValid) { showError("Validate a folder with resumes first."); return; }
    if (!hasCriterion()) { showError("Set at least one screening criterion (minimum experience or a keyword) before starting."); return; }
    var criteria = { minYears: state.minYears === "" ? null : state.minYears, keywords: state.keywords.slice() };
    fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folderPath: state.folderPath, criteria: criteria }),
    }).then(function (res) {
      if (!res.ok) return res.json().catch(function () { return {}; }).then(function (body) {
        throw new Error(body.detail || body.message || ("Start failed (" + res.status + ")"));
      });
      return res.json();
    }).then(function (data) {
      state.runId = data.runId;
      window.App.progress.begin(state.runId, state.folderPath, criteria);
    }).catch(function (err) {
      showError(err.message || "Could not start screening.");
    });
  }

  function resetToSetup(keep) {
    // ponytail: keep = preserve folder+criteria for "new run"; else full reset on folder change.
    document.getElementById("screen-progress").hidden = true;
    document.getElementById("screen-results").hidden = true;
    document.getElementById("screen-setup").hidden = false;
    if (!keep) {
      state.folderValid = false;
      state.fileCount = 0;
      $("folder-status").textContent = "";
      refreshStart();
    }
    showError("");
  }

  function init() {
    $("scan-btn").addEventListener("click", scan);
    $("folder-path").addEventListener("input", function () {
      state.folderValid = false; state.fileCount = 0;
      $("folder-status").textContent = "";
      refreshStart();
    });
    $("keyword-add-btn").addEventListener("click", addKeyword);
    $("keyword-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); addKeyword(); }
    });
    $("min-years").addEventListener("input", function (e) {
      var v = e.target.value;
      state.minYears = (v === "" ? null : Number(v));
      refreshStart();
    });
    $("start-btn").addEventListener("click", start);
    renderChips();
    refreshStart();
  }

  window.App = window.App || {};
  window.App.setup = { state: state, resetToSetup: resetToSetup };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
