const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

// Run the actual download function with browser I/O stubs, without rendering the dashboard.
function download({ failure, backendError } = {}) {
  const source = fs.readFileSync(path.join(__dirname, "../js/app_results.js"), "utf8");
  const elements = new Map();
  const events = [];
  let index = 0;
  const writable = {
    async write(bytes) { events.push(["write", Array.from(bytes)]); if (failure === "write") throw new Error("write on disk"); },
    async close() { events.push(["close"]); if (failure === "close") throw new Error("disk full"); },
    async abort() { events.push(["abort"]); },
  };
  const context = {
    exportReady: true, exporting: false, reviewPending: null, runId: "zip-run", AbortController,
    updateExportButtons() {}, faNum: String,
    $(id) { if (!elements.has(id)) elements.set(id, { removeAttribute() {} }); return elements.get(id); },
    console: { error(...args) { events.push(["error", args[1].location]); } },
    window: { async showSaveFilePicker() { return {
      async createWritable() { events.push(["create"]); if (failure === "create") throw new Error("permission denied"); return writable; },
    }; } },
    async fetch() {
      return {
        ok: !backendError, json: async () => ({ detail: backendError }),
        headers: { get() { return "4"; } },
        body: { getReader() { return {
          async read() { return index++ < 2 ? { done: false, value: new Uint8Array([80, 75]) } : { done: true }; },
          releaseLock() { events.push(["release"]); },
        }; } },
      };
    },
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf("  async function downloadCategory("), source.indexOf("  function renderTable()")), context);
  return { run: () => context.downloadCategory("all"), events, status: () => elements.get("export-status") };
}

test("ZIP closes the browser file only after all bytes arrive", async () => {
  const app = download();
  await app.run();
  assert.deepEqual(app.events, [["create"], ["write", [80, 75]], ["write", [80, 75]], ["close"], ["release"]]);
  assert.match(app.status().textContent, /ذخیره شد/);
});

for (const failure of ["create", "write", "close"]) {
  test("ZIP browser " + failure + " error identifies the local disk", async () => {
    const app = download({ failure });
    await app.run();
    assert.match(app.status().textContent, /ذخیره ZIP در مرورگر ناموفق بود/);
    assert.equal(app.status().className, "hint is-error");
    assert.ok(app.events.some(event => event[0] === "error" && event[1] === "disk"));
    if (failure !== "create") assert.ok(app.events.some(event => event[0] === "abort"));
    assert.doesNotMatch(app.status().textContent, /ذخیره شد/);
  });
}

test("ZIP backend failure keeps the Persian error and never opens a writable file", async () => {
  const message = "خروجی کامل ساخته نشد؛ فایل رزومه در دسترس نیست.";
  const app = download({ backendError: message });
  await app.run();
  assert.equal(app.status().textContent, message);
  assert.deepEqual(app.events, [["error", "server"]]);
});
