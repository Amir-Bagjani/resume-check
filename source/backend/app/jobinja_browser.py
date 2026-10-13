"""Run Jobinja's JavaScript waiting page in an isolated installed browser."""
from http.cookiejar import Cookie
import json
import urllib.parse

from .jobinja import JobinjaError, MAX_HTML_BYTES, _check_destination


def render_resume_page(url, cookies, trace):
    try:
        from playwright.sync_api import Error, TimeoutError, sync_playwright
    except ModuleNotFoundError:
        trace.append("مرورگر: Playwright در این نسخه نصب نیست؛ فقط حل داخلی چالش کوکی در دسترس است.")
        raise JobinjaError("برای باز کردن این صفحه به Playwright نیاز است؛ نسخه‌ی معمولی برنامه بدون آن کار می‌کند.") from None
    try:
        with sync_playwright() as playwright:
            browser = None
            for channel in ("chrome", "msedge"):
                try:
                    browser = playwright.chromium.launch(channel=channel, headless=True, timeout=20000)
                    trace.append(f"مرورگر: {channel}؛ پروفایل موقت و مستقل")
                    break
                except Error:
                    trace.append(f"مرورگر {channel} قابل اجرا نیست.")
            if browser is None:
                raise JobinjaError("صفحهٔ جابینجا به JavaScript نیاز دارد؛ Chrome یا Microsoft Edge را نصب کنید و دوباره تلاش کنید.")
            try:
                context = browser.new_context(locale="fa-IR", timezone_id="Asia/Tehran", service_workers="block")
                context.add_cookies([
                    {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "secure": c.secure}
                    for c in cookies
                ])
                blocked = []
                navigation_count = 0

                def receive(route):
                    nonlocal navigation_count
                    try:
                        target = route.request.url
                        # HTTP redirect requests can bypass routing; follow them here.
                        for _ in range(6):
                            _check_destination(target)
                            if route.request.is_navigation_request():
                                navigation_count += 1
                                if navigation_count > 6:
                                    raise JobinjaError("تعداد تغییر مسیرهای مرورگر بیش از حد مجاز است.")
                            response = route.fetch(url=target, max_redirects=0, timeout=20000)
                            if route.request.is_navigation_request():
                                trace.append(f"مرورگر: HTTP {response.status}؛ دامنه={urllib.parse.urlsplit(target).hostname}")
                            location = response.headers.get("location")
                            if response.status not in (301, 302, 303, 307, 308) or not location:
                                break
                            target = urllib.parse.urljoin(target, location)
                        else:
                            raise JobinjaError("تعداد تغییر مسیرهای مرورگر بیش از حد مجاز است.")
                        if route.request.is_navigation_request():
                            if len(response.body()) > MAX_HTML_BYTES:
                                raise JobinjaError("حجم صفحهٔ دریافت‌شده در مرورگر بیش از حد مجاز است.")
                            if target != route.request.url:
                                destination = json.dumps(target).replace("<", "\\u003c")
                                route.fulfill(status=200, content_type="text/html",
                                              body=f"<script>location.replace({destination})</script>")
                                return
                        route.fulfill(response=response)
                    except Exception as exc:
                        if route.request.is_navigation_request():
                            blocked.append(exc)
                        route.abort()

                context.route("**/*", receive)
                context.route_web_socket("**/*", lambda websocket: websocket.close())
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_function("""() => Array.from(document.querySelectorAll('a[href]')).some(a =>
                        a.hasAttribute('download') || /دانلود|download/i.test(
                            a.textContent + ' ' + (a.title || '') + ' ' + (a.getAttribute('aria-label') || '')))
                    """, timeout=20000)
                except TimeoutError:
                    trace.append("انتظار مرورگر برای لینک دانلود پس از ۲۰ ثانیه پایان یافت.")
                except Error:
                    if not blocked:
                        raise
                if blocked:
                    error = blocked[0]
                    if isinstance(error, JobinjaError):
                        raise error
                    trace.append(f"خطای درخواست مرورگر: {type(error).__name__}")
                    raise JobinjaError("دریافت صفحه در مرورگر ناموفق بود؛ اتصال اینترنت را بررسی کنید.")
                _check_destination(page.url)
                html = page.content()
                if len(html.encode("utf-8")) > MAX_HTML_BYTES:
                    raise JobinjaError("حجم صفحهٔ دریافت‌شده در مرورگر بیش از حد مجاز است.")
                for c in context.cookies():
                    expires = int(c["expires"]) if c["expires"] > 0 else None
                    cookies.set_cookie(Cookie(
                        version=0, name=c["name"], value=c["value"], port=None, port_specified=False,
                        domain=c["domain"], domain_specified=c["domain"].startswith("."),
                        domain_initial_dot=c["domain"].startswith("."), path=c["path"], path_specified=True,
                        secure=c["secure"], expires=expires, discard=expires is None,
                        comment=None, comment_url=None, rest={"HttpOnly": c["httpOnly"]},
                    ))
                trace.append("صفحهٔ مرورگر دریافت شد؛ کوکی‌ها برای دانلود حفظ شدند (مقادیر مخفی).")
                return html, page.url
            finally:
                browser.close()
    except JobinjaError:
        raise
    except Exception as exc:
        trace.append(f"خطای اجرای مرورگر: {type(exc).__name__}")
        raise JobinjaError("اجرای مرورگر برای دریافت رزومه ناموفق بود؛ نصب Chrome یا Edge و اتصال اینترنت را بررسی کنید.") from None
