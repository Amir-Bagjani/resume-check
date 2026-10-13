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
  var previewSession = null;
  var exportReady = false;
  var exporting = false;
  var reviewPending = null;
  var viewerKey = null;

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

  function validJobinjaUrl(value) {
    try {
      var url = new URL(value);
      return url.protocol === "https:" && !url.username && !url.password && (!url.port || url.port === "443") &&
        (url.hostname === "jobinja.ir" || url.hostname.endsWith(".jobinja.ir"));
    } catch (_) { return false; }
  }

  function criteriaSummary(d) {
    var parts = [];
    var c = d.criteria || {};
    if (c.minYears !== null && c.minYears !== undefined && c.minYears !== "") {
      parts.push("حداقل " + faNum(c.minYears) + " سال");
    }
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
    releasePreview();

    scrollMemory[key] = window.scrollY;
    lastFocused = document.activeElement;

    var viewer = $("viewer");
    var body = $("viewer-body");
    var isPdf = /\.pdf$/i.test(key);
    viewerKey = key;
    $("viewer-review-error").hidden = true;

    $("viewer-title").textContent = r.candidateName || key;
    var badge = $("viewer-badge");
    badge.textContent = STATUS_FA[r.finalStatus] || "";
    badge.className = "badge " + (STATUS_CLS[r.finalStatus] || "warn");

    var src = "/api/runs/" + encodeURIComponent(runId) + "/resumes/" + encodeURIComponent(key);
    var dl = $("viewer-download");
    dl.href = src + "?download=true";
    dl.setAttribute("download", key);
    dl.setAttribute("title", "دانلود " + key);

    // Zoom applies to PDF.js pages inside the existing dialog.
    $("viewer-zoom-in").hidden = !isPdf;
    $("viewer-zoom-out").hidden = !isPdf;
    $("viewer-zoom-label").hidden = !isPdf;
    $("viewer-zoom-in").disabled = true;
    $("viewer-zoom-out").disabled = true;
    zoom = 1;
    $("viewer-zoom-label").textContent = "۱۰۰٪";

    body.textContent = "";
    if (isPdf) {
      var loading = document.createElement("div");
      loading.className = "viewer-loading";
      loading.setAttribute("role", "status");
      loading.textContent = "در حال بارگذاری پیش‌نمایش…";
      body.appendChild(loading);
      var session = { controller: new AbortController(), preview: null };
      previewSession = session;
      import("./pdf_preview.mjs").then(function (module) {
        if (previewSession !== session) return;
        session.preview = module.openPreview(body, runId, key, session.controller.signal,
          function () {
            if (previewSession !== session) return;
            loading.remove();
            $("viewer-zoom-in").disabled = false;
            $("viewer-zoom-out").disabled = false;
          },
          function (status, message) {
            if (previewSession === session) showViewerError(status, message);
          });
      }).catch(function (error) {
        if (previewSession !== session) return;
        console.error("PDF preview [module/viewer initialization]:", error);
        showViewerError(0, "بارگذاری نمایشگر PDF ناموفق بود. فایل‌های برنامه یا نوع محتوای آن‌ها را بررسی کنید؛ جزئیات در کنسول مرورگر ثبت شده است.");
      });
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
    renderViewerReview();
    document.body.style.overflow = "hidden";
    $("viewer-close").focus();
  }

  function releasePreview() {
    if (previewSession) previewSession.controller.abort();
    previewSession = null;
  }

  function showViewerError(status, message) {
    releasePreview();
    $("viewer-zoom-in").disabled = true;
    $("viewer-zoom-out").disabled = true;
    var body = $("viewer-body");
    body.textContent = "";
    var box = document.createElement("div");
    box.className = "viewer-error";
    box.setAttribute("role", "alert");
    var note = document.createElement("p");
    note.textContent = message || (status === 404
      ? "فایل این رزومه یافت نشد."
      : "ارتباط با سرور برقرار نشد.");
    box.appendChild(note);
    body.appendChild(box);
  }

  function closeViewer() {
    var viewer = $("viewer");
    if (viewer.hidden) return;
    releasePreview();
    $("viewer-body").textContent = "";
    viewer.hidden = true;
    viewerKey = null;
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
    if (previewSession && previewSession.preview) previewSession.preview.setZoom(zoom);
    $("viewer-zoom-label").textContent = faNum(Math.round(zoom * 100)) + "٪";
  }

  /* -------------------------------------------------------------- table */

  var CATEGORY_STATUS = { all: null, approved: "Qualified", rejected: "Not Qualified", "needs-review": "Undetermined" };
  var REVIEW_LABELS = { approved: "تأیید", rejected: "رد", "needs-review": "نیازمند بررسی" };
  // The decision buttons borrow the status column colours so the two agree.
  var REVIEW_CLS = { approved: "ok", rejected: "bad", "needs-review": "warn" };

  function createReviewActions(row) {
    var actions = document.createElement("div");
    actions.className = "review-actions";
    Object.keys(REVIEW_LABELS).forEach(function (decision) {
      if (CATEGORY_STATUS[decision] === row.finalStatus) return;
      var action = document.createElement("button");
      action.type = "button";
      action.className = "view-btn review-btn " + REVIEW_CLS[decision];
      action.setAttribute("data-review", decision);
      action.textContent = reviewPending && reviewPending.filename === rowKey(row) && reviewPending.decision === decision
        ? "در حال ذخیره…" : REVIEW_LABELS[decision];
      action.setAttribute("aria-label", REVIEW_LABELS[decision] + " رزومه " + (row.candidateName || rowKey(row)));
      action.disabled = !exportReady || exporting || !!reviewPending;
      action.addEventListener("click", function () { reviewResume(row, decision); });
      actions.appendChild(action);
    });
    return actions;
  }

  function renderViewerReview() {
    if (!viewerKey) return;
    var row = rows.find(function (r) { return rowKey(r) === viewerKey; });
    if (!row) return;
    var actions = $("viewer-review-actions");
    var focused = actions.contains(document.activeElement);
    actions.replaceChildren(createReviewActions(row));
    var badge = $("viewer-badge");
    badge.textContent = row.finalStatusFa || STATUS_FA[row.finalStatus];
    badge.className = "badge " + STATUS_CLS[row.finalStatus];
    if (focused) $("viewer-close").focus();
  }

  function updateExportButtons() {
    document.querySelectorAll("[data-export]").forEach(function (button) {
      var status = CATEGORY_STATUS[button.getAttribute("data-export")];
      var count = rows.filter(function (row) { return status === null || row.finalStatus === status; }).length;
      button.disabled = !exportReady || exporting || !!reviewPending || count === 0;
      button.title = count ? "دانلود " + faNum(count) + " رزومه همراه گزارش Excel" : "در این دسته رزومه‌ای وجود ندارد.";
    });
    document.querySelectorAll("[data-review]").forEach(function (button) {
      button.disabled = !exportReady || exporting || !!reviewPending;
    });
    $("download-report-btn").disabled = !exportReady || !!reviewPending;
    $("new-run-btn").disabled = !!reviewPending;
  }

  async function reviewResume(row, decision) {
    if (!exportReady || exporting || reviewPending) return;
    var id = runId;
    reviewPending = { filename: rowKey(row), decision: decision };
    $("results-error").hidden = true;
    $("viewer-review-error").hidden = true;
    renderTable();
    renderViewerReview();
    updateExportButtons();
    try {
      var response = await fetch("/api/runs/" + encodeURIComponent(id) + "/review", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: rowKey(row), decision: decision }),
      });
      var data = await response.json();
      if (!response.ok) throw new Error(data.detail || "ذخیره تصمیم ناموفق بود.");
      if (runId === id) show(data);
    } catch (error) {
      if (runId === id) {
        var message = $("results-error");
        message.textContent = error instanceof TypeError
          ? "ارتباط با سرور برقرار نشد؛ تصمیم تأیید نشده است. دوباره تلاش کنید."
          : (error.message || "ذخیره تصمیم ناموفق بود.");
        message.hidden = false;
        if (viewerKey === rowKey(row)) {
          $("viewer-review-error").textContent = message.textContent;
          $("viewer-review-error").hidden = false;
        }
      }
    } finally {
      reviewPending = null;
      renderTable();
      renderViewerReview();
      updateExportButtons();
    }
  }

  async function downloadCategory(category) {
    if (!exportReady || exporting || reviewPending) return;
    var id = runId;
    var fileName = category + "-resumes.zip";
    var status = $("export-status");
    var progress = $("export-progress");
    var writable = null;
    var reader = null;
    var failureLocation = "picker";
    var controller = new AbortController();
    exporting = true;
    updateExportButtons();
    status.hidden = false;
    status.className = "hint";
    status.textContent = "در حال آماده‌سازی ZIP شامل رزومه‌ها و گزارش Excel…";
    progress.hidden = false;
    progress.removeAttribute("value");
    try {
      // Open the native picker during the button gesture, before preparing the ZIP.
      var handle = window.showSaveFilePicker ? await window.showSaveFilePicker({
        suggestedName: fileName,
        types: [{ description: "ZIP", accept: { "application/zip": [".zip"] } }],
      }) : null;
      failureLocation = "server";
      var response = await fetch("/api/runs/" + encodeURIComponent(id) + "/export/" + category, { signal: controller.signal });
      if (!response.ok) {
        var error = await response.json().catch(function () { return {}; });
        throw new Error(typeof error.detail === "string" ? error.detail : "ساخت خروجی ZIP ناموفق بود.");
      }
      failureLocation = "disk";
      if (handle) writable = await handle.createWritable();
      reader = response.body.getReader();
      var chunks = [];
      var received = 0;
      var total = Number(response.headers.get("Content-Length"));
      while (true) {
        failureLocation = "transfer";
        var chunk = await reader.read();
        if (chunk.done) break;
        failureLocation = "disk";
        if (writable) await writable.write(chunk.value);
        else chunks.push(chunk.value);
        received += chunk.value.byteLength;
        if (total) {
          progress.value = Math.min(100, Math.round(received / total * 100));
          status.textContent = "در حال دریافت ZIP… " + faNum(progress.value) + "٪";
        }
      }
      if (total && received !== total) throw new Error("دریافت ZIP ناقص بود؛ دوباره تلاش کنید.");
      if (writable) {
        failureLocation = "disk";
        await writable.close();
        writable = null;
        status.textContent = "ZIP شامل رزومه‌ها و گزارش Excel ذخیره شد.";
      } else {
        var url = URL.createObjectURL(new Blob(chunks, { type: "application/zip" }));
        var link = document.createElement("a");
        link.href = url;
        link.download = fileName;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
        status.textContent = "ZIP آماده شد و به دانلودهای مرورگر ارسال شد.";
      }
    } catch (error) {
      console.error("ZIP download failed", { location: failureLocation, error: error });
      controller.abort();
      if (writable) await writable.abort().catch(function () {});
      if (error.name === "AbortError") status.textContent = "دانلود لغو شد.";
      else {
        status.className = "hint is-error";
        status.textContent = failureLocation === "disk" || failureLocation === "picker"
          ? "ذخیره ZIP در مرورگر ناموفق بود؛ فضای دیسک و دسترسی به پوشه مقصد را بررسی کنید. " + (error.message || "")
          : error instanceof TypeError
          ? "ارتباط با سرور برقرار نشد؛ اتصال را بررسی کنید و دوباره تلاش کنید."
          : (error.message || "دانلود ZIP ناموفق بود؛ دوباره تلاش کنید.");
      }
    } finally {
      if (reader) reader.releaseLock();
      progress.hidden = true;
      exporting = false;
      updateExportButtons();
    }
  }

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

      // Row number, counting the visible rows from one.
      var index = document.createElement("td");
      index.className = "c-index";
      index.textContent = faNum(shown);
      index.setAttribute("aria-label", "ردیف " + faNum(shown));
      tr.appendChild(index);

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
      // Two tidy rows: the file actions, then the review decisions.
      var act = document.createElement("td");
      act.className = "c-act";
      var stack = document.createElement("div");
      stack.className = "act-stack";
      var fileRow = document.createElement("div");
      fileRow.className = "act-row";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "view-btn";
      btn.setAttribute("aria-label", "مشاهده رزومه " + (r.candidateName || key));
      btn.textContent = "مشاهده رزومه";
      btn.addEventListener("click", function () { openViewer(r); });
      fileRow.appendChild(btn);
      if (r.jobinjaUrl && validJobinjaUrl(r.jobinjaUrl)) {
        var jobinjaLink = document.createElement("a");
        jobinjaLink.className = "view-btn jobinja-link";
        jobinjaLink.textContent = "جابینجا";
        jobinjaLink.href = r.jobinjaUrl;
        jobinjaLink.target = "_blank";
        jobinjaLink.rel = "noopener noreferrer";
        fileRow.appendChild(jobinjaLink);
      }
      stack.appendChild(fileRow);
      stack.appendChild(createReviewActions(r));
      act.appendChild(stack);
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
    if (viewerKey && d.runId !== runId) closeViewer();
    rows = d.results || [];
    runId = d.runId || null;
    try { sessionStorage.setItem("resumecheck-run", runId || ""); } catch (_) {}
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
    exportReady = ready;
    updateExportButtons();

    var err = $("results-error");
    if (err) {
      if (d.error) { err.textContent = d.error; err.hidden = false; }
      else { err.hidden = true; err.textContent = ""; }
    }

    renderTable();
    renderViewerReview();
    var failures = $("download-failures");
    failures.textContent = "";
    failures.hidden = !(d.downloadFailures && d.downloadFailures.length);
    if (!failures.hidden) {
      var title = document.createElement("strong");
      title.textContent = faNum(d.downloadFailures.length) + " رزومه دریافت نشد؛ این موارد ارزیابی نشده‌اند.";
      failures.appendChild(title);
      var details = document.createElement("details");
      var summary = document.createElement("summary");
      summary.textContent = "جزئیات خطاها و گزارش دریافت";
      details.appendChild(summary);
      d.downloadFailures.forEach(function (failure) {
        var item = document.createElement("p");
        item.textContent = (failure.candidateName || "متقاضی ردیف " + faNum(failure.excelRow)) + " — " + failure.reason;
        details.appendChild(item);
      });
      failures.appendChild(details);
    }
    if (!viewerKey) $("results-heading").focus();
  }

  function init() {
    document.querySelectorAll("[data-export]").forEach(function (button) {
      button.addEventListener("click", function () { downloadCategory(button.getAttribute("data-export")); });
    });
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
      try { sessionStorage.removeItem("resumecheck-run"); } catch (_) {}
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

    var savedRun = null;
    try { savedRun = sessionStorage.getItem("resumecheck-run"); } catch (_) {}
    if (savedRun) {
      fetch("/api/runs/" + encodeURIComponent(savedRun), { cache: "no-store" })
        .then(function (response) {
          if (response.status === 404) {
            try { sessionStorage.removeItem("resumecheck-run"); } catch (_) {}
          }
          return response.ok ? response.json() : null;
        })
        .then(function (data) {
          if (data && !runId && (data.state === "finished" || data.state === "cancelled") && !window.App.setup.state.starting) show(data);
        })
        .catch(function (error) { console.error("Results restore failed:", error); });
    }

    // Viewer wiring
    $("viewer-close").addEventListener("click", closeViewer);
    document.querySelector("[data-close]").addEventListener("click", closeViewer);
    $("viewer-zoom-in").addEventListener("click", function () { setZoom(0.1); });
    $("viewer-zoom-out").addEventListener("click", function () { setZoom(-0.1); });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeViewer();
      if (e.key === "Tab" && !$("viewer").hidden) {
        // Keep focus inside the dialog.
        var f = Array.from($("viewer").querySelectorAll("button:not([disabled]), a[href], [tabindex='0']"))
          .filter(function (el) { return !el.hidden; });
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
