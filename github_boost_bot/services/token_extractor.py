"""
services/token_extractor.py
═══════════════════════════════════════════════════════════════
طبقة موحدة لاستخراج التوكن من كوكيز فيسبوك

الطرق بالترتيب:
  1. HTTP Fast    — httpx مباشر على صفحات BM/AdsManager
  2. HTTP Deep    — صفحات إضافية + headers محسّنة
  3. Playwright   — متصفح حقيقي + network interception + JS scan

تُرجع:
  {
    "success": True,
    "dtsg": str,           # fb_dtsg (للـ GraphQL الداخلي)
    "eaa_token": str,      # EAA... access token (للـ Graph API)
    "user_id": str,        # c_user
    "method": str,         # الطريقة التي نجحت
  }
  أو {"success": False, "error": str}
═══════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import random
from typing import Any, Dict, List, Optional

import httpx

# Playwright اختياري — إذا مش مثبت بيشتغل بدونه
try:
    from playwright.async_api import async_playwright, TimeoutError as PwTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False


# ══════════════════════════════════════════
#  ثوابت
# ══════════════════════════════════════════

BM_BASE = "https://business.facebook.com"
FB_BASE = "https://www.facebook.com"

# الصفحات اللي بنجرب نسحب منها التوكن
HTTP_TARGETS = [
    f"{BM_BASE}/",
    f"{BM_BASE}/overview",
    f"{BM_BASE}/billing/",
    f"{BM_BASE}/business_settings",
    f"{BM_BASE}/latest/adsmanager",
    f"{FB_BASE}/",
    f"{FB_BASE}/me",
]

PW_TARGETS = [
    f"{BM_BASE}/latest/adsmanager",
    f"{BM_BASE}/overview",
    f"{BM_BASE}/billing/",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

# ── Regex patterns ──
DTSG_PATTERNS = [
    r'"DTSGInitialData"\s*,\s*\[\s*\]\s*,\s*\{"token"\s*:\s*"([^"]+)"',
    r'"DTSGInitialData"[^}]*?"token"\s*:\s*"([^"]{20,})"',
    r'"DTSGInitData"\s*,\s*\[\s*\]\s*,\s*\{"token"\s*:\s*"([^"]+)"',
    r'require\s*\(\s*["\']DTSGInitialData["\']\s*\).*?token["\']?\s*[=:]\s*["\']([^"\']{20,})',
    r'name="fb_dtsg"\s+value="([^"]{20,})"',
    r'"fb_dtsg"\s*:\s*"([^"]{20,})"',
    r'"fb_dtsg":\{"value"\s*:\s*"([^"]{20,})"',
    r'"dtsg"\s*:\s*"([^"]{20,})"',
    r'"token"\s*:\s*"([a-zA-Z0-9_\-]{24,})"',
    r'fb_dtsg["\']?\s*[=:]\s*["\']?([a-zA-Z0-9_\-]{20,})',
]

EAA_PATTERN = re.compile(r'EAA[a-zA-Z0-9]{30,}')

USER_ID_PATTERNS = [
    r'"ACCOUNT_ID"\s*:\s*"(\d{10,})"',
    r'"USER_ID"\s*:\s*"(\d{10,})"',
    r'c_user=(\d{10,})',
    r'"userID"\s*:\s*"(\d{10,})"',
    r'"uid"\s*:\s*(\d{10,})',
]


# ══════════════════════════════════════════
#  Cookie helpers
# ══════════════════════════════════════════

def parse_cookies_str(s: str) -> dict:
    """تحليل الكوكيز من أي تنسيق."""
    if not s:
        return {}
    s = s.strip()
    if s.lower().startswith("cookie:"):
        s = s[7:]
    s = s.replace("\n", ";").replace("\r", "")
    if s.startswith("{") and s.endswith("}"):
        try:
            d = json.loads(s)
            if isinstance(d, dict):
                return {str(k).strip(): str(v).strip() for k, v in d.items()}
        except Exception:
            pass
    result = {}
    skip = {"secure","httponly","samesite","path","domain","expires","max-age","partitioned","priority"}
    for part in s.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        if not key or key.lower() in skip:
            continue
        try:
            val = urllib.parse.unquote(val.strip())
        except Exception:
            pass
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        result[key] = val
    return result


def _get_proxies(proxy: Optional[str]) -> Optional[dict]:
    if not proxy:
        return None
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return {"http://": proxy, "https://": proxy}


def _build_headers(ua: Optional[str] = None) -> dict:
    return {
        "User-Agent": ua or random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }


# ══════════════════════════════════════════
#  Regex extraction helpers
# ══════════════════════════════════════════

def _extract_dtsg(html: str) -> Optional[str]:
    if not html or len(html) < 100:
        return None
    for pattern in DTSG_PATTERNS:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            tok = m.group(1).strip()
            if len(tok) >= 20:
                return tok
    return None


def _extract_eaa(text: str) -> Optional[str]:
    matches = EAA_PATTERN.findall(text)
    if matches:
        longest = max(matches, key=len)
        if len(longest) >= 50:
            return longest
    return None


def _extract_user_id(html: str, cookies: dict) -> Optional[str]:
    uid = cookies.get("c_user", "")
    if uid and uid.isdigit():
        return uid
    for pattern in USER_ID_PATTERNS:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _is_valid_session(text: str, url: str) -> bool:
    url_l = url.lower()
    text_l = text.lower()
    bad_url = any(k in url_l for k in ["login.php", "/login", "/checkpoint", "/recover"])
    bad_txt = any(k in text_l for k in ["please log in", "session expired", "must be logged in"])
    return not bad_url and not bad_txt


# ══════════════════════════════════════════
#  Method 1: HTTP Fast
# ══════════════════════════════════════════

async def _method_http(
    cookies_dict: dict,
    proxy: Optional[str],
    targets: List[str],
    timeout: int = 20,
) -> Optional[Dict[str, Any]]:
    """محاولة سريعة بـ httpx على عدة صفحات."""
    proxies = _get_proxies(proxy)
    headers = _build_headers()

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            proxies=proxies,
            follow_redirects=True,
        ) as client:
            for url in targets:
                try:
                    resp = await client.get(url, headers=headers, cookies=cookies_dict)
                    text = resp.text
                    final_url = str(resp.url)

                    if resp.status_code != 200:
                        continue
                    if not _is_valid_session(text, final_url):
                        continue

                    dtsg = _extract_dtsg(text)
                    eaa  = _extract_eaa(text)
                    uid  = _extract_user_id(text, cookies_dict)

                    if dtsg or eaa:
                        return {
                            "success":   True,
                            "dtsg":      dtsg,
                            "eaa_token": eaa,
                            "user_id":   uid,
                            "source_url": final_url,
                        }
                except Exception:
                    continue
    except Exception:
        pass
    return None


# ══════════════════════════════════════════
#  Method 2: HTTP Deep (أكثر صفحات + GraphQL)
# ══════════════════════════════════════════

async def _method_http_deep(
    cookies_dict: dict,
    cookies_str: str,
    proxy: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    محاولة أعمق:
    - صفحات إضافية
    - طلب GraphQL بسيط لاستخراج الـ DTSG
    """
    # صفحات إضافية لم تُجرَّب
    extra_targets = [
        f"{BM_BASE}/business_locations",
        f"{BM_BASE}/business_settings/pages/",
        f"{FB_BASE}/ads/manager/",
        f"{FB_BASE}/adsmanager/manage/",
    ]
    res = await _method_http(cookies_dict, proxy, extra_targets, timeout=25)
    if res:
        return res

    # جرب GraphQL endpoint مباشرة
    proxies = _get_proxies(proxy)
    try:
        async with httpx.AsyncClient(
            timeout=25,
            proxies=proxies,
            follow_redirects=True,
        ) as client:
            # استخراج DTSG من صفحة BM أولاً
            resp = await client.get(
                f"{BM_BASE}/",
                headers=_build_headers(),
                cookies=cookies_dict,
            )
            if resp.status_code == 200 and _is_valid_session(resp.text, str(resp.url)):
                dtsg = _extract_dtsg(resp.text)
                eaa  = _extract_eaa(resp.text)
                uid  = _extract_user_id(resp.text, cookies_dict)
                if dtsg:
                    return {
                        "success":   True,
                        "dtsg":      dtsg,
                        "eaa_token": eaa,
                        "user_id":   uid,
                        "source_url": str(resp.url),
                    }
    except Exception:
        pass
    return None


