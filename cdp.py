"""
Подключение к Chrome через DevTools Protocol (порт 9222).

Не использует ChromeDriver — никаких проблем с версиями.
Chrome должен быть запущен пользователем через start-chrome.bat:
    chrome.exe --remote-debugging-port=9222 --user-data-dir=...
"""
import json
import logging
import time
from typing import Dict, List, Optional

import requests

try:
    import websocket  # websocket-client
    HAS_WS = True
except Exception:
    HAS_WS = False

log = logging.getLogger("cdp")


class CDPError(RuntimeError):
    pass


class CDPClient:
    def __init__(self, port: int = 9222):
        self.port = port
        self.ws = None
        self._id = 0
        self.target_url = ""
        # Для доступа к OOPIF (cross-origin iframe) через auto-attach
        self._iframe_sessions: Dict[str, Dict] = {}  # sessionId -> {url, targetId}
        self._iframe_discovery_enabled = False

    # ─── Подключение ─────────────────────────────────────────────────────────

    def connect(self, url_filter: str = "vk.com") -> None:
        if not HAS_WS:
            raise CDPError("Не установлена библиотека websocket-client. Запустите install.bat")
        try:
            tabs = requests.get(f"http://localhost:{self.port}/json", timeout=3).json()
        except Exception as e:
            raise CDPError(
                f"Chrome не отвечает на порту {self.port}.\n"
                f"Запустите Chrome через start-chrome.bat и откройте VK."
            ) from e

        target = None
        for t in tabs:
            if t.get("type") == "page" and url_filter in t.get("url", ""):
                target = t
                break
        if not target:
            urls = [t.get("url", "") for t in tabs if t.get("type") == "page"]
            raise CDPError(
                f"В Chrome нет открытой вкладки с «{url_filter}».\n"
                f"Открытые вкладки:\n  " + "\n  ".join(urls[:6] or ["(нет)"])
            )

        self.target_url = target.get("url", "")
        self.ws = websocket.create_connection(
            target["webSocketDebuggerUrl"], timeout=8,
            origin="http://localhost:9222",
        )

    def close(self) -> None:
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    # ─── Базовый вызов ───────────────────────────────────────────────────────

    def _call(self, method: str, params: Optional[Dict] = None,
              session_id: Optional[str] = None) -> Dict:
        self._id += 1
        msg = {"id": self._id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        while True:
            raw = self.ws.recv()
            data = json.loads(raw)
            # Событие (нет id, есть method) — обрабатываем и продолжаем ждать
            if "id" not in data and "method" in data:
                self._handle_event(data)
                continue
            if data.get("id") == self._id:
                if "error" in data:
                    raise CDPError(f"{method}: {data['error']}")
                return data.get("result", {})

    def _handle_event(self, data: Dict) -> None:
        """Обработать асинхронное событие CDP — в частности, прикрепление iframe-сессий."""
        method = data.get("method")
        params = data.get("params", {})
        if method == "Target.attachedToTarget":
            info = params.get("targetInfo", {})
            sid = params.get("sessionId")
            if sid and info.get("type") == "iframe":
                self._iframe_sessions[sid] = {
                    "url": info.get("url", ""),
                    "targetId": info.get("targetId"),
                }
        elif method == "Target.detachedFromTarget":
            sid = params.get("sessionId")
            self._iframe_sessions.pop(sid, None)
        elif method == "Target.targetInfoChanged":
            info = params.get("targetInfo", {})
            tid = info.get("targetId")
            for s_info in self._iframe_sessions.values():
                if s_info.get("targetId") == tid:
                    s_info["url"] = info.get("url", s_info["url"])

    def enable_iframe_discovery(self) -> None:
        """Включить auto-attach: Chrome будет автоматически прикреплять
        новые iframe-сессии к этому websocket. После этого можно
        вызывать Runtime.evaluate с sessionId конкретного iframe.
        """
        if self._iframe_discovery_enabled:
            return
        try:
            self._call("Target.setAutoAttach", {
                "autoAttach": True,
                "waitForDebuggerOnStart": False,
                "flatten": True,
            })
            self._iframe_discovery_enabled = True
        except Exception as e:
            log.warning(f"setAutoAttach failed: {e}")

    def pump_events(self, duration: float = 0.3) -> None:
        """Прочитать ожидающие события (для сбора Target.attachedToTarget)."""
        if not self.ws:
            return
        deadline = time.time() + duration
        prev_timeout = self.ws.gettimeout()
        try:
            self.ws.settimeout(0.15)
            while time.time() < deadline:
                try:
                    raw = self.ws.recv()
                except Exception:
                    break
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                if "id" not in data and "method" in data:
                    self._handle_event(data)
        finally:
            try:
                self.ws.settimeout(prev_timeout)
            except Exception:
                pass

    def get_iframe_sessions(self, url_filter: Optional[str] = None) -> Dict[str, Dict]:
        """Текущие прикреплённые iframe-сессии (после pump_events)."""
        self.pump_events(0.3)
        if url_filter:
            return {sid: info for sid, info in self._iframe_sessions.items()
                    if url_filter in info.get("url", "")}
        return dict(self._iframe_sessions)

    def evaluate_in_session(self, expr: str, session_id: str):
        """Выполнить JS в контексте конкретной iframe-сессии."""
        try:
            r = self._call("Runtime.evaluate", {
                "expression": expr,
                "returnByValue": True,
                "awaitPromise": True,
            }, session_id=session_id)
        except Exception:
            return None
        if "exceptionDetails" in r:
            return None
        return r.get("result", {}).get("value")

    def click_in_session(self, x: float, y: float, session_id: str) -> None:
        """Клик в iframe-сессии (координаты iframe-relative CSS px)."""
        for ev_type, btn, cnt in (
            ("mouseMoved",    "none", 0),
            ("mousePressed",  "left", 1),
            ("mouseReleased", "left", 1),
        ):
            try:
                self._call("Input.dispatchMouseEvent", {
                    "type": ev_type,
                    "x": float(x), "y": float(y),
                    "button": btn,
                    "buttons": 1 if ev_type == "mousePressed" else 0,
                    "clickCount": cnt,
                    "modifiers": 0,
                    "pointerType": "mouse",
                }, session_id=session_id)
            except Exception:
                pass

    def evaluate(self, expr: str):
        """Выполняет JS в текущей вкладке, возвращает значение."""
        r = self._call("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if "exceptionDetails" in r:
            raise CDPError(f"JS error: {r['exceptionDetails'].get('text','?')}")
        return r.get("result", {}).get("value")

    # ─── Высокоуровневые методы ──────────────────────────────────────────────

    def get_members(self) -> List[Dict]:
        """Список участников через data-testid=settings-subscriber-link."""
        js = r"""
        (function(){
            const seen = new Set();
            const out = [];
            for (const a of document.querySelectorAll('[data-testid="settings-subscriber-link"]')) {
                const href = a.href || '';
                let uid;
                // /id123456 или /123456 (оба варианта нормализуем к id123456)
                const numMatch = href.match(/\/(?:id)?(\d{5,})(?:[/?#]|$)/);
                if (numMatch) {
                    uid = 'id' + numMatch[1];
                } else {
                    const aliasMatch = href.match(/\/([a-zA-Z][a-zA-Z0-9_.]{1,})(?:[/?#]|$)/);
                    if (aliasMatch) uid = aliasMatch[1];
                }
                if (!uid) continue;
                if (seen.has(uid)) continue;
                seen.add(uid);
                const row = a.closest('li') || a.closest('[class*="Cell"]') || a.parentElement;
                const r = (row || a).getBoundingClientRect();
                out.push({id: uid, href: href, top: r.top, height: r.height});
            }
            return out;
        })()
        """
        return self.evaluate(js) or []

    def scroll_to_member(self, member_id: str, screen_target_y: int = -1) -> dict:
        """Точный скролл.

        screen_target_y — Y в пикселях ЭКРАНА (pyautogui).
        JS конвертирует в viewport-координаты через window.screenY/outerHeight/innerHeight,
        находит реальный скроллируемый контейнер и применяет точную дельту.
        Возвращает dict с полями: ok, delta, contentTop, rowMidY, viewportTarget, scrollContainer.
        """
        js = """
        (async function(uid, screenTargetY){
            // uid может быть 'id123456' — ищем и '/id123456', и '/123456'
            const numDigits = uid.startsWith('id') ? uid.slice(2) : null;
            let found = null;
            for (const a of document.querySelectorAll('[data-testid="settings-subscriber-link"]')) {
                const href = a.href || '';
                if (href.includes('/' + uid) || (numDigits && href.includes('/' + numDigits))) {
                    found = a; break;
                }
            }
            if (!found) return {ok: false, reason: 'not_found'};

            const row = found.closest('li') || found.closest('[class*="Cell"]') || found.parentElement;

            if (screenTargetY < 0) {
                row.scrollIntoView({block: 'nearest', behavior: 'instant'});
                await new Promise(r => requestAnimationFrame(r));
                return {ok: true, delta: 0, reason: 'scrollIntoView_only'};
            }

            // Все координаты в CSS/логических пикселях:
            // pyautogui (DPI-unaware) и window.screenY оба работают в логических px.
            const dpr = window.devicePixelRatio || 1;

            // window.screenY (CSS px) = Y верха окна браузера на экране
            // outerHeight - innerHeight = высота панелей инструментов
            const contentTop = window.screenY + (window.outerHeight - window.innerHeight);
            const viewportTarget = screenTargetY - contentTop;

            // Ищем реальный скроллируемый предок
            let scrollEl = null;
            let containerName = 'window';
            let el = row.parentElement;
            while (el && el !== document.documentElement) {
                const s = getComputedStyle(el);
                if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                        && el.scrollHeight > el.clientHeight + 1) {
                    scrollEl = el;
                    containerName = el.tagName + '.' + (el.className || '').split(' ')[0];
                    break;
                }
                el = el.parentElement;
            }

            const rect = row.getBoundingClientRect();
            const rowMidY = rect.top + rect.height / 2;
            const delta = rowMidY - viewportTarget;

            // scrollTop += обходит scroll-behavior:smooth (в отличие от scrollBy/scrollTo)
            if (scrollEl) {
                scrollEl.scrollTop += delta;
            } else {
                // document.scrollingElement тоже обходит smooth
                document.scrollingElement.scrollTop += delta;
            }

            // Ждём один кадр — Chrome успевает применить скролл
            await new Promise(r => requestAnimationFrame(r));

            // Читаем реальную позицию после скролла
            const newRect = row.getBoundingClientRect();
            const newRowMidY = newRect.top + newRect.height / 2;
            const error = Math.round(newRowMidY - viewportTarget);

            return {
                ok: true,
                delta: Math.round(delta),
                error: error,
                dpr: dpr,
                screenY: Math.round(window.screenY),
                contentTop: Math.round(contentTop),
                rowMidY: Math.round(rowMidY),
                newRowMidY: Math.round(newRowMidY),
                viewportTarget: Math.round(viewportTarget),
                scrollContainer: containerName
            };
        })(""" + json.dumps(member_id) + ", " + str(screen_target_y) + ")"
        result = self.evaluate(js)
        if not isinstance(result, dict):
            return {"ok": bool(result)}
        return result

    def get_content_top(self) -> int:
        """Высота браузерной шапки: window.screenY + (outerHeight - innerHeight), в логических px."""
        result = self.evaluate("window.screenY + (window.outerHeight - window.innerHeight)")
        return int(result or 0)

    def get_member_viewport_y(self, member_id: str) -> Optional[float]:
        """Viewport Y центра строки участника (из getBoundingClientRect, без DPR)."""
        js = r"""
        (function(uid){
            const numDigits = uid.startsWith('id') ? uid.slice(2) : null;
            for (const a of document.querySelectorAll('[data-testid="settings-subscriber-link"]')) {
                const href = a.href || '';
                if (href.includes('/' + uid) || (numDigits && href.includes('/' + numDigits))) {
                    const row = a.closest('li') || a.closest('[class*="Cell"]') || a.parentElement;
                    const r = row.getBoundingClientRect();
                    return r.top + r.height / 2;
                }
            }
            return null;
        })(""" + json.dumps(member_id) + ")"
        return self.evaluate(js)

    def scroll_by_delta(self, delta: int) -> dict:
        """Прокручивает контейнер участников ровно на delta CSS-пикселей."""
        js = f"""
        (function(dy){{
            const links = document.querySelectorAll('[data-testid="settings-subscriber-link"]');
            if (!links.length) return {{ok: false, reason: 'no_links'}};
            let found = null;
            let el = links[0].parentElement;
            while (el && el !== document.documentElement) {{
                const s = getComputedStyle(el);
                if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                        && el.scrollHeight > el.clientHeight + 1) {{
                    found = el; break;
                }}
                el = el.parentElement;
            }}
            const target = found || document.scrollingElement;
            const before = target.scrollTop;
            target.scrollTop += dy;
            const after = target.scrollTop;
            return {{
                ok: true,
                container: found ? (found.tagName + '.' + (found.className||'').split(' ')[0]) : 'window',
                before: Math.round(before),
                after: Math.round(after),
                actual: Math.round(after - before)
            }};
        }})({int(delta)})
        """
        result = self.evaluate(js)
        return result if isinstance(result, dict) else {"ok": bool(result)}

    def scroll_by_step(self, dy: int) -> dict:
        """Прокрутка списка участников ровно на dy CSS-пикселей.

        dy — шаг из калибровки (расстояние между строками в логических пикселях).
        CSS px == логические px == пиксели pyautogui на Windows, конвертация не нужна.
        """
        js = f"""
        (function(dy){{
            const links = document.querySelectorAll('[data-testid="settings-subscriber-link"]');
            if (!links.length) return {{ok: false, reason: 'no_links'}};
            let found = null;
            let el = links[0].parentElement;
            while (el && el !== document.documentElement) {{
                const s = getComputedStyle(el);
                if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                        && el.scrollHeight > el.clientHeight + 1) {{
                    found = el; break;
                }}
                el = el.parentElement;
            }}
            const target = found || document.scrollingElement;
            const before = target.scrollTop;
            target.scrollTop += dy;
            const after = target.scrollTop;
            return {{
                ok: true,
                container: found ? (found.tagName + '.' + (found.className||'').split(' ')[0]) : 'window',
                before: Math.round(before),
                after: Math.round(after),
                actual: Math.round(after - before)
            }};
        }})({int(dy)})
        """
        result = self.evaluate(js)
        return result if isinstance(result, dict) else {"ok": bool(result)}

    # ─── Низкоуровневый ввод через CDP (надёжные клики и hover) ──────────────

    def dispatch_mouse(self, ev_type: str, x: float, y: float,
                       button: str = "none", click_count: int = 0) -> None:
        """Input.dispatchMouseEvent в viewport-координатах CSS-пикселей."""
        self._call("Input.dispatchMouseEvent", {
            "type": ev_type,
            "x": float(x),
            "y": float(y),
            "button": button,
            "buttons": 1 if button == "left" else 0,
            "clickCount": click_count,
            "modifiers": 0,
            "pointerType": "mouse",
        })

    def click_at_viewport(self, x: float, y: float) -> None:
        """Полный клик в viewport-координатах: move → press → release."""
        self.dispatch_mouse("mouseMoved",    x, y)
        self.dispatch_mouse("mousePressed",  x, y, button="left", click_count=1)
        self.dispatch_mouse("mouseReleased", x, y, button="left", click_count=1)

    def hover_at_viewport(self, x: float, y: float) -> None:
        """Синтетический mouseMoved для триггера CSS :hover."""
        self.dispatch_mouse("mouseMoved", x, y)

    def get_content_origin(self) -> dict:
        """Экранные координаты левого верхнего угла viewport + DPR.

        Chrome возвращает screenX/Y в CSS-пикселях. pyautogui на DPI-aware
        приложениях работает в физических пикселях. Множитель — devicePixelRatio.
        """
        result = self.evaluate("""
        ({
            x: window.screenX + Math.round((window.outerWidth - window.innerWidth) / 2),
            y: window.screenY + (window.outerHeight - window.innerHeight),
            dpr: window.devicePixelRatio || 1
        })
        """)
        return result if isinstance(result, dict) else {"x": 0, "y": 0, "dpr": 1}

    def get_member_row_rect(self, member_id: str) -> Optional[dict]:
        """Viewport-rect всей строки участника (для наведения курсора перед кликом)."""
        js = r"""
        (function(uid) {
            const numDigits = uid.startsWith('id') ? uid.slice(2) : null;
            for (const a of document.querySelectorAll(
                '[data-testid="settings-subscriber-link"], a[href*="/id"], a[href*="vk.com/"]'
            )) {
                const href = a.href || '';
                const match = href.includes('/' + uid)
                    || (numDigits && (href.includes('/id' + numDigits)
                        || new RegExp('(^|[/?#])' + numDigits + '([/?#]|$)').test(href)));
                if (!match) continue;
                const row = a.closest('li') || a.closest('[class*="Cell"]') || a.parentElement;
                if (!row) continue;
                const r = row.getBoundingClientRect();
                if (r.width > 0 && r.height > 0)
                    return {x: r.left, y: r.top, w: r.width, h: r.height};
            }
            return null;
        })(""" + json.dumps(member_id) + ")"
        return self.evaluate(js)

    def get_member_action_button_rect(self, member_id: str) -> Optional[dict]:
        """Viewport-rect кнопки «...» у конкретного участника.

        Стратегия по геометрии (не по DOM-иерархии):
          1. Находим ссылку участника.
          2. Берём её среднюю Y координату.
          3. Среди ВСЕХ кликабельных элементов страницы выбираем те, что
             на той же горизонтальной линии (|midY - linkMidY| < height) и
             правее ссылки (right > linkRight).
          4. Из них выбираем самый правый видимый, либо с подходящим aria-label.
        """
        js = r"""
        (function(uid) {
            const numDigits = uid.startsWith('id') ? uid.slice(2) : null;

            // 1. Находим ссылку участника
            let memberLink = null;
            for (const a of document.querySelectorAll('a[href]')) {
                const href = a.getAttribute('href') || a.href || '';
                if (href.includes('/' + uid)) { memberLink = a; break; }
                if (numDigits) {
                    const re = new RegExp('/(?:id)?' + numDigits + '($|[/?#])');
                    if (re.test(href)) { memberLink = a; break; }
                }
            }
            if (!memberLink) return null;

            const lr = memberLink.getBoundingClientRect();
            const linkMidY = lr.top + lr.height / 2;
            const linkRight = lr.right;
            const rowH = Math.max(lr.height, 40);

            // 2. Собираем кандидатов: все clickable на той же Y
            const allClickable = document.querySelectorAll(
                'button, [role="button"], [aria-haspopup], [aria-label]'
            );
            const candidates = [];
            for (const el of allClickable) {
                if (el === memberLink || memberLink.contains(el)) continue;
                const r = el.getBoundingClientRect();
                let rect = r;
                let hidden = false;
                if (r.width === 0 || r.height === 0) {
                    // Скрытая кнопка (hover-only). Проверим, что её аria-label
                    // намекает на меню — иначе пропускаем.
                    const al = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (!/ещё|more|действ|меню|menu/.test(al)) continue;
                    // Используем позицию родителя
                    const p = el.parentElement;
                    if (!p) continue;
                    rect = p.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    hidden = true;
                }
                const midY = rect.top + rect.height / 2;
                // Должен быть на той же строке
                if (Math.abs(midY - linkMidY) > rowH * 0.7) continue;
                // Должен быть правее ссылки участника (или внутри её правой половины)
                if (rect.right < linkRight - 10) continue;
                candidates.push({el, rect, hidden,
                    al: (el.getAttribute('aria-label') || '').toLowerCase()});
            }

            if (!candidates.length) return null;

            // 3. Ранжируем: aria-label match → правый край
            candidates.sort((a, b) => {
                const aMatch = /ещё|more|действ|меню|menu/.test(a.al);
                const bMatch = /ещё|more|действ|меню|menu/.test(b.al);
                if (aMatch !== bMatch) return aMatch ? -1 : 1;
                return b.rect.right - a.rect.right;
            });

            const best = candidates[0];
            const r = best.rect;
            return {
                x: r.left, y: r.top, w: r.width, h: r.height,
                hidden: best.hidden, aria: best.al
            };
        })(""" + json.dumps(member_id) + ")"
        return self.evaluate(js)

    def js_click_member_action(self, member_id: str) -> bool:
        """Найти кнопку «...» у участника и вызвать .click() напрямую (React-friendly)."""
        js = r"""
        (function(uid) {
            const numDigits = uid.startsWith('id') ? uid.slice(2) : null;
            let link = null;
            for (const a of document.querySelectorAll('a[href]')) {
                const href = a.getAttribute('href') || a.href || '';
                if (href.includes('/' + uid)) { link = a; break; }
                if (numDigits && new RegExp('/(?:id)?' + numDigits + '($|[/?#])').test(href)) {
                    link = a; break;
                }
            }
            if (!link) return false;
            const lr = link.getBoundingClientRect();
            const linkMidY = lr.top + lr.height / 2;
            const rowH = Math.max(lr.height, 40);

            const candidates = [];
            for (const el of document.querySelectorAll(
                'button, [role="button"], [aria-haspopup], [aria-label]'
            )) {
                if (el === link || link.contains(el)) continue;
                const r = el.getBoundingClientRect();
                let rect = r;
                if (r.width === 0 || r.height === 0) {
                    const al = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (!/ещё|more|действ|меню|menu/.test(al)) continue;
                    const p = el.parentElement;
                    if (!p) continue;
                    rect = p.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                }
                const midY = rect.top + rect.height / 2;
                if (Math.abs(midY - linkMidY) > rowH * 0.7) continue;
                if (rect.right < lr.right - 10) continue;
                candidates.push({el, rect,
                    al: (el.getAttribute('aria-label') || '').toLowerCase()});
            }
            if (!candidates.length) return false;
            candidates.sort((a, b) => {
                const aMatch = /ещё|more|действ|меню|menu/.test(a.al);
                const bMatch = /ещё|more|действ|меню|menu/.test(b.al);
                if (aMatch !== bMatch) return aMatch ? -1 : 1;
                return b.rect.right - a.rect.right;
            });
            try {
                // На случай делегированных handlers — диспатчим полный сценарий
                const el = candidates[0].el;
                el.click();
                return true;
            } catch (e) { return false; }
        })(""" + json.dumps(member_id) + ")"
        return bool(self.evaluate(js))

    def diagnose_member(self, member_id: str) -> dict:
        """Диагностика: что есть в DOM на строке участника."""
        js = r"""
        (function(uid) {
            const numDigits = uid.startsWith('id') ? uid.slice(2) : null;
            let link = null;
            for (const a of document.querySelectorAll('a[href]')) {
                const href = a.getAttribute('href') || a.href || '';
                if (href.includes('/' + uid)) { link = a; break; }
                if (numDigits && new RegExp('/(?:id)?' + numDigits + '($|[/?#])').test(href)) {
                    link = a; break;
                }
            }
            if (!link) return {error: 'no_link', uid: uid};
            const lr = link.getBoundingClientRect();
            const linkMidY = lr.top + lr.height / 2;
            const rowH = Math.max(lr.height, 40);

            const found = [];
            for (const el of document.querySelectorAll('button, [role="button"], [aria-haspopup], [aria-label]')) {
                const r = el.getBoundingClientRect();
                const midY = r.top + r.height / 2;
                if (Math.abs(midY - linkMidY) > rowH * 0.8) continue;
                found.push({
                    tag: el.tagName,
                    aria: el.getAttribute('aria-label') || '',
                    role: el.getAttribute('role') || '',
                    cls: (typeof el.className === 'string' ? el.className.slice(0, 80) : ''),
                    rect: {x: Math.round(r.left), y: Math.round(r.top),
                           w: Math.round(r.width), h: Math.round(r.height)}
                });
            }
            return {
                linkHref: link.getAttribute('href'),
                linkRect: {x: Math.round(lr.left), y: Math.round(lr.top),
                           w: Math.round(lr.width), h: Math.round(lr.height)},
                onRowElements: found
            };
        })(""" + json.dumps(member_id) + ")"
        return self.evaluate(js) or {}

    def find_menu_item(self, text: str) -> Optional[dict]:
        """Viewport-rect видимого пункта меню (в открытом popup'е) с текстом."""
        js = r"""
        (function(searchText) {
            const lcText = searchText.toLowerCase();

            // 1) Ищем открытые popup-контейнеры
            const popupSelectors = [
                '[role="menu"]', '[role="dialog"]', '[role="listbox"]',
                '[class*="ActionSheet"]', '[class*="Dropdown"]',
                '[class*="Popover"]', '[class*="Popout"]',
                '[class*="Modal"]', '[class*="vkuiPopper"]',
                '[class*="Tooltip"]', '[data-floating-ui-placement]',
            ];
            const popups = [];
            for (const sel of popupSelectors) {
                for (const p of document.querySelectorAll(sel)) {
                    const r = p.getBoundingClientRect();
                    if (r.width > 30 && r.height > 30) popups.push(p);
                }
            }
            // Сортируем popup'ы по z-index (самый верхний — последний открытый)
            popups.sort((a, b) => {
                const za = parseInt(getComputedStyle(a).zIndex) || 0;
                const zb = parseInt(getComputedStyle(b).zIndex) || 0;
                return zb - za;
            });

            const itemSelectors = [
                '[role="menuitem"]', '[role="option"]',
                'button', 'a', 'li',
                '[class*="ActionSheetItem"]', '[class*="SimpleCell"]',
                '[class*="CellButton"]', '[class*="DropdownItem"]',
                '[class*="MenuItem"]', '[class*="Item"]',
            ];

            for (const popup of popups) {
                for (const sel of itemSelectors) {
                    for (const el of popup.querySelectorAll(sel)) {
                        const txt = (el.textContent || '').trim().toLowerCase();
                        if (!txt.includes(lcText)) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0
                            && r.top >= 0 && r.top < window.innerHeight) {
                            return {x: r.left, y: r.top, w: r.width, h: r.height};
                        }
                    }
                }
            }

            // 2) Fallback: глобальный поиск среди всех видимых элементов
            for (const el of document.querySelectorAll(
                'button, a, [role="menuitem"], [role="option"], li, [class*="Cell"]'
            )) {
                const txt = (el.textContent || '').trim().toLowerCase();
                if (!txt.includes(lcText)) continue;
                if (txt.length > lcText.length + 60) continue;  // отбрасываем длинные блоки
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0
                    && r.top >= 0 && r.top < window.innerHeight) {
                    return {x: r.left, y: r.top, w: r.width, h: r.height};
                }
            }
            return null;
        })(""" + json.dumps(text) + ")"
        return self.evaluate(js)

    def js_click_text(self, text: str, popup_only: bool = True) -> bool:
        """Найти элемент с заданным текстом и вызвать .click() на клик-родителе.

        Более надёжно для VK (React/Vue handlers), чем dispatchMouseEvent —
        работает напрямую через DOM-обработчик.
        """
        js = r"""
        (function(searchText, popupOnly) {
            const lc = searchText.toLowerCase();

            function clickableAncestor(el) {
                let cur = el;
                for (let i = 0; cur && i < 12; i++) {
                    const tag = cur.tagName;
                    const role = (cur.getAttribute && (cur.getAttribute('role') || '')).toLowerCase();
                    const cls = (typeof cur.className === 'string') ? cur.className : '';
                    if (tag === 'BUTTON' || tag === 'A' || tag === 'LI'
                        || role === 'menuitem' || role === 'option' || role === 'button'
                        || /ActionSheetItem|SimpleCell|CellButton|MenuItem|DropdownItem|RadioGroup|Radio__/i.test(cls)) {
                        return cur;
                    }
                    if (cur.onclick) return cur;
                    cur = cur.parentElement;
                }
                return null;
            }

            let roots = [];
            if (popupOnly) {
                const sels = '[role="menu"],[role="dialog"],[role="listbox"],'
                    + '[class*="ActionSheet"],[class*="Dropdown"],[class*="Popover"],'
                    + '[class*="Popout"],[class*="Modal"],[class*="vkuiPopper"]';
                for (const p of document.querySelectorAll(sels)) {
                    const r = p.getBoundingClientRect();
                    if (r.width > 30 && r.height > 30) roots.push(p);
                }
                if (!roots.length) roots = [document.body];
            } else {
                roots = [document.body];
            }

            const candidates = [];
            for (const root of roots) {
                for (const el of root.querySelectorAll('*')) {
                    if (el.children.length > 0) continue;
                    const t = (el.textContent || '').trim().toLowerCase();
                    if (t !== lc && !t.startsWith(lc + ' ') && !t.startsWith(lc)) continue;
                    if (t.length > lc.length + 80) continue;
                    const target = clickableAncestor(el);
                    if (!target) continue;
                    const r = target.getBoundingClientRect();
                    if (r.width < 5 || r.height < 5) continue;
                    candidates.push({target, r, len: t.length});
                }
            }
            if (!candidates.length) return false;
            candidates.sort((a, b) => a.len - b.len);
            try { candidates[0].target.click(); return true; }
            catch (e) { return false; }
        })(""" + json.dumps(text) + ", " + ("true" if popup_only else "false") + ")"
        return bool(self.evaluate(js))

    def find_role_option(self, role_name: str) -> Optional[dict]:
        """Найти кликабельную опцию роли в диалоге («Администратор» / «Редактор» / «Модератор»).

        Ищет видимый элемент с точным или начинающимся текстом role_name
        внутри модального диалога/секции с радио-кнопками.
        """
        js = r"""
        (function(roleName) {
            const lc = roleName.toLowerCase();
            // Ищем все элементы у которых текст НАЧИНАЕТСЯ с роли (отбрасываем
            // длинные блоки с описаниями).
            const candidates = [];
            const all = document.querySelectorAll(
                'label, [class*="SelectionControl"], [class*="Radio"], '
                + '[class*="Cell"], [role="radio"], [role="option"], '
                + 'li, button, div'
            );
            for (const el of all) {
                const txt = (el.textContent || '').trim();
                if (!txt) continue;
                const lct = txt.toLowerCase();
                if (!(lct === lc || lct.startsWith(lc))) continue;
                if (txt.length > 250) continue;  // отбрасываем целые блоки
                const r = el.getBoundingClientRect();
                if (r.width < 10 || r.height < 10) continue;
                if (r.top < 0 || r.top > window.innerHeight) continue;
                // Предпочитаем мелкие компактные элементы (саму опцию, а не контейнер)
                candidates.push({el, r, area: r.width * r.height, len: txt.length});
            }
            if (!candidates.length) return null;
            // Самый компактный (меньшая площадь, короткий текст)
            candidates.sort((a, b) => a.area - b.area || a.len - b.len);
            const best = candidates[0];
            return {x: best.r.left, y: best.r.top,
                    w: best.r.width, h: best.r.height};
        })(""" + json.dumps(role_name) + ")"
        return self.evaluate(js)

    def dump_popups(self) -> list:
        """Диагностика: список текстов в открытых popup'ах."""
        js = r"""
        (function() {
            const out = [];
            const popupSelectors = [
                '[role="menu"]', '[role="dialog"]', '[role="listbox"]',
                '[class*="ActionSheet"]', '[class*="Dropdown"]',
                '[class*="Popover"]', '[class*="Popout"]', '[class*="Modal"]',
            ];
            for (const sel of popupSelectors) {
                for (const p of document.querySelectorAll(sel)) {
                    const r = p.getBoundingClientRect();
                    if (r.width < 30 || r.height < 30) continue;
                    const items = [];
                    for (const el of p.querySelectorAll(
                        'button, a, [role="menuitem"], li, [class*="Cell"]'
                    )) {
                        const t = (el.textContent || '').trim();
                        if (t && t.length < 80) items.push(t);
                    }
                    if (items.length) out.push({sel: sel, items: items.slice(0, 10)});
                }
            }
            return out;
        })()
        """
        result = self.evaluate(js)
        return result if isinstance(result, list) else []

    def find_confirm_button(self, text: str) -> Optional[dict]:
        """Viewport-rect видимой кнопки подтверждения с заданным текстом."""
        js = r"""
        (function(text) {
            for (const btn of document.querySelectorAll('button')) {
                const t = btn.textContent.trim();
                if ((t === text || t.includes(text)) && btn.offsetParent !== null) {
                    const r = btn.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.top >= 0 && r.top < window.innerHeight)
                        return {x: r.left, y: r.top, w: r.width, h: r.height};
                }
            }
            return null;
        })(""" + json.dumps(text) + ")"
        return self.evaluate(js)

    def scroll_member_into_view(self, member_id: str) -> bool:
        """Прокрутить участника в видимую область (мгновенно, без анимации)."""
        js = r"""
        (function(uid) {
            const numDigits = uid.startsWith('id') ? uid.slice(2) : null;
            for (const a of document.querySelectorAll('[data-testid="settings-subscriber-link"]')) {
                const href = a.href || '';
                const match = href.includes('/' + uid)
                    || (numDigits && (href.includes('/id' + numDigits)
                        || new RegExp('[/?#]' + numDigits + '([/?#]|$)').test(href)));
                if (!match) continue;
                const row = a.closest('li') || a.closest('[class*="Cell"]') || a.parentElement;
                if (row) { row.scrollIntoView({block: 'center', behavior: 'instant'}); return true; }
            }
            return false;
        })(""" + json.dumps(member_id) + ")"
        return bool(self.evaluate(js))

    def find_captcha_checkbox(self) -> Optional[dict]:
        """Найти чекбокс 'Я не робот' (VK ID капча) в текущем фрейме.

        Пробивает shadow DOM, same-origin iframes. Текст «Я не робот»
        содержит &nbsp; — нормализуем все whitespace.
        """
        js = r"""
        (function() {
            // ── Утилиты ────────────────────────────────────────────────────
            function norm(s) {
                return (s || '').replace(/[\s ]+/g, ' ').trim().toLowerCase();
            }
            function rectOK(r) {
                return r.width > 0 && r.height > 0
                    && r.right > 0 && r.bottom > 0
                    && r.left < (window.innerWidth + 50)
                    && r.top < (window.innerHeight + 50);
            }
            function findCheckboxAncestor(el) {
                let cur = el;
                for (let i = 0; cur && i < 10; i++) {
                    const cls = (typeof cur.className === 'string') ? cur.className : '';
                    if (/Checkbox(?!.*title)/i.test(cls) && !/title/i.test(cls)) return cur;
                    if (cur.tagName === 'LABEL') return cur;
                    if (cur.getAttribute && cur.getAttribute('role') === 'checkbox') return cur;
                    cur = cur.parentElement;
                }
                return null;
            }
            // Сбор всех корней: document + shadow roots + same-origin iframes
            function collectRoots() {
                const roots = [document];
                const stack = [document];
                while (stack.length) {
                    const root = stack.pop();
                    // Shadow roots
                    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
                    for (const el of all) {
                        if (el.shadowRoot) {
                            roots.push(el.shadowRoot);
                            stack.push(el.shadowRoot);
                        }
                    }
                    // Same-origin iframes
                    const ifrs = root.querySelectorAll ? root.querySelectorAll('iframe') : [];
                    for (const ifr of ifrs) {
                        try {
                            const d = ifr.contentDocument;
                            if (d) {
                                roots.push(d);
                                stack.push(d);
                            }
                        } catch (e) {}
                    }
                }
                return roots;
            }

            const roots = collectRoots();
            const found = [];

            for (const root of roots) {
                // 1) По классу VKUI
                try {
                    for (const el of root.querySelectorAll(
                        '[class*="Checkbox__title"], [class*="Checkbox-module__title"]'
                    )) {
                        const t = norm(el.textContent);
                        if (!t.includes('не робот') && !t.includes('robot')) continue;
                        const clickable = findCheckboxAncestor(el) || el.parentElement || el;
                        const r = clickable.getBoundingClientRect();
                        if (rectOK(r)) found.push({rect: r, src: 'vkc-title', txt: t});
                    }
                } catch (e) {}

                // 2) input[type=checkbox]
                try {
                    for (const cb of root.querySelectorAll('input[type="checkbox"]')) {
                        const wrap = cb.closest('label')
                            || cb.closest('[class*="Checkbox"]')
                            || cb.parentElement;
                        if (!wrap) continue;
                        const t = norm(wrap.textContent);
                        if (!t.includes('не робот') && !t.includes('robot')) continue;
                        const r = wrap.getBoundingClientRect();
                        if (rectOK(r)) found.push({rect: r, src: 'input', txt: t});
                    }
                } catch (e) {}

                // 3) Поиск по тексту
                try {
                    for (const el of root.querySelectorAll('div, span, p, label, button')) {
                        if (el.children.length > 2) continue;
                        const t = norm(el.textContent);
                        if (t !== 'я не робот' && t !== "i'm not a robot"
                            && t !== 'i am not a robot') continue;
                        const clickable = findCheckboxAncestor(el) || el.parentElement || el;
                        const r = clickable.getBoundingClientRect();
                        if (rectOK(r)) found.push({rect: r, src: 'text', txt: t});
                    }
                } catch (e) {}

                // 4) role="checkbox"
                try {
                    for (const el of root.querySelectorAll('[role="checkbox"]')) {
                        const t = norm((el.getAttribute('aria-label') || '') + ' ' + el.textContent);
                        if (!t.includes('не робот') && !t.includes('robot')) continue;
                        const r = el.getBoundingClientRect();
                        if (rectOK(r)) found.push({rect: r, src: 'role', txt: t});
                    }
                } catch (e) {}
            }

            if (!found.length) return null;
            // Берём первый найденный
            const f = found[0];
            return {x: f.rect.left, y: f.rect.top, w: f.rect.width, h: f.rect.height,
                    src: f.src, txt: f.txt};
        })()
        """
        return self.evaluate(js)

    def debug_captcha_state(self) -> dict:
        """Диагностика: что есть в DOM по теме капчи."""
        js = r"""
        (function() {
            const out = {
                bodyHasText: false,
                checkboxes: 0,
                vkcCheckboxes: 0,
                texts: [],
                iframes: 0,
                shadowRoots: 0,
            };
            const body = (document.body && document.body.innerText) || '';
            out.bodyHasText = body.includes('не робот') || body.includes('Подтвердите');
            out.checkboxes = document.querySelectorAll('input[type="checkbox"]').length;
            out.vkcCheckboxes = document.querySelectorAll('[class*="Checkbox"]').length;
            out.iframes = document.querySelectorAll('iframe').length;
            for (const el of document.querySelectorAll('*')) {
                if (el.shadowRoot) out.shadowRoots++;
            }
            for (const el of document.querySelectorAll('[class*="Checkbox__title"], [class*="Checkbox-module__title"]')) {
                const t = (el.textContent || '').trim();
                if (t && t.length < 60) out.texts.push(t);
            }
            return out;
        })()
        """
        return self.evaluate(js) or {}

    def is_captcha_dialog_visible(self) -> bool:
        """Проверить, видна ли капча-диалог (в любом месте страницы)."""
        js = r"""
        (function() {
            const body = document.body ? (document.body.innerText || '') : '';
            return body.includes('не робот') || body.includes('Подтвердите');
        })()
        """
        return bool(self.evaluate(js))

    def get_popup_debugger_url(self, url_filter: str) -> Optional[str]:
        """Найти popup-вкладку/окно по URL и вернуть адрес debugger websocket."""
        try:
            tabs = requests.get(f"http://localhost:{self.port}/json", timeout=3).json()
            for t in tabs:
                if t.get("type") == "page" and url_filter in t.get("url", ""):
                    if t.get("url") != self.target_url:
                        return t.get("webSocketDebuggerUrl")
        except Exception:
            pass
        return None

    def get_all_targets_cdp(self) -> list:
        """Все CDP-таргеты, включая iframe (OOPIF) и popup-окна."""
        try:
            # Включаем auto-attach к iframe для появления их в Target list
            try:
                self._call("Target.setDiscoverTargets", {"discover": True})
            except Exception:
                pass
            r = self._call("Target.getTargets", {})
            return r.get("targetInfos", [])
        except Exception:
            return []

    def iframe_ws_url(self, target_id: str) -> str:
        return f"ws://localhost:{self.port}/devtools/page/{target_id}"

    def find_captcha_iframe_in_parent(self) -> Optional[dict]:
        """В контексте родителя ищет iframe который содержит VK ID капчу.

        Возвращает rect iframe относительно viewport родителя и его src.
        """
        js = r"""
        (function() {
            const candidates = [];
            for (const ifr of document.querySelectorAll('iframe')) {
                const src = ifr.src || '';
                const r = ifr.getBoundingClientRect();
                if (r.width < 50 || r.height < 50) continue;
                // VK ID / captcha признаки
                const score = (
                    (/id\.vk\.com/i.test(src) ? 10 : 0) +
                    (/vkid/i.test(src) ? 8 : 0) +
                    (/captcha/i.test(src) ? 8 : 0) +
                    (/oauth/i.test(src) ? 4 : 0) +
                    (/vk\.com/i.test(src) ? 2 : 0)
                );
                if (score > 0) {
                    candidates.push({
                        src: src,
                        x: r.left, y: r.top, w: r.width, h: r.height,
                        score: score
                    });
                }
            }
            if (!candidates.length) return null;
            candidates.sort((a, b) => b.score - a.score);
            return candidates[0];
        })()
        """
        return self.evaluate(js)

    def attach_existing_iframes(self) -> int:
        """Вручную прикрепить уже существующие OOPIF-таргеты через attachToTarget.

        setAutoAttach ловит только *новые* iframes; этот метод прикрепляет те,
        что уже есть на странице. Возвращает число новых прикреплённых сессий.
        """
        attached = 0
        try:
            self._call("Target.setDiscoverTargets", {"discover": True})
        except Exception:
            pass
        try:
            r = self._call("Target.getTargets", {})
        except Exception:
            return 0
        for t in r.get("targetInfos", []):
            tid = t.get("targetId", "")
            ttype = t.get("type", "")
            url = t.get("url", "")
            # Пропускаем основной target и уже прикреплённые
            already = any(v.get("targetId") == tid for v in self._iframe_sessions.values())
            if already:
                continue
            # Присоединяемся к iframe и page-типам с VK ID URL
            is_vkid = "id.vk.com" in url or "captcha" in url or "vkid" in url
            if ttype == "iframe" or (ttype == "page" and is_vkid):
                try:
                    res = self._call("Target.attachToTarget", {
                        "targetId": tid,
                        "flatten": True,
                    })
                    sid = res.get("sessionId")
                    if sid:
                        self._iframe_sessions[sid] = {"url": url, "targetId": tid}
                        attached += 1
                except Exception:
                    pass
        return attached

    def scroll_page(self, dy: int = 600) -> None:
        """Прокручивает список участников вниз через CDP mouseWheel."""
        # Координата центра viewport — туда направляем колесо мыши
        vx = self.evaluate("window.innerWidth / 2") or 600
        vy = self.evaluate("window.innerHeight / 2") or 400
        # Одно событие mouseWheel на весь dy (Chrome суммирует delta)
        self._call("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": float(vx),
            "y": float(vy),
            "deltaX": 0,
            "deltaY": float(dy),
            "modifiers": 0,
            "pointerType": "mouse",
        })
