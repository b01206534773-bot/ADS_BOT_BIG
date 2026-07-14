"""
bm_card_service.py
خدمة تسميع البطاقات من Business Manager
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import httpx

BM_BASE = 'https://business.facebook.com'
GRAPHQL = f'{BM_BASE}/api/graphql/'
FB_BASE = 'https://www.facebook.com'
IG_BASE = 'https://www.instagram.com'

DEVICE_PROFILES = [
    {
        'ua': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'lang': 'en-US,en;q=0.9',
    },
    {
        'ua': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
        'lang': 'en-US,en;q=0.9',
    },
]


def _parse_cookies(s: str) -> dict:
    """
    تحليل الكوكيز من أي تنسيق:
      - semicolon-separated: a=1;b=2
      - newline-separated: a=1\nb=2
      - with Cookie: prefix
      - JSON values inside cookies
      - lines copied from devtools/network
      - Set-Cookie like content
    """
    if not s or not isinstance(s, str):
        return {}

    s = s.strip()
    if not s:
        return {}

    if s.lower().startswith('cookie:'):
        s = s[7:]

    if s.startswith('{') and s.endswith('}'):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                return {str(k).strip(): str(v).strip() for k, v in parsed.items() if str(k).strip()}
        except (json.JSONDecodeError, ValueError):
            pass

    s = s.replace('\r', '')
    lines = [line.strip() for line in s.split('\n') if line.strip()]
    if len(lines) > 1:
        merged_parts: List[str] = []
        for line in lines:
            if ':' in line and '=' not in line:
                continue
            merged_parts.append(line)
        s = '; '.join(merged_parts)

    result: Dict[str, str] = {}
    parts = [p.strip() for p in s.split(';') if p.strip()]
    skip_attrs = {
        'secure', 'httponly', 'samesite', 'path', 'domain', 'expires',
        'max-age', 'partitioned', 'priority', 'version'
    }

    for part in parts:
        if not part or '=' not in part:
            continue

        key, _, value = part.partition('=')
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        lower_key = key.lower()
        if lower_key in skip_attrs:
            continue

        if lower_key == 'set-cookie':
            inner_key, _, inner_value = value.partition('=')
            if inner_key and inner_value:
                key, value = inner_key.strip(), inner_value.strip()
                lower_key = key.lower()
            else:
                continue

        try:
            value = urllib.parse.unquote(value)
        except Exception:
            pass

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]

        result[key] = value

    return result


def _parse_proxy(proxy_str: str) -> Optional[str]:
    """
    تحليل صيغ متعددة من البروكسي وتحويلها إلى صيغة موحدة.
    صيغ مقبولة:
    - IP:PORT
    - username:password@IP:PORT
    - hostname:port:username:password
    - hostname:port
    """
    if not proxy_str or not isinstance(proxy_str, str):
        return None

    proxy_str = proxy_str.strip()

    if '@' in proxy_str:
        try:
            credentials, host_port = proxy_str.rsplit('@', 1)
            if ':' in host_port:
                host, port_str = host_port.rsplit(':', 1)
                port = int(port_str)
                if 1 <= port <= 65535:
                    return f"http://{credentials}@{host}:{port}"
        except (ValueError, IndexError):
            pass
        return None

    parts = proxy_str.split(':')

    if len(parts) == 2:
        host, port_str = parts
        try:
            port = int(port_str)
            if 1 <= port <= 65535:
                return f"http://{host}:{port}"
        except (ValueError, IndexError):
            pass

    elif len(parts) == 4:
        host, port_str, user, password = parts
        try:
            port = int(port_str)
            if 1 <= port <= 65535:
                return f"http://{user}:{password}@{host}:{port}"
        except (ValueError, IndexError):
            pass

    elif len(parts) >= 3:
        try:
            port = int(parts[-1])
            if 1 <= port <= 65535:
                host = ':'.join(parts[:-1])
                return f"http://{host}:{port}"
        except (ValueError, IndexError):
            pass

    return None


def _get_proxies(proxy: Optional[str]) -> Optional[dict]:
    """تحويل البروكسي إلى صيغة httpx."""
    if not proxy:
        return None
    parsed_proxy = _parse_proxy(proxy)
    if not parsed_proxy:
        return None
    return {'http://': parsed_proxy, 'https://': parsed_proxy}


def _is_business_manager_response(text: str) -> bool:
    html = (text or '').lower()
    return (
        'business.facebook.com' in html
        or 'fb_dtsg' in html
        or 'dtsginitialdata' in html
        or 'business_settings' in html
        or 'meta business suite' in html
    )


def _validate_cookie_keys(cookies_dict: dict) -> dict:
    """التحقق المرن من وجود مفاتيح جلسة أساسية لفيس/إنستا/ميتا."""
    has_c_user = 'c_user' in cookies_dict and bool(cookies_dict['c_user'])
    has_xs = 'xs' in cookies_dict and bool(cookies_dict['xs'])
    has_sessionid = 'sessionid' in cookies_dict and bool(cookies_dict['sessionid'])
    has_ds_user_id = 'ds_user_id' in cookies_dict and bool(cookies_dict['ds_user_id'])

    result = {
        'has_c_user': has_c_user,
        'has_xs': has_xs,
        'has_datr': 'datr' in cookies_dict and bool(cookies_dict['datr']),
        'has_sb': 'sb' in cookies_dict and bool(cookies_dict['sb']),
        'has_sessionid': has_sessionid,
        'has_ds_user_id': has_ds_user_id,
        'total_keys': len(cookies_dict),
    }
    result['looks_valid'] = (has_c_user and has_xs) or (has_sessionid and has_ds_user_id) or has_sessionid or has_c_user
    return result


def _extract_dtsg(html: str) -> Optional[str]:
    if not html or len(html) < 100:
        return None

    candidates = [html]
    try:
        decoded = html.encode('utf-8').decode('unicode_escape')
        if decoded and decoded != html:
            candidates.append(decoded)
    except Exception:
        pass

    patterns = [
        r'"DTSGInitialData"[^}]*?"token":"([^"]+)"',
        r'"DTSGInitialData":\s*\{[^}]*?"token":"([^"]+)"',
        r'\["DTSGInitialData",\s*\[],\s*\{[^}]*?"token":"([^"]+)"',
        r'require\(\s*["\']DTSGInitialData["\']\s*\)\.token\s*[:=]?\s*["\']([^"\']+)["\']',
        r'DTSGInitialData\.token\s*=\s*["\']([^"\']+)["\']',
        r'name="fb_dtsg"\s+value="([^"]+)"',
        r'name="fb_dtsg" value="([^"]+)"',
        r'"fb_dtsg":"([^"]+)"',
        r'"fb_dtsg"\s*:\s*\{[^}]*?"value"\s*:\s*"([^"]+)"',
        r'fb_dtsg["\']?\s*[=:]\s*["\']?([A-Za-z0-9:_-]{20,})',
        r'DTSG["\']?\s*[=:]\s*["\']?([A-Za-z0-9:_-]{20,})',
        r'"dtsg":"([^"]+)"',
        r'"token":"([A-Za-z0-9:_-]{20,})"',
    ]

    for candidate in candidates:
        for pattern in patterns:
            match = re.search(pattern, candidate, re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            token = match.group(1).strip()
            token = token.replace('\\/', '/').replace('\\u003A', ':')
            if len(token) >= 20:
                return token
    return None


def _extract_js_value(html: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            value = match.group(1)
            if value:
                return value.strip().strip('"\'')
    return None


def _extract_bm_context(html: str) -> Dict[str, Optional[str]]:
    context = {
        'dtsg': _extract_dtsg(html),
        'user_id': None,
        'business_id': None,
        'ad_account_id': None,
    }

    if not html or len(html) < 100:
        return context

    context['user_id'] = _extract_js_value(html, [
        r'"CurrentUserInitialData"\s*:\s*\{[^}]*?"ACCOUNT_ID"\s*:\s*"(\d+)"',
        r'CurrentUserInitialData\.ACCOUNT_ID\s*=\s*"(\d+)"',
        r'CurrentUserInitialData\.ACCOUNT_ID\s*=\s*(\d+)',
        r'"ACCOUNT_ID"\s*:\s*"(\d+)"',
    ])

    context['business_id'] = _extract_js_value(html, [
        r'"BusinessUnifiedNavigationContext"\s*:\s*\{[^}]*?"businessID"\s*:\s*"(\d+)"',
        r'BusinessUnifiedNavigationContext\.businessID\s*=\s*"(\d+)"',
        r'BusinessUnifiedNavigationContext\.businessID\s*=\s*(\d+)',
        r'"businessID"\s*:\s*"(\d+)"',
    ])

    context['ad_account_id'] = _extract_js_value(html, [
        r'"BusinessUnifiedNavigationContext"\s*:\s*\{[^}]*?"adAccountID"\s*:\s*"(\d+)"',
        r'BusinessUnifiedNavigationContext\.adAccountID\s*=\s*"(\d+)"',
        r'BusinessUnifiedNavigationContext\.adAccountID\s*=\s*(\d+)',
        r'"adAccountID"\s*:\s*"(\d+)"',
    ])

    return context


async def _fetch_dtsg_with_playwright(cookies_dict: dict, proxy: Optional[str] = None) -> Dict[str, Any]:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return {'success': False, 'error': 'PLAYWRIGHT_NOT_INSTALLED'}

    parsed_proxy = _parse_proxy(proxy) if proxy else None

    browser_proxy = None
    if parsed_proxy:
        browser_proxy = {'server': parsed_proxy}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, proxy=browser_proxy)
            context = await browser.new_context(ignore_https_errors=True)

            cookie_items = []
            for name, value in cookies_dict.items():
                cookie_items.append({
                    'name': name,
                    'value': value,
                    'domain': '.facebook.com',
                    'path': '/',
                    'httpOnly': False,
                    'secure': True,
                })
                cookie_items.append({
                    'name': name,
                    'value': value,
                    'domain': '.business.facebook.com',
                    'path': '/',
                    'httpOnly': False,
                    'secure': True,
                })
                cookie_items.append({
                    'name': name,
                    'value': value,
                    'domain': '.instagram.com',
                    'path': '/',
                    'httpOnly': False,
                    'secure': True,
                })

            await context.add_cookies(cookie_items)
            page = await context.new_page()
            await page.goto(f'{BM_BASE}/billing/', wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(5000)

            current_url = page.url.lower()
            html = await page.content()

            token = _extract_dtsg(html)
            if not token:
                token = await page.evaluate("""
                    () => {
                        const fromInput = document.querySelector('input[name="fb_dtsg"]');
                        if (fromInput && fromInput.value) return fromInput.value;
                        const html = document.documentElement ? document.documentElement.outerHTML : '';
                        return html || null;
                    }
                """)
                if token and '<html' in token.lower():
                    token = _extract_dtsg(token)

            if not token:
                possible = await page.evaluate("""
                    () => {
                        try {
                            if (window.require) {
                                const mods = ['DTSGInitialData', 'DTSGInitData'];
                                for (const m of mods) {
                                    try {
                                        const v = window.require(m);
                                        if (v && v.token) return v.token;
                                    } catch (e) {}
                                }
                            }
                        } catch (e) {}
                        return null;
                    }
                """)
                if possible:
                    token = possible

            await browser.close()

            if token:
                return {'success': True, 'dtsg': token, 'url': current_url, 'source': 'playwright'}

            if 'login' in current_url or 'checkpoint' in current_url:
                return {'success': False, 'error': 'تم تحويل الجلسة إلى login/checkpoint داخل المتصفح'}

            return {
                'success': False,
                'error': 'تعذر استخراج DTSG حتى عبر Playwright رغم فتح الصفحة',
                'details': {'url': current_url, 'has_bm': _is_business_manager_response(html)}
            }
    except Exception as e:
        return {'success': False, 'error': f'Playwright error: {str(e)}'}


class BMCardService:
    def __init__(self, cookies_str: str, proxy: Optional[str] = None,
                 dtsg: Optional[str] = None, user_id: Optional[str] = None):
        self.cookies_str = cookies_str
        self.cookies_dict = _parse_cookies(cookies_str)
        self.proxies = _get_proxies(proxy)
        self.proxy = proxy
        self._dtsg: Optional[str] = dtsg
        self._user_id: str = user_id or self.cookies_dict.get('c_user') or self.cookies_dict.get('ds_user_id', '')
        self._profile = random.choice(DEVICE_PROFILES)

    def _headers(self) -> dict:
        return {
            'User-Agent': self._profile['ua'],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': self._profile['lang'],
            'Accept-Encoding': 'gzip, deflate, br',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': BM_BASE,
            'Referer': f'{BM_BASE}/billing/',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Cache-Control': 'max-age=0',
            'X-Requested-With': 'XMLHttpRequest',
            'Pragma': 'no-cache',
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30, proxies=self.proxies, follow_redirects=True)

    async def fetch_dtsg(self) -> Dict[str, Any]:
        endpoints = [
            f'{BM_BASE}/',
            f'{BM_BASE}/overview',
            f'{BM_BASE}/billing/',
            f'{BM_BASE}/business_locations',
            f'{BM_BASE}/business_settings',
            f'{FB_BASE}/',
            f'{IG_BASE}/',
        ]
        session_expired_url_indicators = ['login', 'checkpoint']
        session_expired_text_indicators = [
            'please log in', 'session expired', 'session has expired',
            'must be logged in', 'requires login', 'checkpoint'
        ]

        checked = []
        saw_business_page = False

        try:
            async with self._client() as c:
                for endpoint in endpoints:
                    try:
                        resp = await c.get(endpoint, headers=self._headers(), cookies=self.cookies_dict)
                        text = resp.text
                        url_str = str(resp.url).lower()
                        has_bm = 'business.facebook.com' in url_str or _is_business_manager_response(text)
                        saw_business_page = saw_business_page or has_bm

                        checked.append({
                            'endpoint': endpoint,
                            'status': resp.status_code,
                            'final_url': url_str,
                            'has_bm': has_bm,
                        })

                        if any(indicator in url_str for indicator in session_expired_url_indicators):
                            continue
                        if any(indicator in text.lower() for indicator in session_expired_text_indicators):
                            continue
                        if resp.status_code != 200:
                            continue

                        ctx = _extract_bm_context(text)
                        if ctx['dtsg']:
                            self._dtsg = ctx['dtsg']
                            if ctx['user_id']:
                                self._user_id = ctx['user_id']
                            return {
                                'success': True,
                                'endpoint': endpoint,
                                'dtsg': self._dtsg,
                                'user_id': self._user_id,
                                'business_id': ctx['business_id'],
                                'ad_account_id': ctx['ad_account_id'],
                                'source': 'httpx',
                            }
                    except Exception as exc:
                        checked.append({
                            'endpoint': endpoint,
                            'status': 'error',
                            'final_url': '',
                            'has_bm': False,
                            'error': str(exc)[:200],
                        })
                        continue

            pw_result = await asyncio.wait_for(
                _fetch_dtsg_with_playwright(self.cookies_dict, proxy=self.proxy),
                timeout=90
            )
            if pw_result.get('success'):
                self._dtsg = pw_result['dtsg']
                return {
                    'success': True,
                    'endpoint': pw_result.get('url', 'playwright'),
                    'dtsg': self._dtsg,
                    'user_id': self._user_id,
                    'business_id': None,
                    'ad_account_id': None,
                    'source': 'playwright',
                }

            if saw_business_page:
                extra = pw_result.get('error') if isinstance(pw_result, dict) else ''
                return {
                    'success': False,
                    'error': 'فتحنا صفحات Business Manager لكن تعذر استخراج DTSG من HTML الخام ومن المتصفح. ' + extra,
                    'details': checked,
                }

            return {
                'success': False,
                'error': 'فشل الوصول إلى Business Manager باستخدام هذه الجلسة. قد تكون الجلسة غير مكتملة أو تحتاج دخول business.facebook.com مرة واحدة.',
                'details': checked,
            }
        except asyncio.TimeoutError:
            return {
                'success': False,
                'error': 'انتهاء المهلة الزمنية أثناء استخراج DTSG - قد تكون الجلسة ثقيلة أو البروكسي بطيئاً',
                'details': checked,
            }
        except Exception as e:
            error_str = str(e)
            if 'timeout' in error_str.lower():
                return {'success': False, 'error': 'انتهاء المهلة الزمنية - قد يكون البروكسي بطيئاً أو الرد معلقاً', 'details': checked}
            if 'proxy' in error_str.lower() or 'connection' in error_str.lower():
                return {'success': False, 'error': f'مشكلة في الاتصال/البروكسي: {error_str[:120]}', 'details': checked}
            return {'success': False, 'error': f'خطأ في الاتصال: {error_str}', 'details': checked}

    async def _gql(self, friendly: str, doc_id: str, variables: dict,
                   bm_id: str, ad_id: str) -> Dict[str, Any]:
        query_params = {}
        if friendly == 'BillingHubPaymentMethodsViewQuery':
            query_params = {'_callFlowletID': '0', '_triggerFlowletID': '2596'}
        elif friendly == 'BillingHubPaymentMethodsBusinessSectionQuery':
            query_params = {'_callFlowletID': '0', '_triggerFlowletID': '1'}

        url = GRAPHQL
        if query_params:
            url = f"{GRAPHQL}?{urllib.parse.urlencode(query_params)}"

        body_dict = {
            'av': self._user_id,
            '__aaid': ad_id,
            '__bid': bm_id,
            '__user': self._user_id,
            '__a': '1',
            'fb_dtsg': self._dtsg,
            'fb_api_caller_class': 'RelayModern',
            'fb_api_req_friendly_name': friendly,
            'variables': json.dumps(variables),
            'doc_id': doc_id,
        }
        body = urllib.parse.urlencode(body_dict)
        try:
            async with self._client() as c:
                resp = await c.post(url, headers=self._headers(), cookies=self.cookies_dict, content=body)
                if resp.status_code == 401:
                    return {'success': False, 'error': 'الكوكيز منتهية - تحتاج تسجيل دخول من جديد (401)'}
                if resp.status_code == 403:
                    return {'success': False, 'error': 'الوصول مرفوض - قد تحتاج إلى سلطات إضافية (403)'}
                if resp.status_code >= 500:
                    return {'success': False, 'error': f'خطأ الخادم ({resp.status_code})'}
                try:
                    data = resp.json()
                    return {'success': True, 'data': data}
                except Exception:
                    return {'success': False, 'error': f'رد غير JSON ({resp.status_code}): {resp.text[:200]}'}
        except Exception as e:
            return {'success': False, 'error': f'خطأ شبكة: {str(e)}'}

    async def get_billing_account_id(self, bm_id: str, ad_id: str) -> Dict[str, Any]:
        r = await self._gql(
            'BillingHubPaymentMethodsViewQuery',
            '23945721255021756',
            {'businessID': bm_id},
            bm_id, ad_id,
        )
        if not r['success']:
            return r
        bm_ad_id = (r['data'].get('data', {})
                             .get('business', {})
                             .get('billing_payment_account', {})
                             .get('id'))
        if not bm_ad_id:
            return {'success': False, 'error': 'لم يتم العثور على حساب الدفع في البيزنس'}
        return {'success': True, 'bm_ad_id': bm_ad_id}

    async def get_payment_methods(self, bm_id: str, ad_id: str, bm_ad_id: str) -> Dict[str, Any]:
        r = await self._gql(
            'BillingHubPaymentMethodsBusinessSectionQuery',
            '24585166657733775',
            {
                'paymentAccountID': bm_ad_id,
                'billable_account_types': ['FB_ADS', 'WHATSAPP'],
                'connected_asset_limit': 26,
                'connected_asset_detail_limit': 5,
            },
            bm_id, ad_id,
        )
        if not r['success']:
            return r
        try:
            methods = (r['data']['data']['payment_account']['billing_payment_methods'])
            cards = [m['credential'] for m in methods]
            if not cards:
                return {'success': False, 'error': 'لا توجد بطاقات في الحافظة'}
            return {'success': True, 'cards': cards}
        except Exception as e:
            return {'success': False, 'error': f'خطأ في تحليل البطاقات: {e}'}

    async def make_default(self, bm_id: str, ad_id: str, credential_id: str) -> Dict[str, Any]:
        def _rnd():
            return f"upl_{int(time.time()*1000)}_{random.randint(100000, 999999)}"

        r = await self._gql(
            'BillingSaveSharedBizCardStateMutation',
            '25126279877041501',
            {
                'input': {
                    'payment_legacy_account_id': ad_id,
                    'shared_biz_credential_id': credential_id,
                    'upl_logging_data': {
                        'context': 'billingaddpm',
                        'credential_id': credential_id,
                        'credential_type': 'CREDIT_CARD',
                        'entry_point': 'BILLING_HUB',
                        'external_flow_id': _rnd(),
                        'target_name': 'BillingSaveSharedBizCardStateMutation',
                        'user_session_id': _rnd(),
                        'wizard_config_name': 'SELECT_PAYMENT_METHOD',
                        'wizard_name': 'ADD_PM_PUX_EP',
                        'wizard_session_id': f'upl_wizard_{_rnd()}',
                    },
                    'actor_id': self._user_id,
                    'client_mutation_id': str(int(time.time() * 1000)),
                },
                'includeCreateNewFromOldFragment': False,
            },
            bm_id, ad_id,
        )
        if not r['success']:
            return r
        if 'errors' in r.get('data', {}):
            msg = r['data']['errors'][0].get('message', 'خطأ غير معروف')
            return {'success': False, 'error': msg}
        return {'success': True}


async def verify_bm_cookies(cookies_str: str, proxy: Optional[str] = None) -> Dict[str, Any]:
    parsed = _parse_cookies(cookies_str)
    validation = _validate_cookie_keys(parsed)
    if not parsed:
        return {'success': False, 'error': 'تعذر تحليل الكوكيز المرسلة'}

    svc = BMCardService(cookies_str, proxy)
    result = await svc.fetch_dtsg()
    if result.get('success'):
        return {
            'success': True,
            'dtsg': result.get('dtsg'),
            'url': result.get('endpoint') or result.get('url'),
            'source': result.get('source', 'unknown'),
            'validation': validation,
        }

    return {
        'success': False,
        'error': result.get('error', 'فشل التحقق من الجلسة'),
        'details': result.get('details', []),
        'validation': validation,
    }


async def get_bm_cards(cookies: str, bm_id: str, ad_id: str, proxy: Optional[str] = None) -> Dict[str, Any]:
    svc = BMCardService(cookies, proxy)
    r = await svc.fetch_dtsg()

    if not r['success']:
        if proxy:
            svc_no_proxy = BMCardService(cookies, proxy=None)
            r = await svc_no_proxy.fetch_dtsg()
            if r['success']:
                r = await svc_no_proxy.get_billing_account_id(bm_id, ad_id)
                if not r['success']:
                    return r
                return await svc_no_proxy.get_payment_methods(bm_id, ad_id, r['bm_ad_id'])
            return {
                'success': False,
                'error': f"{r['error']}\n\n💡 <b>ملاحظة:</b> حاولنا بدون بروكسي أيضاً"
            }
        return r

    r = await svc.get_billing_account_id(bm_id, ad_id)
    if not r['success']:
        return r
    return await svc.get_payment_methods(bm_id, ad_id, r['bm_ad_id'])


async def warm_bm_cards(cookies: str, bm_id: str, ad_id: str,
                        cards: List[dict], card_ids: List[str],
                        interval_secs: int,
                        proxy: Optional[str] = None) -> Dict[str, Any]:
    svc = BMCardService(cookies, proxy)
    r = await svc.fetch_dtsg()
    if not r['success']:
        return r

    id_to_card = {c.get('credential_id', ''): c for c in cards}
    results = []
    for cid in card_ids:
        card = id_to_card.get(cid, {})
        name = card.get('card_association_name', 'Card')
        last4 = card.get('last_four_digits', '****')
        label = f"{name} •••• {last4}"

        res = await svc.make_default(bm_id, ad_id, cid)
        results.append({
            'label': label,
            'success': res['success'],
            'error': res.get('error', ''),
        })
        if interval_secs > 0 and cid != card_ids[-1]:
            await asyncio.sleep(interval_secs)

    success_count = sum(1 for item in results if item['success'])
    fail_count = len(results) - success_count
    return {
        'success': True,
        'results': results,
        'success_count': success_count,
        'fail_count': fail_count,
    }
