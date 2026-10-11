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
    keywords: [],
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
    return state.keywords.length > 0 || (state.minYears !== null && state.minYears !== "");
  }
  function folderReady() { return state.fileCount > 0 && !state.uploading && !state.starting; }

  function refreshStart() {
    var ready = folderReady() && hasCriterion();
    $("start-btn").disabled = !ready;
    $("folder-btn").disabled = state.uploading || state.starting;
    $("start-hint").textContent = ready
      ? "همه‌چیز آماده است — " + faNum(state.fileCount) + " فایل برای بررسی."
      : state.uploading
        ? "در حال بارگذاری فایل‌ها…"
        : "برای شروع، پوشه را انتخاب کنید و حداقل یک معیار تعیین کنید.";
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
      (state.skipped ? " · " + faNum(state.skipped) + " فایل نادیده گرفته شد" : "");
    $("dz-title").textContent = state.folderName || "انتخاب پوشه رزومه‌ها";
    $("folder-btn").classList.add("is-done");
  }

  function clearFolder() {
    state.folderName = "";
    state.fileCount = 0;
    state.skipped = 0;
    state.uploadId = null;
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

  /* ------------------------------------------------------------ keywords */
  function renderChips() {
    var ul = $("keyword-chips");
    ul.textContent = "";
    state.keywords.forEach(function (kw) {
      var li = document.createElement("li");
      li.appendChild(document.createTextNode(kw));
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = "✕";
      b.setAttribute("aria-label", "حذف " + kw);
      b.addEventListener("click", function () {
        state.keywords = state.keywords.filter(function (k) { return k !== kw; });
        renderChips();
        refreshStart();
      });
      li.appendChild(b);
      ul.appendChild(li);
    });
    refreshStart();
  }

  function addKeyword() {
    var input = $("keyword-input");
    var v = input.value.trim();
    if (!v) return;
    var dup = state.keywords.some(function (k) { return k.toLowerCase() === v.toLowerCase(); });
    if (dup) { input.value = ""; input.focus(); return; }
    state.keywords.push(v);
    input.value = "";
    input.focus();
    renderChips();
  }

  /* ----------------------------------------------------------------- run */
  function start() {
    // Guards against double submission while uploading or already running.
    if (state.starting) return;
    showError("");
    if (!folderReady()) { showError("ابتدا یک پوشه حاوی رزومه انتخاب کنید."); return; }
    if (!hasCriterion()) { showError("حداقل یک معیار تعیین کنید: سابقه کار یا فناوری موردنیاز."); return; }

    var criteria = {
      minYears: state.minYears === null || state.minYears === "" ? null : state.minYears,
      keywords: state.keywords.slice(),
    };

    state.starting = true;
    refreshStart();
    $("start-btn").disabled = true;

    fetch("/api/uploads/" + encodeURIComponent(state.uploadId) + "/run", {
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
        window.App.progress.begin(data.runId, state.folderName, criteria);
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
    if (!keep) clearFolder();
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

    $("keyword-add-btn").addEventListener("click", addKeyword);
    $("keyword-input").addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); addKeyword(); }
    });
    $("min-years").addEventListener("input", function (e) {
      var v = e.target.value;
      state.minYears = v === "" ? null : Number(v);
      refreshStart();
    });
    $("start-btn").addEventListener("click", start);
    renderChips();
    refreshStart();
  }

  window.App.setup = { state: state, resetToSetup: resetToSetup };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
