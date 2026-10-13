const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function setup(fetch) {
  const elements = new Map();
  const document = {
    readyState: "complete",
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, {
        listeners: {}, value: "", textContent: "", hidden: true,
        classList: { add() {}, remove() {}, toggle() {} }, focus() {},
        addEventListener(event, handler) { this.listeners[event] = handler; },
      });
      return elements.get(id);
    },
  };
  const began = [];
  const window = { App: { progress: {
    begin(...args) { began.push(["folder", ...args]); },
    beginImport(...args) { began.push(["jobinja", ...args]); },
  } } };
  class FormData {
    constructor() { this.files = []; }
    append(field, file, name) { this.files.push({ field, file, name }); }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../js/app_setup.js"), "utf8"),
    { window, document, fetch, FormData });
  return {
    state: window.App.setup.state,
    began,
    reset: window.App.setup.resetToSetup,
    el: (id) => document.getElementById(id),
    async upload(files) {
      document.getElementById("folder-input").listeners.change({ target: { files } });
      await new Promise(setImmediate);
    },
  };
}

const file = (size = 1, name = "cv.pdf") => ({ name, size, webkitRelativePath: "رزومه ها/تیم/" + name });

for (const [label, files, message] of [
  ["oversize file", [file(32 * 1024 * 1024 + 1)], "۳۲"],
  ["too many files", Array.from({ length: 501 }, () => file()), "۵۰۰"],
  ["oversize folder", Array.from({ length: 17 }, () => file(32 * 1024 * 1024)), "۵۱۲"],
]) {
  test("rejects " + label + " before making a network request", async () => {
    let requests = 0;
    const app = setup(() => { requests++; throw new Error("unexpected fetch"); });
    await app.upload(files);
    assert.equal(requests, 0);
    assert.match(app.el("setup-error").textContent, new RegExp(message));
    assert.equal(app.state.uploadId, null);
    assert.equal(app.el("start-btn").disabled, true);
  });
}

test("uploads supported files with their Persian relative paths", async () => {
  let sent;
  const app = setup(async (url, options) => {
    assert.equal(url, "/api/uploads");
    sent = options.body.files;
    return { ok: true, json: async () => ({ uploadId: "batch", fileCount: 1 }) };
  });
  await app.upload([file(1, "cv.DOCX"), file(1, "report.xlsx")]);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].name, "رزومه ها/تیم/cv.DOCX");
  assert.equal(app.state.fileCount, 1);
  assert.equal(app.state.uploading, false);
});

test("network failure gives actionable text and the next upload clears it", async () => {
  let fail = true;
  const app = setup(async () => {
    if (fail) throw new TypeError("Failed to fetch");
    return { ok: true, json: async () => ({ uploadId: "batch", fileCount: 1 }) };
  });
  await app.upload([file()]);
  assert.match(app.el("setup-error").textContent, /ResumeCheck/);
  assert.doesNotMatch(app.el("setup-error").textContent, /Failed to fetch/);
  assert.equal(app.state.uploadId, null);
  assert.equal(app.state.uploading, false);
  fail = false;
  await app.upload([file()]);
  assert.equal(app.el("setup-error").hidden, true);
  assert.equal(app.state.uploadId, "batch");
});

test("preserves the server's disk permission error", async () => {
  const message = "دسترسی و فضای دیسک را بررسی کنید.";
  const app = setup(async () => ({ ok: false, status: 507, json: async () => ({ detail: message }) }));
  await app.upload([file()]);
  assert.equal(app.el("setup-error").textContent, message);
});

test("switching source clears the old input and only shows the selected panel", async () => {
  const app = setup(async () => ({ ok: true, json: async () => ({ uploadId: "folder", fileCount: 1 }) }));
  await app.upload([file()]);
  app.el("source-jobinja").listeners.change({ target: { value: "jobinja" } });
  assert.equal(app.state.uploadId, null);
  assert.equal(app.state.source, "jobinja");
  assert.equal(app.el("folder-panel").hidden, true);
  assert.equal(app.el("jobinja-panel").hidden, false);
  assert.equal(app.el("start-btn").disabled, true);
});

test("Excel upload waits for start and sends only the minimum-experience criterion", async () => {
  const requests = [];
  const app = setup(async (url, options) => {
    requests.push([url, options]);
    return { ok: true, json: async () => url === "/api/jobinja/imports"
      ? { importId: "excel", total: 3, failed: 1, folderName: "جابینجا.xlsx" }
      : { importId: "excel", state: "downloading" } };
  });
  app.el("source-jobinja").listeners.change({ target: { value: "jobinja" } });
  app.el("excel-input").listeners.change({ target: { files: [{ name: "جابینجا.xlsx", size: 10 }] } });
  await new Promise(setImmediate);
  assert.equal(requests.length, 1);
  assert.equal(app.state.importId, "excel");
  assert.equal(app.el("start-btn").disabled, true);
  app.el("min-years").listeners.input({ target: { value: "5" } });
  assert.equal(app.el("start-btn").disabled, false);
  app.el("start-btn").listeners.click();
  await new Promise(setImmediate);
  assert.equal(requests[1][0], "/api/jobinja/imports/excel/run");
  assert.deepEqual(JSON.parse(requests[1][1].body), { criteria: { minYears: 5 } });
  assert.equal(app.began[0][0], "jobinja");
  assert.equal(app.began[0][1], "excel");
  assert.equal(app.state.keywords, undefined);
  app.reset(true);
  assert.equal(app.state.importId, null, "A new run must ask for an Excel rather than restart a finished import");
  assert.equal(app.el("start-btn").disabled, true);
});

test("negative or nonnumeric minimum cannot start a folder run", async () => {
  const app = setup(async () => ({ ok: true, json: async () => ({ uploadId: "folder", fileCount: 1 }) }));
  await app.upload([file()]);
  for (const value of ["", "-1", "NaN", "Infinity"]) {
    app.el("min-years").listeners.input({ target: { value } });
    assert.equal(app.el("start-btn").disabled, true);
  }
  app.el("min-years").listeners.input({ target: { value: "0" } });
  assert.equal(app.el("start-btn").disabled, false);
});
