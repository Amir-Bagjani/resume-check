/* Results dashboard + resume viewer. */
(function () {
  "use strict";

  var rows = [];
  var runId = null;
  var activeFilter = "all";
  var query = "";

  // Scroll offsets kept per row key so closing the viewer restores the table.
  var scrollMemory = {};
  var lastFocused = null;
  var zoom = 1;

  function $(id) {
    var el = document.getElementById(id);
    // Guard so one missing node cannot break the whole dashboard render.
    if (!el) console.warn("missing element: #" + id);
    return el;
  }
  function text(id, value) {
    var el = $(id);
    if (el) el.textContent = value;
  }
  function faNum(v) { return window.App.faNum(v); }
  function list(v) { return Array.isArray(v) ? v.join("، ") : (v || ""); }

  var STATUS_FA = { Qualified: "تأییدشده", "Not Qualified": "ردشده", Undetermined: "نیازمند بررسی" };
  var STATUS_CLS = { Qualified: "ok", "Not Qualified": "bad", Undetermined: "warn" };

  function criteriaSummary(d) {
    var parts = [];
    var c = d.criteria || {};
    if (c.minYears !== null && c.minYears !== undefined && c.minYears !== "") {
      parts.push("حداقل " + faNum(c.minYears) + " سال");
    }
    if (c.keywords && c.keywords.length) parts.push(c.keywords.join("، "));
    return parts.join(" · ") || d.criteriaUsedFa || "—";
  }

  /* ------------------------------------------------------------- viewer */

  function rowKey(r) {
    // Stable identity, never the visible index: filtering reorders the list.
    return r.filename || r.candidateName || "";
  }

  function openViewer(r) {
    var key = rowKey(r);
    if (!key) return;

    scrollMemory[key] = window.scrollY;
    lastFocused = document.activeElement;

    var viewer = $("viewer");
    var body = $("viewer-body");
    var isPdf = /\.pdf$/i.test(key);

    $("viewer-title").textContent = r.candidateName || key;
    var badge = $("viewer-badge");
    badge.textContent = STATUS_FA[r.finalStatus] || "";
    badge.className = "badge " + (STATUS_CLS[r.finalStatus] || "warn");

    var src = "/api/runs/" + encodeURIComponent(runId) + "/resumes/" + encodeURIComponent(key);
    var dl = $("viewer-download");
    dl.href = src + "?download=true";
    dl.setAttribute("download", key);
    dl.setAttribute("title", "دانلود " + key);

    // Zoom only applies to the embedded PDF frame.
    $("viewer-zoom-in").hidden = !isPdf;
    $("viewer-zoom-out").hidden = !isPdf;
    $("viewer-zoom-label").hidden = !isPdf;
    zoom = 1;
    $("viewer-zoom-label").textContent = "۱۰۰٪";

    body.textContent = "";
    if (isPdf) {
      var frame = document.createElement("iframe");
      frame.id = "viewer-frame";
      frame.src = src;
      frame.title = "پیش‌نمایش رزومه " + key;
      // The browser's own PDF plugin loads the file; if it cannot, the frame stays
      // empty. A GET probe confirms reachability without relying on HEAD, which the
      // API does not answer.
      fetch(src).then(function (res) {
        if (!res.ok) showViewerError(res.status);
      }).catch(function () { showViewerError(0); });
      body.appendChild(frame);
    } else {
      // Browsers cannot render DOCX; offer the file instead of a broken frame.
      var box = document.createElement("div");
      box.className = "viewer-fallback";
      box.innerHTML =
        '<span class="fb-ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
        'stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
        '<path d="M14 2v6h6"/></svg></span>' +
        '<h3>پیش‌نمایش این قالب در مرورگر ممکن نیست</h3>' +
        '<p>این فایل از نوع Word است. برای مشاهده کامل آن، فایل را باز یا دانلود کنید.</p>' +
        '<a class="btn primary" href="' + src + '?download=true" download="' + key.replace(/"/g, "") + '">' +
        'باز کردن و دانلود فایل</a>';
      body.appendChild(box);
    }

    viewer.hidden = false;
    document.body.style.overflow = "hidden";
    $("viewer-close").focus();
  }

  function showViewerError(status) {
    var body = $("viewer-body");
    body.textContent = "";
    var box = document.createElement("div");
    box.className = "viewer-error";
    box.innerHTML =
      '<p>' + (status
        ? "این رزومه در دسترس نیست."
        : "ارتباط با سرور برقرار نشد.") + '</p>' +
      '<p style="font-weight:600;color:var(--text-soft)">فایل ممکن است حذف شده باشد یا دسترسی به آن ممکن نباشد.</p>';
    body.appendChild(box);
  }

  function closeViewer() {
    var viewer = $("viewer");
    if (viewer.hidden) return;
    var frame = $("viewer-frame");
    if (frame) frame.src = "about:blank"; // release the PDF resource
    $("viewer-body").textContent = "";
    viewer.hidden = true;
    document.body.style.overflow = "";
    if (lastFocused && lastFocused.focus) lastFocused.focus();
    var key = null;
    // Restore the scroll position of whichever row opened the viewer.
    for (var k in scrollMemory) { key = k; }
    if (key) {
      var target = document.querySelector('[data-row-key="' + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]');
      if (target && scrollMemory[key]) {
        target.scrollIntoView({ block: "center", behavior: "instant" });
      }
    }
  }

  function setZoom(delta) {
    zoom = Math.min(2, Math.max(0.5, Math.round((zoom + delta) * 10) / 10));
    var frame = $("viewer-frame");
    if (frame) frame.style.transform = "scale(" + zoom + ")";
    $("viewer-zoom-label").textContent = faNum(Math.round(zoom * 100)) + "٪";
  }

  /* -------------------------------------------------------------- table */

  function renderTable() {
    var body = $("results-body");
    if (!body) return;
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
      var key = rowKey(r);
      var tr = document.createElement("tr");
      tr.setAttribute("data-row-key", key);

      // Candidate
      var name = document.createElement("td");
      var wrap = document.createElement("div");
      wrap.className = "cell-name";
      var strong = document.createElement("strong");
      strong.textContent = r.candidateName || key;
      strong.dir = r.candidateName ? "auto" : "ltr";
      wrap.appendChild(strong);
      if (r.candidateName) {
        var file = document.createElement("span");
        file.textContent = key;
        file.dir = "auto";
        wrap.appendChild(file);
      }
      name.appendChild(wrap);
      tr.appendChild(name);

      // Declared experience
      var years = document.createElement("td");
      years.className = "c-years";
      var val = document.createElement("span");
      var declared = r.declaredExperienceYears;
      if (declared === null || declared === undefined) {
        val.className = "years-val is-unknown";
        val.textContent = "نامشخص";
      } else {
        val.className = "years-val";
        val.textContent = r.declaredExperienceYearsFa || (faNum(declared) + " سال");
      }
      years.appendChild(val);
      tr.appendChild(years);

      // Status badge
      var status = document.createElement("td");
      var badge = document.createElement("span");
      badge.className = "badge " + (STATUS_CLS[r.finalStatus] || "warn");
      badge.textContent = r.finalStatusFa || STATUS_FA[r.finalStatus] || "—";
      status.appendChild(badge);
      tr.appendChild(status);

      // Reason
      var reason = document.createElement("td");
      var rc = document.createElement("div");
      rc.className = "reason-cell";
      rc.textContent = r.reason || "—";
      rc.title = r.reason || "";   // full text on hover
      reason.appendChild(rc);
      tr.appendChild(reason);

      // Actions — the view button exists for every row regardless of status.
      var act = document.createElement("td");
      act.className = "c-act";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "view-btn";
      btn.setAttribute("aria-label", "مشاهده رزومه " + (r.candidateName || key));
      btn.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" ' +
        'stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z"/>' +
        '<circle cx="12" cy="12" r="2.6"/></svg><span>مشاهده رزومه</span>';
      btn.addEventListener("click", function () { openViewer(r); });
      act.appendChild(btn);
      tr.appendChild(act);

      body.appendChild(tr);
    });

    text("results-count",
      shown === rows.length
        ? "همه " + faNum(rows.length) + " رزومه نمایش داده می‌شود."
        : faNum(shown) + " رزومه از " + faNum(rows.length) + " مورد نمایش داده می‌شود.");
    if ($("results-empty")) $("results-empty").hidden = shown !== 0;
  }

  function show(d) {
    rows = d.results || [];
    runId = d.runId || null;
    $("screen-progress").hidden = true;
    $("screen-setup").hidden = true;
    $("screen-results").hidden = false;

    text("s-found", faNum(d.found || 0));
    text("s-qualified", faNum(d.qualified || 0));
    text("s-not", faNum(d.notQualified !== undefined ? d.notQualified : (d.not_qualified || 0)));
    text("s-und", faNum(d.undetermined || 0));

    text("results-criteria", criteriaSummary(d));
    text("results-date", d.screeningDateJalaliLong || d.screeningDateJalali || "—");

    var ready = (d.state === "finished" || d.state === "cancelled") && !!runId;
    if ($("download-report-btn")) $("download-report-btn").disabled = !ready;

    var err = $("results-error");
    if (err) {
      if (d.error) { err.textContent = d.error; err.hidden = false; }
      else { err.hidden = true; err.textContent = ""; }
    }

    renderTable();
    $("results-heading").focus();
  }

  function init() {
    document.querySelectorAll(".filter-chip, .chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        activeFilter = chip.getAttribute("data-filter");
        document.querySelectorAll(".chip").forEach(function (c) {
          var on = c === chip;
          c.classList.toggle("is-active", on);
          c.setAttribute("aria-pressed", on ? "true" : "false");
        });
        renderTable();
      });
    });

    $("table-search").addEventListener("input", function (e) {
      query = e.target.value;
      renderTable();
    });

    $("download-report-btn").addEventListener("click", function () {
      if (!runId) return;
      saveReportAs(runId);
    });

    // Save As: on supporting browsers the OS dialog lets the user pick the
    // location and file name; elsewhere the file downloads with the suggested
    // name. Cancellation is silent, success and real errors get Persian text.
    function saveReportAs(id) {
      var note = function (msg) { var el = $("copy-confirm"); if (el) el.textContent = msg; };
      note("");
      fetch("/api/runs/" + encodeURIComponent(id) + "/report-name")
        .then(function (r) { return r.json(); })
        .then(function (body) {
          var fileName = (body && body.fileName) || "screening-report.xlsx";
          if (window.showSaveFilePicker) {
            return saveWithPicker(id, fileName, note);
          }
          standardDownload(id, fileName);
          note("گزارش Excel در حال دانلود است.");
        })
        .catch(function () {
          standardDownload(id, "screening-report.xlsx");
          note("مرورگر شما انتخاب مسیر را پشتیبانی نمی‌کند؛ فایل با نام پیش‌فرض در پوشه دانلودها ذخیره می‌شود.");
        });
    }

    function standardDownload(id, fileName) {
      var a = document.createElement("a");
      a.href = "/api/runs/" + encodeURIComponent(id) + "/report";
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
    }

    function saveWithPicker(id, fileName, note) {
      var ext = fileName.slice(fileName.lastIndexOf(".")).toLowerCase();
      var opts = {
        suggestedName: fileName,
        types: [{
          description: "Excel",
          accept: { "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [ext || ".xlsx"] }
        }]
      };
      var handleRef = null;
      window.showSaveFilePicker(opts).then(function (handle) {
        handleRef = handle;
        return fetch("/api/runs/" + encodeURIComponent(id) + "/report");
      }).then(function (res) {
        if (!res.ok) throw new Error("report");
        return res.blob();
      }).then(function (blob) {
        return handleRef.createWritable().then(function (writable) {
          return writable.write(blob).then(function () { return writable.close(); });
        });
      }).then(function () { note("فایل Excel با موفقیت ذخیره شد."); })
        .catch(function (err) {
          if (err && err.name === "AbortError") return; // user pressed Cancel: save nothing
          // Picker opened but the write failed: fall back so the user still gets the file.
          standardDownload(id, fileName);
          note("ذخیره در مسیر انتخابی ناموفق بود؛ فایل با نام پیش‌فرض دانلود شد.");
        });
    }

    $("new-run-btn").addEventListener("click", function () {
      activeFilter = "all";
      query = "";
      $("table-search").value = "";
      document.querySelectorAll(".chip").forEach(function (c) {
        var on = c.getAttribute("data-filter") === "all";
        c.classList.toggle("is-active", on);
        c.setAttribute("aria-pressed", on ? "true" : "false");
      });
      window.App.setup.resetToSetup(true);
    });

    // Viewer wiring
    $("viewer-close").addEventListener("click", closeViewer);
    document.querySelector("[data-close]").addEventListener("click", closeViewer);
    $("viewer-zoom-in").addEventListener("click", function () { setZoom(0.1); });
    $("viewer-zoom-out").addEventListener("click", function () { setZoom(-0.1); });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeViewer();
      if (e.key === "Tab" && !$("viewer").hidden) {
        // Keep focus inside the dialog.
        var f = $("viewer").querySelectorAll("button, a[href]");
        if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
  }

  window.App = window.App || {};
  window.App.results = { show: show };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();