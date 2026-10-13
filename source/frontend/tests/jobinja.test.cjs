const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function dom() {
  const elements = new Map();
  function element(tag) {
    let text = "";
    return {
      tag, children: [], attributes: {}, listeners: {}, style: {}, hidden: true,
      classList: { toggle() {}, add() {}, remove() {} }, focus() {},
      set textContent(value) { text = value; this.children = []; },
      get textContent() { return text + this.children.map(child => child.textContent).join(""); },
      appendChild(child) { this.children.push(child); },
      setAttribute(name, value) { this.attributes[name] = value; },
      getAttribute(name) { return this.attributes[name]; },
      addEventListener(event, handler) { this.listeners[event] = handler; },
    };
  }
  const document = {
    readyState: "loading", addEventListener() {},
    createElement: element,
    querySelectorAll() { return []; },
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element("div"));
      return elements.get(id);
    },
  };
  return { document, el: id => document.getElementById(id), element };
}

function walk(node) { return [node, ...node.children.flatMap(walk)]; }

test("Jobinja links keep the exact row URL in every status, alongside the resume viewer", () => {
  const app = dom();
  const window = { App: { faNum: String } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../js/app_results.js"), "utf8"),
    { window, document: app.document, URL, console, sessionStorage: { setItem() {} } });
  const statuses = ["Qualified", "Not Qualified", "Undetermined"];
  const results = statuses.map((finalStatus, index) => ({ filename: `cv-${index}.pdf`, finalStatus,
    jobinjaUrl: `https://jobinja.ir/resume/${index}?token=EXACT%2BToken&x=one+two`, candidateName: "نام" }));
  results.push({ filename: "folder.pdf", finalStatus: "Qualified" });
  results.push({ filename: "invalid.pdf", finalStatus: "Qualified", jobinjaUrl: "javascript:alert(1)" });
  window.App.results.show({ runId: "run", state: "finished", results, downloadFailures: [
    { excelRow: 7, candidateName: "نام دیگر", reason: "دریافت انجام نشد\n\nگزارش مراحل دریافت:\nHTTP 200؛ Content-Type=text/html\nلینک‌های دانلود: 0\n<script>untrusted</script>" },
  ] });
  const rows = app.el("results-body").children;
  rows.forEach((row, index) => {
    const nodes = walk(row);
    assert.ok(nodes.some(node => node.tag === "button" && node.textContent === "مشاهده رزومه"));
    const links = nodes.filter(node => node.tag === "a");
    assert.equal(links.length, index < 3 ? 1 : 0);
    if (index < 3) {
      assert.equal(links[0].href, results[index].jobinjaUrl);
      assert.equal(links[0].target, "_blank");
      assert.equal(links[0].rel, "noopener noreferrer");
      assert.equal(links[0].textContent, "جابینجا");
    }
  });
  assert.match(app.el("download-failures").textContent, /این موارد ارزیابی نشده‌اند/);
  const failure = walk(app.el("download-failures")).find(node => node.tag === "p");
  assert.ok(failure.textContent.includes("\nHTTP 200؛ Content-Type=text/html\nلینک‌های دانلود: 0"));
  assert.ok(failure.textContent.includes("<script>untrusted</script>"));
  assert.equal(failure.children.length, 0, "Diagnostics render as text, never HTML");
  assert.equal(rows.length, 5, "Failed download is separate from evaluated resumes");
});

test("real download progress switches to the existing screening poll", async () => {
  const app = dom();
  app.el("progress-fill").parentElement = app.element("div");
  let poll;
  let step = 0;
  const requests = [];
  const shown = [];
  const window = { App: { faNum: String, results: { show(data) { shown.push(data); } } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../js/app_progress.js"), "utf8"), {
    window, document: app.document,
    setInterval(callback) { poll = callback; return 1; }, clearInterval() {},
    fetch: async url => {
      requests.push(url);
      return { ok: true, json: async () => url.includes("/imports/")
        ? (step === 0 ? { state: "downloading", total: 5, completed: 3, downloaded: 2, failed: 1 }
          : { state: "screening", total: 5, completed: 5, downloaded: 4, failed: 1, runId: "screening" })
        : { state: "finished", runId: "screening", found: 4, processed: 4, qualified: 2, notQualified: 1, undetermined: 1 } };
    },
  });
  window.App.progress.beginImport("excel", "جابینجا.xlsx", { minYears: 5 });
  await new Promise(setImmediate);
  assert.equal(app.el("progress-fill").style.width, "60%");
  assert.match(app.el("progress-text").textContent, /2 رزومه از 5 دریافت شد/);
  assert.equal(app.el("pause-btn").disabled, true);
  assert.equal(app.el("progress-counters").hidden, true);
  step = 1;
  poll();
  await new Promise(setImmediate);
  assert.ok(requests.includes("/api/runs/screening"));
  assert.equal(app.el("progress-fill").style.width, "100%");
  assert.equal(app.el("progress-counters").hidden, false);
  assert.equal(shown.length, 1);
});