# ══════════════════════════════════════════
#  Method 3: Playwright
# ══════════════════════════════════════════

# JavaScript يسحب التوكنات من localStorage + sessionStorage + window
_JS_SCAN_STORAGE = """
() => {
    const out = { dtsg: null, eaa: [], user_id: null };
    const dtsgPat = /[a-zA-Z0-9_\\-]{24,}/;
    const eaaPat  = /EAA[a-zA-Z0-9]{30,}/g;

    // localStorage + sessionStorage
    [localStorage, sessionStorage].forEach(store => {
        try {
            for (let i = 0; i < store.length; i++) {
                const k = store.key(i);
                const v = store.getItem(k);
                if (!v || typeof v !== 'string') continue;
                if (/dtsg|fb_dtsg/i.test(k) && dtsgPat.test(v) && !out.dtsg)
                    out.dtsg = v;
                const ms = v.match(eaaPat);
                if (ms) ms.forEach(t => { if (!out.eaa.includes(t)) out.eaa.push(t); });
                if (/user_id|account_id|c_user/i.test(k) && /^\\d{10,}$/.test(v))
                    out.user_id = v;
            }
        } catch(e){}
    });

    // window globals
    try {
        const win = window;
        for (const k of Object.keys(win)) {
            try {
                const v = win[k];
                if (typeof v === 'string') {
                    if (/EAA[a-zA-Z0-9]{30,}/.test(v) && !out.eaa.includes(v)) out.eaa.push(v);
                }
                if (v && typeof v === 'object' && !Array.isArray(v)) {
                    const s = JSON.stringify(v);
                    const ms = s.match(eaaPat);
                    if (ms) ms.forEach(t => { if (!out.eaa.includes(t)) out.eaa.push(t); });
                }
            } catch(e){}
        }
    } catch(e){}

    // require() scan (Facebook internal module system)
    try {
        const mods = ['DTSGInitialData','DTSGInitData'];
        for (const m of mods) {
            try {
                const d = window.require(m);
                if (d && d.token && !out.dtsg) out.dtsg = d.token;
            } catch(e){}
        }
    } catch(e){}

    // __initialData string scan
    try {
        if (typeof window.__initialData === 'string') {
            const ms = window.__initialData.match(eaaPat);
            if (ms) ms.forEach(t => { if (!out.eaa.includes(t)) out.eaa.push(t); });
        }
    } catch(e){}

    return out;
}
"""

