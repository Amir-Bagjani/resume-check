import { AnnotationMode, GlobalWorkerOptions, getDocument } from "../vendor/pdfjs/pdf.min.mjs";
import { EventBus, PDFLinkService, PDFViewer } from "../vendor/pdfjs/pdf_viewer.mjs";

const assets = new URL("../vendor/pdfjs/", import.meta.url).href;
GlobalWorkerOptions.workerSrc = assets + "pdf.worker.min.mjs";

export function openPreview(body, runId, filename, signal, onReady, onError) {
  const container = document.createElement("div");
  container.className = "viewer-pdf";
  container.dir = "ltr";
  container.tabIndex = 0;
  container.setAttribute("aria-label", "پیش‌نمایش رزومه " + filename);
  const pages = document.createElement("div");
  pages.className = "pdfViewer";
  container.appendChild(pages);
  body.appendChild(container);

  const eventBus = new EventBus();
  const linkService = new PDFLinkService({ eventBus });
  linkService.externalLinkEnabled = false;
  const viewer = new PDFViewer({
    container, viewer: pages, eventBus, linkService, abortSignal: signal,
    annotationMode: AnnotationMode.ENABLE,
    imageResourcesPath: assets + "images/",
  });
  linkService.setViewer(viewer);
  let loadingTask = null;
  let baseScale = 1;
  let ready = false;

  eventBus.on("pagesinit", () => {
    viewer.currentScaleValue = "page-width";
    baseScale = viewer.currentScale;
  }, { signal });
  eventBus.on("pagerendered", ({ error }) => {
    if (error) {
      console.error("PDF preview [page render]:", error);
      onError(0, "رندر صفحه PDF ناموفق بود. جزئیات در کنسول مرورگر ثبت شده است.");
    } else if (!ready) {
      ready = true;
      onReady();
    }
  }, { signal });

  signal.addEventListener("abort", () => {
    viewer.setDocument(null);
    linkService.setDocument(null);
    viewer.l10n.destroy().catch(console.error);
    if (loadingTask) loadingTask.destroy().catch(console.error);
  }, { once: true });

  (async () => {
    let response;
    let stage = "HTTP request";
    try {
      // No PDF URL navigation, PDF MIME type, or download filename in this request.
      response = await fetch("/api/runs/" + encodeURIComponent(runId) + "/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }), signal,
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        console.error("PDF preview [HTTP request]:", response.status, detail.code || "http_error");
        onError(response.status, typeof detail.detail === "string" ? detail.detail : "دریافت PDF از سرور ناموفق بود.");
        return;
      }
      stage = "PDF bytes";
      const data = new Uint8Array(await response.arrayBuffer());
      if (signal.aborted) return;
      if (!data.length) throw new Error("Empty PDF response");
      stage = "worker initialization";
      const worker = await fetch(GlobalWorkerOptions.workerSrc, { method: "HEAD", signal });
      if (!worker.ok) throw new Error("PDF worker asset HTTP " + worker.status);
      if (!/^(text|application)\/(javascript|ecmascript)(;|$)/i.test(worker.headers.get("Content-Type") || "")) {
        throw new Error("PDF worker asset has an invalid JavaScript MIME type");
      }
      stage = "PDF parsing/worker";
      loadingTask = getDocument({
        data, cMapUrl: assets + "cmaps/", cMapPacked: true,
        standardFontDataUrl: assets + "standard_fonts/", wasmUrl: assets + "wasm/",
        isEvalSupported: false,
      });
      const pdf = await loadingTask.promise;
      if (signal.aborted) return;
      linkService.setDocument(pdf);
      viewer.setDocument(pdf);
    } catch (error) {
      if (!signal.aborted) {
        console.error("PDF preview [" + stage + "]:", error);
        const workerFailed = stage === "worker initialization" || /worker/i.test(error.message || "");
        onError(0, workerFailed
          ? "راه‌اندازی پردازشگر PDF ناموفق بود. فایل worker و نوع محتوای آن را بررسی کنید."
          : stage === "HTTP request" ? "ارتباط با سرور برقرار نشد."
          : stage === "PDF bytes" ? "داده‌های PDF دریافت نشد."
          : error.name === "PasswordException" ? "این PDF رمزگذاری‌شده است و برای پیش‌نمایش به نسخه بدون رمز نیاز دارد."
          : "خواندن PDF ناموفق بود. فایل ممکن است نامعتبر یا خراب باشد.");
      }
    }
  })();

  return { setZoom(value) { if (ready) viewer.currentScale = baseScale * value; } };
}