test("a failed report generation stops the loading poll and shows a Persian error", async () => {
  const app = dom();
  app.el("progress-fill").parentElement = app.element("div");
  let poll;
  let cleared = 0;
  const shown = [];
  const window = { App: { faNum: String, results: { show(data) { shown.push(data); } } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../js/app_progress.js"), "utf8"), {
    window, document: app.document,
    setInterval(callback) { poll = callback; return 1; },
    clearInterval() { cleared += 1; },
    fetch: async url => ({ ok: true, json: async () => url.includes("/imports/")
      ? { state: "screening", total: 5, completed: 5, downloaded: 5, failed: 0, runId: "screening" }
      : { state: "failed", runId: "screening", found: 5, processed: 5, qualified: 0, notQualified: 0,
          undetermined: 5, error: "تولید گزارش یا پوشهٔ خروجی ناموفق بود؛ جزئیات کامل در لاگ برنامه است." } }),
  });
  window.App.progress.beginImport("excel", "جابینجا.xlsx", { minYears: 5 });
  await new Promise(setImmediate);
  poll();
  await new Promise(setImmediate);
  assert.ok(cleared >= 1, "polling stops, so the UI cannot stay in loading forever");
  assert.equal(app.el("progress-error").hidden, false);
  assert.match(app.el("progress-error").textContent, /تولید گزارش/);
  assert.equal(app.el("progress-back-btn").hidden, false);
  assert.equal(shown.length, 0, "a failed run is not presented as finished results");
});

test("operation buttons are laid out as two aligned rows of four actions", () => {
  const app = dom();
  const window = { App: { faNum: String } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../js/app_results.js"), "utf8"),
    { window, document: app.document, URL, console, sessionStorage: { setItem() {} } });
  window.App.results.show({ runId: "run", state: "finished", results: [{
    filename: "cv.pdf", finalStatus: "Qualified", candidateName: "نام",
    jobinjaUrl: "https://jobinja.ir/resume/1?token=EXACT", reason: "دلیل",
  }], downloadFailures: [] });

  const row = app.el("results-body").children[0];
  assert.equal(row.children[0].className, "c-index");
  assert.equal(row.children[0].textContent, "1", "rows are numbered from one");
  const cell = row.children.find(node => node.className === "c-act");
  assert.ok(cell, "the operations cell exists");
  const stack = cell.children[0];
  assert.equal(stack.className, "act-stack");
  const [fileRow, reviewRow] = stack.children;
  assert.equal(fileRow.className, "act-row");
  assert.equal(reviewRow.className, "review-actions");
  // Two file actions and exactly two review decisions (the current status is skipped).
  assert.equal(fileRow.children.length, 2);
  assert.equal(reviewRow.children.length, 2);
  const actions = [...fileRow.children, ...reviewRow.children];
  assert.equal(actions.length, 4);
  actions.forEach(node => {
    assert.ok(node.className.split(" ").includes("view-btn"), node.className);
  });
  assert.ok(!actions.some(node => (node.className || "").includes("is-primary")));
  // Decision buttons carry the status colours: approved=ok, rejected=bad, needs-review=warn.
  assert.deepEqual(reviewRow.children.map(node => node.className.split(" ").pop()).sort(),
                   ["bad", "warn"]);
  fileRow.children.forEach(node => assert.ok(!/\bok\b|\bbad\b|\bwarn\b/.test(node.className)));
  assert.equal(fileRow.children[0].textContent, "مشاهده رزومه");
  assert.ok(!fileRow.children[0].children.some(node => node.tag === "svg"), "no icon left in the view button");
  assert.equal(fileRow.children[1].tag, "a");
  assert.equal(fileRow.children[1].textContent, "جابینجا");
  reviewRow.children.forEach(node => assert.ok(node.className.split(" ").includes("view-btn")));
});
