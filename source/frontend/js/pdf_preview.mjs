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
      onError(0, "نمایش این PDF ممکن نشد. فایل ممکن است خراب یا رمزگذاری‌شده باشد.");
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
    try {
      // No PDF URL navigation, PDF MIME type, or download filename in this request.
      response = await fetch("/api/runs/" + encodeURIComponent(runId) + "/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }), signal,
      });
      if (!response.ok) {
        onError(response.status);
        return;
      }
      const data = new Uint8Array(await response.arrayBuffer());
      if (signal.aborted) return;
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
        console.error("PDF preview failed:", error);
        onError(0, response && response.ok
          ? "نمایش این PDF ممکن نشد. فایل ممکن است خراب یا رمزگذاری‌شده باشد."
          : "ارتباط با سرور برقرار نشد.");
      }
    }
  })();

  return { setZoom(value) { if (ready) viewer.currentScale = baseScale * value; } };
}
