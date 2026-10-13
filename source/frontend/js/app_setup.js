/* Setup: folder picker, upload and criteria. Exposes window.App. */
(function () {
  "use strict";

  var FA = "۰۱۲۳۴۵۶۷۸۹";

  window.App = window.App || {};
  window.App.faNum = function (v) {
    if (v === null || v === undefined || v === "") return "۰";
    return String(v).replace(/[0-9]/g, function (d) { return FA[Number(d)]; });
  };

  var ACCEPTED = [".pdf", ".docx"];

  var state = {
    folderName: "",
    fileCount: 0,
    skipped: 0,
    uploadId: null,
    uploading: false,
    starting: false,
    source: "folder",
    importId: null,
    minYears: null,
    runId: null,
  };

  function $(id) { return document.getElementById(id); }
  function faNum(v) { return window.App.faNum(v); }
  function accepted(name) {
    var l = name.toLowerCase();
    return ACCEPTED.some(function (e) { return l.slice(-e.length) === e; });
  }

  function showError(msg) {
    var el = $("setup-error");
    el.textContent = msg || "";
    el.hidden = !msg;
    if (msg) el.focus();
  }

  function hasCriterion() {
    return state.minYears !== null && Number.isFinite(state.minYears) && state.minYears >= 0;
  }
  function folderReady() { return state.fileCount > 0 && !state.uploading && !state.starting; }

  function refreshStart() {
    var ready = folderReady() && hasCriterion();
    $("start-btn").disabled = !ready;
    ["folder-btn", "excel-btn", "source-folder", "source-jobinja"].forEach(function (id) {
      $(id).disabled = state.uploading || state.starting;
    });
    $("start-hint").textContent = ready
      ? "همه‌چیز آماده است — " + faNum(state.fileCount) + " فایل برای بررسی."
      : state.uploading
        ? "در حال بارگذاری فایل‌ها…"
        : "منبع رزومه‌ها و حداقل سابقه کار را مشخص کنید.";
  }

  function setStatus(text, isError) {
    var el = $("folder-status");
    el.textContent = text || "";
    el.classList.toggle("is-error", !!isError);
  }

  /* ------------------------------------------------------ folder summary */
  function renderSummary() {
    var box = $("folder-summary");
    if (!state.fileCount) { box.hidden = true; return; }
    box.hidden = false;
    $("picked-name").textContent = state.folderName || "—";
    $("picked-count").textContent =
      faNum(state.fileCount) + " فایل" +
      (state.skipped ? " · " + faNum(state.skipped) + (state.source === "jobinja" ? " ردیف نامعتبر" : " فایل نادیده گرفته شد") : "");
    $("dz-title").textContent = state.folderName || "انتخاب پوشه رزومه‌ها";
    $("folder-btn").classList.add("is-done");
  }

  function clearFolder() {
    state.folderName = "";
    state.fileCount = 0;
    state.skipped = 0;
    state.uploadId = null;
    state.importId = null;
    state.uploading = false;
    $("folder-summary").hidden = true;
    $("folder-btn").classList.remove("is-done");
    $("dz-title").textContent = "انتخاب پوشه رزومه‌ها";
    setStatus("", false);
    refreshStart();
  }

  /* -------------------------------------------------------------- upload */
  function upload(files) {
    showError("");
    var usable = [], skipped = 0;
    Array.prototype.forEach.call(files, function (f) {
      if (accepted(f.name)) usable.push(f); else skipped++;
    });

    if (!usable.length) {
      clearFolder();
      setStatus(skipped
        ? "در این پوشه فایل PDF یا DOCX پیدا نشد."
        : "پوشه انتخاب‌شده خالی است.", true);
      return;
    }

    var tooLarge = usable.some(function (f) { return f.size > 32 * 1024 * 1024; });
    var totalBytes = usable.reduce(function (sum, f) { return sum + f.size; }, 0);
    var limitError = usable.length > 500 ? "حداکثر ۵۰۰ فایل را انتخاب کنید."
      : tooLarge ? "حجم هر فایل باید حداکثر ۳۲ مگابایت باشد."
      : totalBytes > 512 * 1024 * 1024 ? "حجم کل فایل‌ها باید حداکثر ۵۱۲ مگابایت باشد." : "";
    if (limitError) {
      clearFolder();
      setStatus(limitError, true);
      showError(limitError);
      return;
    }

    var rel = usable[0].webkitRelativePath || "";
    state.folderName = rel.split("/")[0] || usable[0].name;
    state.skipped = skipped;
    state.uploading = true;
    state.fileCount = 0;
    state.uploadId = null;
    $("folder-btn").classList.add("is-done");
    setStatus("در حال بارگذاری " + faNum(usable.length) + " فایل…");
    refreshStart();

    var form = new FormData();
    usable.forEach(function (f) {
      // Send the folder-relative path so two resumes that share a file name in
      // different sub-folders stay distinct on the server.
      form.append("files", f, f.webkitRelativePath || f.name);
    });

    fetch("/api/uploads", { method: "POST", body: form })
      .catch(function () {
        throw new Error("بارگذاری انجام نشد. پنجره ResumeCheck را باز نگه دارید و مطمئن شوید فایل‌های انتخاب‌شده روی این رایانه قابل خواندن‌اند.");
      })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          if (!res.ok) throw new Error(body.detail || ("بارگذاری ناموفق بود (" + res.status + ")"));
          return body;
        });
      })
      .then(function (data) {
        state.uploadId = data.uploadId;
        state.fileCount = data.fileCount;
        if (data.folderName) state.folderName = data.folderName;
        if (typeof data.skipped === "number") state.skipped = data.skipped;
        state.uploading = false;
        setStatus("");
        renderSummary();
        refreshStart();
      })
      .catch(function (err) {
        clearFolder();
        setStatus(err.message || "بارگذاری فایل‌ها ناموفق بود.", true);
        showError(err.message || "بارگذاری فایل‌ها ناموفق بود.");
        refreshStart();
      });
  }

  function changeSource(source) {
    if (state.uploading || state.starting) return;
    state.source = source;
    clearFolder();
    $("folder-panel").hidden = source !== "folder";
    $("jobinja-panel").hidden = source !== "jobinja";
    showError("");
  }

  async function uploadExcel(file) {
    clearFolder();
    showError("");
    if (!file || !/\.xlsx$/i.test(file.name)) { showError("فایل Excel با پسوند XLSX انتخاب کنید."); return; }
    if (file.size > 10 * 1024 * 1024) { showError("حجم Excel باید حداکثر ۱۰ مگابایت باشد."); return; }
    state.uploading = true;
    refreshStart();
    setStatus("در حال خواندن ردیف‌های Excel…");
    var form = new FormData();
    form.append("file", file, file.name);
    try {
      var response = await fetch("/api/jobinja/imports", { method: "POST", body: form });
      var data = await response.json();
      if (!response.ok) throw new Error(data.detail || "خواندن Excel ناموفق بود.");
      state.importId = data.importId;
      state.folderName = data.folderName || file.name;
      state.fileCount = data.total;
      state.skipped = data.failed;
      renderSummary();
      setStatus(data.failed ? faNum(data.failed) + " ردیف لینک معتبر ندارد؛ در گزارش دریافت مشخص می‌شود." : "");
    } catch (error) {
      showError(error instanceof TypeError ? "ارتباط با ResumeCheck برقرار نشد؛ برنامه را باز نگه دارید." : error.message);
      setStatus("خواندن Excel ناموفق بود.", true);
    } finally {
      state.uploading = false;
      refreshStart();
    }
  }

  /* ----------------------------------------------------------------- run */
  function start() {
    // Guards against double submission while uploading or already running.
    if (state.starting) return;
    showError("");
    if (!folderReady()) { showError("ابتدا پوشه رزومه‌ها یا Excel جابینجا را انتخاب کنید."); return; }
    if (!hasCriterion()) { showError("حداقل سابقه کار را با یک عدد نامنفی مشخص کنید."); return; }

    var criteria = {
      minYears: state.minYears === null || state.minYears === "" ? null : state.minYears,
    };

    state.starting = true;
    refreshStart();
    $("start-btn").disabled = true;

    var endpoint = state.source === "jobinja"
      ? "/api/jobinja/imports/" + encodeURIComponent(state.importId) + "/run"
      : "/api/uploads/" + encodeURIComponent(state.uploadId) + "/run";
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ criteria: criteria }),
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          if (!res.ok) throw new Error(body.detail || ("شروع بررسی ناموفق بود (" + res.status + ")"));
          return body;
        });
      })
      .then(function (data) {
        state.runId = data.runId;
        if (state.source === "jobinja") window.App.progress.beginImport(state.importId, state.folderName, criteria);
        else window.App.progress.begin(data.runId, state.folderName, criteria);
      })
      .catch(function (err) {
        state.starting = false;
        showError(err.message || "شروع بررسی ممکن نشد.");
        refreshStart();
      });
  }

  function resetToSetup(keep) {
    $("screen-progress").hidden = true;
    $("screen-results").hidden = true;
    $("screen-setup").hidden = false;
    state.starting = false;
    if (!keep || state.source === "jobinja") clearFolder();
    refreshStart();
    showError("");
  }

  function init() {
    $("folder-btn").addEventListener("click", function () {
      var input = $("folder-input");
      input.value = "";
      input.click();
    });
    $("folder-reset-btn").addEventListener("click", clearFolder);
    $("folder-input").addEventListener("change", function (e) {
      if (e.target.files && e.target.files.length) upload(e.target.files);
    });

    ["source-folder", "source-jobinja"].forEach(function (id) {
      $(id).addEventListener("change", function (event) { changeSource(event.target.value); });
    });
    $("excel-btn").addEventListener("click", function () {
      $("excel-input").value = "";
      $("excel-input").click();
    });
    $("excel-input").addEventListener("change", function (event) {
      if (event.target.files && event.target.files.length) uploadExcel(event.target.files[0]);
    });
    $("min-years").addEventListener("input", function (e) {
      var v = e.target.value;
      state.minYears = v === "" ? null : Number(v);
      refreshStart();
    });
    $("start-btn").addEventListener("click", start);
    refreshStart();
  }

  window.App.setup = { state: state, resetToSetup: resetToSetup };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