async def _method_playwright(
    cookies_dict: dict,
    proxy: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Playwright: متصفح حقيقي + network interception + JS scan."""
    if not PLAYWRIGHT_OK:
        return None

    collected_dtsg: list = []
    collected_eaa:  list = []

    # تحويل cookies إلى playwright format
    pw_cookies = [
        {
            "name":     k,
            "value":    v,
            "domain":   ".facebook.com",
            "path":     "/",
            "sameSite": "Lax",
        }
        for k, v in cookies_dict.items()
        if k and v
    ]

    proxy_cfg = None
    if proxy:
        raw = proxy if "://" in proxy else f"http://{proxy}"
        # parse: http://user:pass@host:port
        m = re.match(r"https?://(?:([^:@]+):([^@]+)@)?([^:]+):(\d+)", raw)
        if m:
            user, pwd, host, port = m.groups()
            proxy_cfg = {"server": f"http://{host}:{port}"}
            if user:
                proxy_cfg["username"] = user
            if pwd:
                proxy_cfg["password"] = pwd

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                proxy=proxy_cfg,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                locale="en-US",
                timezone_id="America/New_York",
                viewport={"width": 1440, "height": 900},
                user_agent=random.choice(USER_AGENTS),
            )
            await ctx.add_cookies(pw_cookies)
            page = await ctx.new_page()

            # ── Network interception ──────────────────
            async def on_response(resp):
                try:
                    url = resp.url
                    if not any(k in url for k in [
                        "graphql", "business.facebook", "api/graphql",
                        "graph.facebook", "adsmanager",
                    ]):
                        return
                    try:
                        body = await resp.text()
                    except Exception:
                        return
                    # DTSG من network
                    dtsg = _extract_dtsg(body)
                    if dtsg and dtsg not in collected_dtsg:
                        collected_dtsg.append(dtsg)
                    # EAA tokens
                    for t in EAA_PATTERN.findall(body):
                        if len(t) >= 50 and t not in collected_eaa:
                            collected_eaa.append(t)
                except Exception:
                    pass

            page.on("response", on_response)

            # ── Navigation ───────────────────────────
            for target in PW_TARGETS:
                try:
                    await page.goto(target, wait_until="networkidle", timeout=40_000)
                    await page.wait_for_timeout(2_000)

                    if not _is_valid_session(await page.content(), page.url):
                        continue

                    # DTSG من HTML مباشرة
                    html = await page.content()
                    dtsg = _extract_dtsg(html)
                    if dtsg and dtsg not in collected_dtsg:
                        collected_dtsg.append(dtsg)

                    # EAA من HTML
                    for t in EAA_PATTERN.findall(html):
                        if len(t) >= 50 and t not in collected_eaa:
                            collected_eaa.append(t)

                    # JS scan
                    try:
                        js_result = await page.evaluate(_JS_SCAN_STORAGE)
                        if js_result.get("dtsg") and js_result["dtsg"] not in collected_dtsg:
                            collected_dtsg.insert(0, js_result["dtsg"])
                        for t in js_result.get("eaa", []):
                            if t not in collected_eaa:
                                collected_eaa.append(t)
                        js_uid = js_result.get("user_id")
                    except Exception:
                        js_uid = None

                    if collected_dtsg or collected_eaa:
                        break
                except PwTimeout:
                    continue
                except Exception:
                    continue

            await browser.close()

        if collected_dtsg or collected_eaa:
            uid = cookies_dict.get("c_user") or js_uid if 'js_uid' in dir() else cookies_dict.get("c_user")
            return {
                "success":   True,
                "dtsg":      collected_dtsg[0] if collected_dtsg else None,
                "eaa_token": collected_eaa[0]  if collected_eaa  else None,
                "user_id":   uid,
                "source_url": "playwright",
            }
    except Exception:
        pass
    return None


# ══════════════════════════════════════════
#  الدالة الرئيسية الموحدة
# ══════════════════════════════════════════

async def extract_token(
    cookies_str: str,
    proxy: Optional[str] = None,
    use_playwright: bool = True,
    timeout_per_method: int = 30,
) -> Dict[str, Any]:
    """
    استخراج التوكن من الكوكيز بثلاث طرق متتالية.

    المعاملات:
        cookies_str       : الكوكيز كنص
        proxy             : بروكسي اختياري
        use_playwright    : هل نستخدم Playwright كـ fallback؟
        timeout_per_method: timeout لكل طريقة بالثواني

    الإرجاع:
        dict يحتوي على:
          success    : bool
          dtsg       : str | None   (fb_dtsg للـ GraphQL الداخلي)
          eaa_token  : str | None   (EAA للـ Graph API)
          user_id    : str | None
          method     : str          (http_fast / http_deep / playwright)
          error      : str          (فقط عند الفشل)
    """
    cookies_dict = parse_cookies_str(cookies_str)
    if not cookies_dict:
        return {"success": False, "error": "الكوكيز فارغة أو غير صالحة"}

    uid_from_cookies = cookies_dict.get("c_user", "")

    # ── Method 1: HTTP Fast ──────────────────────────────────────
    try:
        res = await asyncio.wait_for(
            _method_http(cookies_dict, proxy, HTTP_TARGETS[:5]),
            timeout=timeout_per_method,
        )
        if res:
            res["method"]  = "http_fast"
            res["user_id"] = res.get("user_id") or uid_from_cookies
            return res
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass

    # ── Method 2: HTTP Deep ──────────────────────────────────────
    try:
        res = await asyncio.wait_for(
            _method_http_deep(cookies_dict, cookies_str, proxy),
            timeout=timeout_per_method,
        )
        if res:
            res["method"]  = "http_deep"
            res["user_id"] = res.get("user_id") or uid_from_cookies
            return res
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass

    # ── Method 3: Playwright ─────────────────────────────────────
    if use_playwright and PLAYWRIGHT_OK:
        try:
            res = await asyncio.wait_for(
                _method_playwright(cookies_dict, proxy),
                timeout=timeout_per_method + 30,
            )
            if res:
                res["method"]  = "playwright"
                res["user_id"] = res.get("user_id") or uid_from_cookies
                return res
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

    # ── فشل كل الطرق ─────────────────────────────────────────────
    # آخر محاولة: على الأقل أرجع بيانات الكوكيز الأساسية
    c_user = cookies_dict.get("c_user", "")
    xs     = cookies_dict.get("xs", "")
    if c_user and xs:
        return {
            "success":   True,
            "dtsg":      None,
            "eaa_token": None,
            "user_id":   c_user,
            "method":    "cookies_only",
            "_warning":  "لم يُعثر على DTSG — الأدوات الداخلية ستعمل بالكوكيز فقط",
        }

    return {
        "success": False,
        "error": (
            "فشلت جميع طرق استخراج التوكن.\n"
            "• تأكد من أن الكوكيز تحتوي على c_user و xs\n"
            "• تأكد من أن الجلسة لا تزال نشطة\n"
            "• جرب نسخ الكوكيز من جديد من متصفح مفتوح على facebook.com"
        ),
    }


def format_token_result(res: dict) -> str:
    """تنسيق رسالة نجاح/فشل الاستخراج للـ Telegram."""
    if not res.get("success"):
        return f"❌ <b>فشل استخراج التوكن</b>\n\n{res.get('error', 'خطأ غير معروف')}"

    method_icons = {
        "http_fast":    "⚡ HTTP سريع",
        "http_deep":    "🔍 HTTP عميق",
        "playwright":   "🌐 Playwright",
        "cookies_only": "🍪 كوكيز فقط",
    }
    method_lbl = method_icons.get(res.get("method", ""), res.get("method", ""))

    dtsg  = res.get("dtsg")
    eaa   = res.get("eaa_token")
    uid   = res.get("user_id", "—")

    lines = [
        f"✅ <b>تم استخراج التوكن</b> [{method_lbl}]",
        "",
        f"👤 User ID: <code>{uid}</code>",
        f"🔑 DTSG:    {'✅ موجود' if dtsg else '⚠️ غير موجود'}",
        f"🎟️ EAA:     {'✅ موجود' if eaa else '⚠️ غير موجود'}",
    ]
    if res.get("_warning"):
        lines.append(f"\n⚠️ <i>{res['_warning']}</i>")
    return "\n".join(lines)
