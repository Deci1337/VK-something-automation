"""
VK Admin Bot.

Использует CDP для поиска кнопок прямо в DOM VK — никакой ручной калибровки.
pyautogui двигает реальный курсор по кривой Безье и кликает.
"""
import logging
import math
import random
import threading
import time
from typing import Callable, Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
except Exception:
    pyautogui = None

import cdp
import storage

log = logging.getLogger("bot")

# ── Движение мыши (Безье) ─────────────────────────────────────────────────────

def _cubic_bezier(p0, p1, p2, p3, t):
    u = 1 - t
    x = u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0]
    y = u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1]
    return x, y


def _bezier_move(tx: int, ty: int, duration: float = 0.45) -> None:
    if not pyautogui:
        return
    sx, sy = pyautogui.position()
    start = (float(sx), float(sy))
    end   = (float(tx), float(ty))
    dist  = math.hypot(end[0] - start[0], end[1] - start[1])
    if dist < 2:
        return
    dx, dy = end[0] - start[0], end[1] - start[1]
    dev = min(dist * random.uniform(0.15, 0.4), 150)
    c1 = (start[0] + dx*random.uniform(0.2, 0.4) + random.uniform(-dev, dev),
          start[1] + dy*random.uniform(0.2, 0.4) + random.uniform(-dev, dev))
    c2 = (start[0] + dx*random.uniform(0.6, 0.8) + random.uniform(-dev, dev),
          start[1] + dy*random.uniform(0.6, 0.8) + random.uniform(-dev, dev))
    steps      = max(15, int(dist / 12))
    step_delay = duration / steps
    profile    = random.choice(["ease_in_out", "ease_in", "ease_out"])
    for i in range(1, steps + 1):
        raw_t = i / steps
        if profile == "ease_in_out":
            t = raw_t * raw_t * (3 - 2 * raw_t)
        elif profile == "ease_in":
            t = raw_t ** 2
        else:
            t = 1 - (1 - raw_t) ** 2
        px, py = _cubic_bezier(start, c1, c2, end, t)
        try:
            pyautogui.moveTo(int(px), int(py), duration=0, _pause=False)
        except Exception:
            pass
        time.sleep(step_delay)


def _human_pause(min_s: float, max_s: float, stop_event=None) -> None:
    total = random.uniform(min_s, max_s)
    start = time.time()
    while time.time() - start < total:
        if stop_event is not None and stop_event.is_set():
            return
        time.sleep(0.1)


def _idle_jiggle() -> None:
    if not pyautogui:
        return
    try:
        x, y   = pyautogui.position()
        sw, sh = pyautogui.size()
        nx = max(80, min(sw - 80, x + random.randint(-120, 120)))
        ny = max(80, min(sh - 80, y + random.randint(-80,  80)))
        _bezier_move(nx, ny, duration=random.uniform(0.3, 0.7))
    except Exception:
        pass


# ── VKBot ─────────────────────────────────────────────────────────────────────

class VKBot:
    def __init__(
        self,
        group_url: str,
        profile_path: str,
        count: int,
        delay_min: float,
        delay_max: float,
        admin_hold: float,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_done: Optional[Callable[[], None]] = None,
        on_cdp_ready: Optional[Callable] = None,
    ):
        self.group_url  = group_url
        self.count      = count
        self.delay_min  = delay_min
        self.delay_max  = delay_max
        self.admin_hold = admin_hold
        self.on_log       = on_log
        self.on_progress  = on_progress
        self.on_done      = on_done
        self.on_cdp_ready = on_cdp_ready
        self._stop_event  = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._log("⏹ Остановка запрошена...")

    def _log(self, msg: str) -> None:
        log.info(msg)
        if self.on_log:
            self.on_log(msg)

    def _progress(self, done: int, total: int) -> None:
        if self.on_progress:
            self.on_progress(done, total)

    def _stopped(self) -> bool:
        return self._stop_event.is_set()

    def _wait_idle(self, total: float, captcha_client: Optional['cdp.CDPClient'] = None) -> None:
        start       = time.time()
        next_jiggle = time.time() + random.uniform(2.0, 4.5)
        next_captcha_check = time.time() + 1.5
        while time.time() - start < total:
            if self._stopped():
                return
            if time.time() >= next_jiggle:
                _idle_jiggle()
                next_jiggle = time.time() + random.uniform(2.5, 6.0)
            # Каждые ~1.5 сек проверяем капчу, чтобы не ждать впустую
            if captcha_client is not None and time.time() >= next_captcha_check:
                try:
                    if self._detect_and_solve_captcha(captcha_client):
                        # Капча была — выходим из ожидания пораньше
                        return
                except Exception:
                    pass
                next_captcha_check = time.time() + 1.5
            time.sleep(0.2)

    # ── Конвертация viewport CSS → физические OS-пиксели (с DPR) ─────────────

    def _scroll_list(self, client: cdp.CDPClient, clicks: int = 8) -> None:
        """Скроллит список участников вниз через pyautogui (реальное колесо мыши).

        pyautogui.scroll() — единственный надёжный способ: VK реагирует только
        на настоящие OS-события, игнорируя JS scrollTop и CDP mouseWheel.
        """
        try:
            origin = client.get_content_origin()
            dpr = float(origin.get("dpr", 1) or 1)
            vx = client.evaluate("window.innerWidth / 2") or 600
            vy = client.evaluate("window.innerHeight / 2") or 400
            sx = int((origin["x"] + vx) * dpr)
            sy = int((origin["y"] + vy) * dpr)
            if pyautogui:
                pyautogui.moveTo(sx, sy, duration=0.1, _pause=False)
                pyautogui.scroll(-clicks, _pause=False)
                return
        except Exception:
            pass
        # Fallback: CDP mouseWheel
        try:
            client.scroll_page(clicks * 80)
        except Exception:
            pass

    def _viewport_to_os(self, client: cdp.CDPClient, vx: float, vy: float) -> tuple:
        """CSS viewport-координата → физическая OS-координата для pyautogui.

        Учитывает devicePixelRatio: на дисплее со 125%/150% масштабом
        Chrome работает в CSS-px, pyautogui (DPI-aware) — в физических.
        """
        origin = client.get_content_origin()
        dpr = float(origin.get("dpr", 1) or 1)
        sx = int((origin["x"] + vx) * dpr)
        sy = int((origin["y"] + vy) * dpr)
        return sx, sy

    def _real_os_click(self, client: cdp.CDPClient, rect: dict,
                        log_label: str = "") -> tuple:
        """Реальный OS-клик через pyautogui — наводит, ждёт, кликает.

        Это самый «честный» способ — Chrome видит настоящий click от реальной
        мыши, CSS :hover триггерится, все React handlers получают trusted event.
        Возвращает (sx, sy) куда был сделан клик.
        """
        vx = rect["x"] + rect["w"] * random.uniform(0.4, 0.6)
        vy = rect["y"] + rect["h"] * random.uniform(0.4, 0.6)
        sx, sy = self._viewport_to_os(client, vx, vy)
        if log_label:
            self._log(f"  → OS-клик{log_label} @ screen=({sx},{sy}) "
                      f"viewport=({int(vx)},{int(vy)})")
        _bezier_move(sx, sy, duration=random.uniform(0.35, 0.6))
        # Дольше «зависаем» — даём CSS :hover триггернуть menu в DOM
        time.sleep(random.uniform(0.3, 0.5))
        if pyautogui:
            try:
                pyautogui.click(sx, sy, _pause=False)
            except Exception as e:
                self._log(f"  ⚠ pyautogui click error: {e}")
        return sx, sy

    # ── Гибридный клик: pyautogui двигает курсор (визуал), CDP кликает (надёжно) ─

    def _click_rect(self, client: cdp.CDPClient, rect: dict) -> None:
        """Кликнуть по DOM-элементу.

        1. pyautogui двигает реальный OS-курсор по Безье — визуальный эффект.
        2. CDP Input.dispatchMouseEvent выполняет настоящий клик внутри
           браузера в viewport-координатах — гарантированно попадает в элемент,
           не зависит от DPI и масштаба Windows.
        """
        vx = rect["x"] + rect["w"] * random.uniform(0.35, 0.65)
        vy = rect["y"] + rect["h"] * random.uniform(0.35, 0.65)

        sx, sy = self._viewport_to_os(client, vx, vy)
        _bezier_move(sx, sy, duration=random.uniform(0.3, 0.6))
        time.sleep(random.uniform(0.08, 0.2))

        try:
            client.click_at_viewport(vx, vy)
        except Exception as e:
            self._log(f"  ⚠ CDP click error: {e}")

    def _click_text_js(self, client: cdp.CDPClient, text: str,
                       popup_only: bool = True) -> bool:
        """Клик по элементу с заданным текстом через JS .click() (надёжный для VK React).

        Сначала двигает курсор визуально (для эффекта человека), затем вызывает .click().
        """
        # Получим rect (для движения курсора) — переиспользуем find_menu_item
        rect = client.find_menu_item(text) if popup_only else None
        if rect:
            vx = rect["x"] + rect["w"] * random.uniform(0.35, 0.65)
            vy = rect["y"] + rect["h"] * random.uniform(0.35, 0.65)
            sx, sy = self._viewport_to_os(client, vx, vy)
            _bezier_move(sx, sy, duration=random.uniform(0.3, 0.55))
            time.sleep(random.uniform(0.08, 0.2))
        # JS-клик — гарантированно триггерит React/Vue handler
        try:
            return client.js_click_text(text, popup_only=popup_only)
        except Exception as e:
            self._log(f"  ⚠ JS click error: {e}")
            return False

    def _hover_rect(self, client: cdp.CDPClient, rect: dict) -> None:
        """Навести курсор: pyautogui визуально + CDP синтетический hover."""
        vx = rect["x"] + rect["w"] * random.uniform(0.35, 0.65)
        vy = rect["y"] + rect["h"] * random.uniform(0.35, 0.65)
        sx, sy = self._viewport_to_os(client, vx, vy)
        _bezier_move(sx, sy, duration=random.uniform(0.25, 0.45))
        try:
            client.hover_at_viewport(vx, vy)
        except Exception:
            pass
        time.sleep(random.uniform(0.3, 0.6))

    def _wait_for(self, finder, timeout: float = 6.0, interval: float = 0.3) -> Optional[dict]:
        """Повторяет finder() пока не вернёт ненулевой результат или не кончится timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._stopped():
                return None
            r = finder()
            if r:
                return r
            time.sleep(interval)
        return None

    # ── Основной цикл ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        client = cdp.CDPClient()
        try:
            if pyautogui is None:
                self._log("❌ Не установлен pyautogui. Запустите install.bat")
                return

            self._log("🔌 Подключаюсь к Chrome (порт 9222)...")
            try:
                client.connect("vk.com")
                self._log(f"  ✅ Подключено: {client.target_url[:70]}")
                origin = client.get_content_origin()
                self._log(
                    f"  📐 Chrome viewport origin: ({origin.get('x')},{origin.get('y')})"
                    f"  DPR={origin.get('dpr')}"
                )
                # Включаем auto-attach для OOPIF (cross-origin iframe'ов VK ID капчи)
                try:
                    client.enable_iframe_discovery()
                    self._log("  ✅ iframe-discovery включен (OOPIF будут прикрепляться)")
                except Exception as e:
                    self._log(f"  ⚠ iframe-discovery: {e}")
                if self.on_cdp_ready:
                    self.on_cdp_ready(client)
            except cdp.CDPError as e:
                self._log(f"❌ {e}")
                return

            self._log("⏳ Переключитесь на окно Chrome (5 сек)...")
            for s in range(5, 0, -1):
                if self._stopped():
                    return
                self._log(f"  {s}...")
                time.sleep(1)

            done             = 0
            unlimited        = self.count == 0
            empty_scrolls    = 0
            MAX_EMPTY        = 10
            consecutive_skip = 0
            MAX_SKIP         = 5   # сколько подряд «уже в базе» до прокрутки

            while (unlimited or done < self.count) and not self._stopped():

                # 0. Проверяем капчу перед каждой итерацией
                self._handle_captcha(client)
                if self._stopped():
                    break

                # 1. Получаем видимых участников из DOM
                try:
                    members = client.get_members()
                except cdp.CDPError as e:
                    self._log(f"❌ CDP: {e}")
                    break

                self._log(f"  🔍 Видно в DOM: {len(members)} участников")
                if not members:
                    empty_scrolls += 1
                    if empty_scrolls >= MAX_EMPTY:
                        self._log("🏁 DOM пуст — возможно конец списка. Выход.")
                        break
                    self._log(f"  ⬇ DOM пуст, прокручиваю ({empty_scrolls}/{MAX_EMPTY})...")
                    self._scroll_list(client, clicks=10)
                    _human_pause(2.5, 4.0, self._stop_event)
                    continue

                # 2. Ищем первого необработанного
                target = None
                skipped_in_view = 0
                for m in members:
                    if storage.is_processed(m["id"]) or storage.is_ignored(m["id"]):
                        skipped_in_view += 1
                        continue
                    target = m
                    break

                if not target:
                    empty_scrolls    += 1
                    consecutive_skip += skipped_in_view
                    if empty_scrolls >= MAX_EMPTY:
                        self._log("🏁 Все новые участники обработаны. Выход.")
                        break
                    self._log(
                        f"  ⬇ Все {skipped_in_view} видимых уже в базе, прокручиваю"
                        f" ({empty_scrolls}/{MAX_EMPTY})..."
                    )
                    self._scroll_list(client, clicks=8)
                    _human_pause(2.0, 3.5, self._stop_event)
                    continue

                empty_scrolls    = 0
                consecutive_skip = 0
                uid = target["id"]
                self._log(f"\n👤 Обрабатываю: {uid}")

                # 3. Скроллим участника в центр экрана
                try:
                    client.scroll_member_into_view(uid)
                except Exception:
                    pass
                _human_pause(0.5, 1.0, self._stop_event)
                if self._stopped():
                    break

                # 4. Назначаем администратором
                if not self._make_admin(client, uid):
                    self._log(f"  ⚠ Не удалось назначить {uid} — НЕ помечаю, попробую дальше")
                    # Закрываем возможные открытые меню
                    if pyautogui:
                        try: pyautogui.press("escape")
                        except Exception: pass
                    _human_pause(2.0, 3.5, self._stop_event)
                    # Прокручиваем дальше — этого участника пробовать смысла нет
                    self._scroll_list(client, clicks=5)
                    # Защита от бесконечного цикла на одном участнике
                    storage.mark_processed(uid, self.group_url)
                    continue

                if self._stopped():
                    storage.mark_processed(uid, self.group_url)
                    break

                # 5. Ждём (с фоновой проверкой капчи каждые 1.5 сек)
                hold = random.uniform(self.admin_hold, self.admin_hold + 5)
                self._log(f"  ⏱ Держим {hold:.0f} сек (с мониторингом капчи)...")
                self._wait_idle(hold, captcha_client=client)

                if self._stopped():
                    storage.mark_processed(uid, self.group_url)
                    break

                # 6. Снимаем с должности
                if not self._remove_admin(client, uid):
                    self._log(f"  ⚠ Не удалось снять {uid} с должности")

                # 7. Фиксируем
                storage.mark_processed(uid, self.group_url)
                done += 1
                self._progress(done, self.count)
                self._log(f"  ✅ {uid} готово ({done}{'/' + str(self.count) if self.count else ''})")

                # 8. Дополнительная пауза после снятия — VK должна закрыть диалог
                _human_pause(2.0, 4.0, self._stop_event)
                # 9. Основная пауза перед следующим
                _human_pause(self.delay_min, self.delay_max, self._stop_event)

            self._log(f"\n🏁 Завершено. Обработано: {done}")

        except Exception as e:
            self._log(f"💥 Ошибка: {e}")
            log.exception("Bot error")
        finally:
            client.close()
            if self.on_done:
                self.on_done()

    # ── Обработка капчи ───────────────────────────────────────────────────────

    def _click_captcha_rect(self, c: cdp.CDPClient, rect: dict,
                              iframe_offset: Optional[dict],
                              main_client: cdp.CDPClient, label: str) -> None:
        """Кликает по чекбоксу.

        rect — viewport-rect внутри контекста c (главная страница или iframe).
        iframe_offset — если c это iframe, передаём rect самого iframe в родителе
        (viewport родителя). Тогда курсор будет двигаться в правильную точку OS,
        а CDP-клик уйдёт в iframe-контекст.
        """
        # Точка клика в системе координат контекста c
        local_vx = rect["x"] + rect["w"] * random.uniform(0.4, 0.6)
        local_vy = rect["y"] + rect["h"] * random.uniform(0.4, 0.6)

        # Для OS-движения курсора нужны экранные координаты.
        # Если это iframe — добавляем offset iframe в родителе, и используем DPR родителя.
        if iframe_offset is not None:
            origin = main_client.get_content_origin()
            dpr = float(origin.get("dpr", 1) or 1)
            screen_vx = iframe_offset["x"] + local_vx
            screen_vy = iframe_offset["y"] + local_vy
            sx = int((origin["x"] + screen_vx) * dpr)
            sy = int((origin["y"] + screen_vy) * dpr)
        else:
            origin = c.get_content_origin()
            dpr = float(origin.get("dpr", 1) or 1)
            sx = int((origin["x"] + local_vx) * dpr)
            sy = int((origin["y"] + local_vy) * dpr)

        self._log(f"  → OS-курсор Безье → screen=({sx},{sy})  iframe_offset={iframe_offset is not None}")

        # 1) Движение курсора по кривой Безье в OS — визуально человеческое
        _bezier_move(sx, sy, duration=random.uniform(0.35, 0.6))
        time.sleep(random.uniform(0.25, 0.45))

        # 2) Клик: для iframe-контекста CDP click_at_viewport идёт в правильный context
        if pyautogui:
            try:
                pyautogui.click(sx, sy, _pause=False)
            except Exception as e:
                self._log(f"  ⚠ pyautogui click error: {e}")

        # 3) Дополнительно CDP-клик в координатах ВНУТРИ контекста c
        try:
            c.click_at_viewport(local_vx, local_vy)
        except Exception:
            pass

    def _try_click_captcha_in_client(self, c: cdp.CDPClient, label: str,
                                       iframe_offset: Optional[dict] = None,
                                       main_client: Optional[cdp.CDPClient] = None) -> bool:
        rect = c.find_captcha_checkbox()
        if not rect:
            return False
        src = rect.get("src", "?")
        self._log(f"🤖 КАПЧА: нашёл чекбокс [{label}] src={src} @ "
                  f"({int(rect['x'])},{int(rect['y'])}) {int(rect['w'])}x{int(rect['h'])}")

        self._click_captcha_rect(c, rect, iframe_offset, main_client or c, label)
        _human_pause(1.2, 2.0, self._stop_event)

        # Повторный клик если чекбокс ещё там
        rect2 = c.find_captcha_checkbox()
        if rect2:
            self._log("  → чекбокс ещё виден, повторный клик")
            self._click_captcha_rect(c, rect2, iframe_offset, main_client or c, label)
            _human_pause(1.0, 1.6, self._stop_event)

        # JS-клик fallback
        rect3 = c.find_captcha_checkbox()
        if rect3:
            self._log("  → чекбокс ещё виден, JS-клик")
            try:
                c.js_click_text("Я не робот", popup_only=False)
            except Exception:
                pass
            _human_pause(1.0, 1.6, self._stop_event)
        return True

    def _iter_popup_clients(self, main_client: cdp.CDPClient):
        """Перебирает все CDP-таргеты (page + iframe), исключая основной таб."""
        import websocket as _ws

        seen = set()
        # 1) Через CDP Target.getTargets — даёт OOPIF iframe'ы
        targets = []
        try:
            targets = main_client.get_all_targets_cdp() or []
        except Exception:
            targets = []
        for t in targets:
            tid = t.get("targetId")
            url = t.get("url", "")
            ttype = t.get("type")
            if not tid or tid in seen:
                continue
            if ttype not in ("page", "iframe", "webview"):
                continue
            if url == main_client.target_url:
                continue
            if url.startswith("chrome://") or url.startswith("devtools://"):
                continue
            seen.add(tid)
            ws_url = main_client.iframe_ws_url(tid)
            popup = cdp.CDPClient(port=main_client.port)
            try:
                popup.ws = _ws.create_connection(
                    ws_url, timeout=8, origin="http://localhost:9222"
                )
                popup.target_url = url
            except Exception:
                continue
            try:
                yield popup, url, ttype
            finally:
                popup.close()

        # 2) Fallback через /json HTTP
        try:
            import requests as _rq
            tabs = _rq.get(f"http://localhost:{main_client.port}/json", timeout=3).json()
        except Exception:
            return
        for t in tabs:
            tid = t.get("id")
            ttype = t.get("type")
            if tid in seen or ttype not in ("page", "iframe"):
                continue
            url = t.get("url", "")
            ws_url = t.get("webSocketDebuggerUrl")
            if not ws_url or url == main_client.target_url:
                continue
            if url.startswith("chrome://") or url.startswith("devtools://"):
                continue
            seen.add(tid)
            popup = cdp.CDPClient(port=main_client.port)
            try:
                popup.ws = _ws.create_connection(
                    ws_url, timeout=8, origin="http://localhost:9222"
                )
                popup.target_url = url
            except Exception:
                continue
            try:
                yield popup, url, ttype
            finally:
                popup.close()

    # JS для поиска чекбокса 'Я не робот' в любом DOM-контексте (включая iframe-сессию)
    _CAPTCHA_FIND_JS = r"""
    (function() {
        function norm(s) { return (s || '').replace(/[\s ]+/g, ' ').trim().toLowerCase(); }
        function ok(r) {
            return r.width > 0 && r.height > 0
                && r.right > 0 && r.bottom > 0
                && r.left < (window.innerWidth + 100)
                && r.top  < (window.innerHeight + 100);
        }
        function ancestor(el) {
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
        const found = [];
        try {
            for (const el of document.querySelectorAll(
                '[class*="Checkbox__title"], [class*="Checkbox-module__title"]'
            )) {
                const t = norm(el.textContent);
                if (!t.includes('не робот') && !t.includes('robot')) continue;
                const c = ancestor(el) || el.parentElement || el;
                const r = c.getBoundingClientRect();
                if (ok(r)) found.push({rect: r, src: 'vkc-title', txt: t});
            }
        } catch (e) {}
        try {
            for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
                const wrap = cb.closest('label')
                    || cb.closest('[class*="Checkbox"]')
                    || cb.parentElement;
                if (!wrap) continue;
                const t = norm(wrap.textContent);
                if (!t.includes('не робот') && !t.includes('robot')) continue;
                const r = wrap.getBoundingClientRect();
                if (ok(r)) found.push({rect: r, src: 'input', txt: t});
            }
        } catch (e) {}
        try {
            for (const el of document.querySelectorAll('div, span, p, label, button')) {
                if (el.children.length > 2) continue;
                const t = norm(el.textContent);
                if (t !== 'я не робот' && t !== "i'm not a robot"
                    && t !== 'i am not a robot') continue;
                const c = ancestor(el) || el.parentElement || el;
                const r = c.getBoundingClientRect();
                if (ok(r)) found.push({rect: r, src: 'text', txt: t});
            }
        } catch (e) {}
        if (!found.length) return null;
        const f = found[0];
        return {x: f.rect.left, y: f.rect.top, w: f.rect.width, h: f.rect.height,
                src: f.src, txt: f.txt};
    })()
    """

    def _try_click_captcha_in_iframe_session(self, main_client: cdp.CDPClient,
                                                session_id: str, url: str,
                                                iframe_offset: Optional[dict]) -> bool:
        """Найти и кликнуть чекбокс через iframe-сессию CDP."""
        rect = main_client.evaluate_in_session(self._CAPTCHA_FIND_JS, session_id)
        if not rect:
            return False
        short = url[:70].replace("https://", "").replace("http://", "")
        self._log(f"🤖 КАПЧА: нашёл чекбокс в iframe-сессии [{short}] "
                  f"src={rect.get('src')} @ ({int(rect['x'])},{int(rect['y'])}) "
                  f"{int(rect['w'])}x{int(rect['h'])}")

        # Если не знаем offset iframe в родителе — считаем что (0,0) (часто так и есть)
        if iframe_offset is None:
            iframe_offset = {"x": 0, "y": 0}

        origin = main_client.get_content_origin()
        dpr = float(origin.get("dpr", 1) or 1)

        local_vx = rect["x"] + rect["w"] * random.uniform(0.4, 0.6)
        local_vy = rect["y"] + rect["h"] * random.uniform(0.4, 0.6)
        target_vx = iframe_offset["x"] + local_vx
        target_vy = iframe_offset["y"] + local_vy
        sx = int((origin["x"] + target_vx) * dpr)
        sy = int((origin["y"] + target_vy) * dpr)

        self._log(f"  → OS-курсор Безье → screen=({sx},{sy})")

        # 1) Движение курсора по Безье + OS-клик (визуально + триггерит :hover)
        _bezier_move(sx, sy, duration=random.uniform(0.4, 0.65))
        time.sleep(random.uniform(0.25, 0.45))
        if pyautogui:
            try:
                pyautogui.click(sx, sy, _pause=False)
            except Exception as e:
                self._log(f"  ⚠ pyautogui click error: {e}")

        # 2) CDP-клик в координатах iframe — гарантированный trusted event внутри iframe
        try:
            main_client.click_in_session(local_vx, local_vy, session_id)
        except Exception:
            pass

        _human_pause(1.2, 2.2, self._stop_event)

        # Повторный клик если ещё виден
        rect2 = main_client.evaluate_in_session(self._CAPTCHA_FIND_JS, session_id)
        if rect2:
            self._log("  → чекбокс ещё виден, повторный клик")
            local_vx2 = rect2["x"] + rect2["w"] / 2
            local_vy2 = rect2["y"] + rect2["h"] / 2
            try:
                main_client.click_in_session(local_vx2, local_vy2, session_id)
            except Exception:
                pass
            target_vx2 = iframe_offset["x"] + local_vx2
            target_vy2 = iframe_offset["y"] + local_vy2
            sx2 = int((origin["x"] + target_vx2) * dpr)
            sy2 = int((origin["y"] + target_vy2) * dpr)
            _bezier_move(sx2, sy2, duration=0.4)
            if pyautogui:
                try: pyautogui.click(sx2, sy2, _pause=False)
                except Exception: pass
            _human_pause(1.0, 1.6, self._stop_event)
        return True

    def _detect_and_solve_captcha(self, main_client: cdp.CDPClient) -> bool:
        """Один проход поиска капчи в main + iframe-сессиях + blind-click."""
        # 1) Главный фрейм
        if self._try_click_captcha_in_client(main_client, "main"):
            return True

        # 2) Включаем iframe-discovery (если ещё нет)
        try:
            main_client.enable_iframe_discovery()
        except Exception:
            pass

        # 3) Координаты iframe в родителе
        try:
            iframe_offset = main_client.find_captcha_iframe_in_parent()
        except Exception:
            iframe_offset = None

        # 4) Прикрепляем уже существующие OOPIF-таргеты вручную + перебираем сессии
        try:
            n = main_client.attach_existing_iframes()
            if n:
                self._log(f"  📎 attach_existing_iframes: прикреплено {n} новых таргетов")
        except Exception:
            pass
        sessions_tried = 0
        try:
            sessions = main_client.get_iframe_sessions()
        except Exception:
            sessions = {}
        for sid, info in sessions.items():
            url = info.get("url", "")
            if not url:
                continue
            score = 0
            if "id.vk.com" in url: score += 10
            if "captcha" in url: score += 10
            if "vkid" in url: score += 5
            if score == 0:
                continue
            sessions_tried += 1
            if self._try_click_captcha_in_iframe_session(main_client, sid, url, iframe_offset):
                return True

        # 5) Старый путь — popup-таргеты (page-level)
        for popup, url, ttype in self._iter_popup_clients(main_client):
            short = (url or ttype)[:70].replace("https://", "").replace("http://", "")
            offset = iframe_offset if ttype == "iframe" else None
            if self._try_click_captcha_in_client(popup, short,
                                                    iframe_offset=offset,
                                                    main_client=main_client):
                return True

        # 6) ⚠ BLIND-CLICK fallback: если в родителе найден iframe VK ID капчи,
        # но ни одна CDP-сессия не дала чекбокс — кликаем по расчётной позиции.
        if iframe_offset:
            src = iframe_offset.get("src", "")
            if ("not_robot_captcha" in src or "id.vk.com" in src
                    or "vkid" in src or "captcha" in src):
                self._log(f"  ⚠ iframe есть, но через CDP-сессии не достучаться "
                          f"(sessions_tried={sessions_tried}) — blind-click")
                self._blind_click_captcha_iframe(main_client, iframe_offset)
                return True

        # 7) Ничего не нашли — диагностика (rate-limited)
        self._log_captcha_diag(main_client, "no-captcha")
        return False

    def _log_captcha_diag(self, main_client: cdp.CDPClient, tag: str = "") -> None:
        """Логирует диагностику капчи: iframe в DOM + iframe-сессии + targets.
        Вызывается каждый раз когда капча подозревается но не найдена,
        с rate limit ~1 раз в 3 сек чтобы не флудить логи.
        """
        now = time.time()
        last = getattr(self, "_last_captcha_diag", 0)
        if now - last < 3.0:
            return
        self._last_captcha_diag = now
        prefix = f"[{tag}] " if tag else ""
        try:
            ifr = main_client.find_captcha_iframe_in_parent()
            if ifr:
                self._log(f"  {prefix}📦 iframe: src={ifr.get('src','')[:80]} "
                          f"rect=({int(ifr['x'])},{int(ifr['y'])}) "
                          f"{int(ifr['w'])}x{int(ifr['h'])}")
            else:
                self._log(f"  {prefix}📦 iframe-кандидата нет в DOM родителя")
        except Exception as e:
            self._log(f"  (iframe diag: {e})")
        try:
            sessions = main_client.get_iframe_sessions()
            self._log(f"  {prefix}🧩 iframe-сессий: {len(sessions)}")
            for sid, info in list(sessions.items())[:6]:
                self._log(f"     sid={sid[:10]}... url={info.get('url','')[:90]}")
        except Exception as e:
            self._log(f"  (sessions diag: {e})")

    def _blind_click_captcha_iframe(self, main_client: cdp.CDPClient,
                                       iframe_offset: dict) -> bool:
        """Fallback: клик по расчётной позиции чекбокса в iframe VK ID капчи.

        Когда не удалось получить доступ к содержимому iframe через CDP-сессию,
        используем фиксированную геометрию: диалог ~380x430 центрирован в iframe,
        чекбокс находится примерно на 38% по X и 71% по Y от верха диалога.
        """
        DIALOG_W = 380.0
        DIALOG_H = 430.0
        CB_REL_X = 0.38   # 38% от левого края диалога
        CB_REL_Y = 0.71   # 71% от верха диалога

        iframe_cx = iframe_offset["x"] + iframe_offset["w"] / 2
        iframe_cy = iframe_offset["y"] + iframe_offset["h"] / 2
        dialog_left = iframe_cx - DIALOG_W / 2
        dialog_top  = iframe_cy - DIALOG_H / 2
        cb_vx = dialog_left + DIALOG_W * CB_REL_X
        cb_vy = dialog_top  + DIALOG_H * CB_REL_Y

        origin = main_client.get_content_origin()
        dpr = float(origin.get("dpr", 1) or 1)
        sx = int((origin["x"] + cb_vx) * dpr)
        sy = int((origin["y"] + cb_vy) * dpr)

        self._log(f"  🎯 BLIND-CLICK по расчётной позиции чекбокса: "
                  f"viewport=({int(cb_vx)},{int(cb_vy)}) screen=({sx},{sy})")

        # Движение Безье + OS-клик
        _bezier_move(sx, sy, duration=random.uniform(0.4, 0.65))
        time.sleep(random.uniform(0.3, 0.5))
        if pyautogui:
            try:
                pyautogui.click(sx, sy, _pause=False)
            except Exception as e:
                self._log(f"  ⚠ pyautogui click error: {e}")

        # Дублирующий CDP-клик через родителя — событие уйдёт в iframe
        try:
            main_client.click_at_viewport(cb_vx, cb_vy)
        except Exception:
            pass

        _human_pause(1.2, 2.0, self._stop_event)
        return True

    def _handle_captcha(self, main_client: cdp.CDPClient, wait_seconds: float = 0.0) -> bool:
        """Проверить наличие капчи VK и обработать её.

        wait_seconds — сколько секунд ждать ПОЯВЛЕНИЯ капчи (с интервальным
        опросом). Используется после действий, после которых VK может показать
        капчу не мгновенно. 0 = только один быстрый чек.
        Возвращает True если капча была обнаружена и решена.
        """
        # Первый быстрый проход
        if self._detect_and_solve_captcha(main_client):
            return True

        # Если нет — логируем диагностику (rate-limited)
        if wait_seconds > 0:
            self._log_captcha_diag(main_client, "wait")

        # Polling — ждём появления капчи
        if wait_seconds > 0:
            deadline = time.time() + wait_seconds
            while time.time() < deadline and not self._stopped():
                time.sleep(0.5)
                if self._detect_and_solve_captcha(main_client):
                    return True

        # Если в DOM есть текст «не робот», но кликнуть не смогли — ждём вручную
        try:
            visible = main_client.is_captcha_dialog_visible()
        except Exception:
            visible = False
        if visible:
            try:
                dbg = main_client.debug_captcha_state()
                self._log(f"🤖 КАПЧА: диалог виден, но чекбокс не найден. DEBUG: {dbg}")
            except Exception:
                pass
            self._log("🤖 КАПЧА: диалог виден, но недоступен через DOM — решите вручную (до 2 мин)")
            deadline = time.time() + 120
            while time.time() < deadline:
                if self._stopped():
                    return True
                try:
                    if not main_client.is_captcha_dialog_visible():
                        self._log("  ✅ Капча решена, продолжаю")
                        _human_pause(1.0, 2.0, self._stop_event)
                        return True
                except Exception:
                    pass
                # И пытаемся каждые 2 сек найти чекбокс автоматически
                if self._detect_and_solve_captcha(main_client):
                    return True
                time.sleep(2)
            self._log("  ⚠ Капча не решена за 2 минуты — останавливаю")
            self._stop_event.set()
            return True

        return False

    # ── Навести курсор на строку (делает кнопку «...» видимой) ──────────────

    def _dump_member(self, client: cdp.CDPClient, uid: str) -> None:
        """Логирует что есть на строке участника — для диагностики."""
        try:
            info = client.diagnose_member(uid)
        except Exception as e:
            self._log(f"  (диагностика недоступна: {e})")
            return
        if not info or info.get("error"):
            self._log(f"  📋 {info}")
            return
        self._log(f"  📋 link {info.get('linkHref')} rect={info.get('linkRect')}")
        for el in info.get("onRowElements", []):
            self._log(
                f"     {el['tag']} aria={el['aria']!r} role={el['role']!r} "
                f"cls={el['cls']!r} rect={el['rect']}"
            )

    def _dump_menus(self, client: cdp.CDPClient) -> None:
        """Логирует тексты в открытых popup'ах — для диагностики не найденных пунктов."""
        try:
            popups = client.dump_popups()
        except Exception as e:
            self._log(f"  (диагностика недоступна: {e})")
            return
        if not popups:
            self._log("  📋 Открытых popup'ов нет — меню не появилось.")
            return
        for p in popups:
            self._log(f"  📋 popup {p.get('sel')}: {p.get('items')}")

    def _hover_row(self, client: cdp.CDPClient, uid: str) -> None:
        """Двигает курсор на строку участника + CDP hover, чтобы CSS :hover показал «...»."""
        row_rect = client.get_member_row_rect(uid)
        if not row_rect:
            return
        self._hover_rect(client, row_rect)

    # ── Поддержка hover'а пока меню должно оставаться открытым ───────────────

    def _sustain_hover(self, client: cdp.CDPClient, rect: dict, duration: float = 0.4) -> None:
        """Многократно дёргает CDP mouseMoved в центре rect — удерживает CSS :hover."""
        vx = rect["x"] + rect["w"] / 2
        vy = rect["y"] + rect["h"] / 2
        end = time.time() + duration
        while time.time() < end:
            try:
                client.dispatch_mouse("mouseMoved", vx, vy)
            except Exception:
                pass
            time.sleep(0.08)

    def _open_action_menu(self, client: cdp.CDPClient, uid: str, probe_text: str,
                          attempts: int = 3) -> Optional[dict]:
        """Открыть меню «...» у участника и вернуть rect пункта probe_text.

        Стратегия — для hover-based меню VK:
          1. Скролл участника в видимую область.
          2. Hover на «...» (OS-курсор + CDP mouseMoved, многократно).
          3. Ждём появление probe_text в DOM.
          4. Сразу переводим CDP mouseMoved на rect пункта (удерживает меню открытым).
        """
        # Закрыть любые открытые попапы перед началом
        try:
            client.evaluate("document.activeElement?.blur()")
        except Exception:
            pass
        if pyautogui:
            try: pyautogui.press("escape")
            except Exception: pass
        try: client.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',keyCode:27,bubbles:true}))")
        except Exception: pass
        time.sleep(0.3)

        for attempt in range(1, attempts + 1):
            if self._stopped():
                return None
            try:
                client.scroll_member_into_view(uid)
            except Exception:
                pass
            _human_pause(0.3, 0.6, self._stop_event)

            # Находим кнопку «...»
            btn_rect = client.get_member_action_button_rect(uid)
            if not btn_rect:
                # Hover'нём по строке чтобы кнопка появилась (для hover-only кнопок)
                row_rect = client.get_member_row_rect(uid)
                if row_rect:
                    self._sustain_hover(client, row_rect, duration=0.5)
                    btn_rect = client.get_member_action_button_rect(uid)
            if not btn_rect:
                if attempt == attempts:
                    self._log("  ⚠ Кнопка «...» не найдена")
                    self._dump_member(client, uid)
                _human_pause(0.5, 1.0, self._stop_event)
                continue

            self._log(
                f"  → hover на «...» @ ({int(btn_rect['x'])},{int(btn_rect['y'])})"
                f" {int(btn_rect['w'])}x{int(btn_rect['h'])}"
                f"{' [hidden]' if btn_rect.get('hidden') else ''}"
                f" [#{attempt}]"
            )

            # 1) Визуально двигаем OS-курсор на кнопку (с учётом DPR)
            bvx = btn_rect["x"] + btn_rect["w"] / 2
            bvy = btn_rect["y"] + btn_rect["h"] / 2
            bsx, bsy = self._viewport_to_os(client, bvx, bvy)
            _bezier_move(bsx, bsy, duration=random.uniform(0.3, 0.55))

            # 2) Удерживаем OS-курсор на кнопке — CSS :hover триггерится от реальной мыши
            time.sleep(random.uniform(0.4, 0.7))

            # 3) Меню могло появиться от OS-hover. Если нет — настоящий OS-клик
            item = client.find_menu_item(probe_text)
            if not item:
                self._log("  ↻ hover не открыл меню — настоящий OS-клик")
                if pyautogui:
                    try:
                        pyautogui.click(bsx, bsy, _pause=False)
                    except Exception:
                        pass
                _human_pause(0.5, 0.9, self._stop_event)
                item = client.find_menu_item(probe_text)

            if not item:
                self._log("  ↻ Ни hover, ни OS-клик не сработали — CDP fallback")
                try:
                    client.click_at_viewport(bvx, bvy)
                except Exception:
                    pass
                _human_pause(0.4, 0.7, self._stop_event)
                # Поддерживаем hover дальше — на случай если меню открылось но требует hover
                self._sustain_hover(client, btn_rect, duration=0.4)
                item = client.find_menu_item(probe_text)

            if not item:
                self._log("  ↻ Ни hover, ни клик не открыли меню — JS .click() fallback")
                try:
                    client.js_click_member_action(uid)
                except Exception:
                    pass
                _human_pause(0.5, 0.9, self._stop_event)
                self._sustain_hover(client, btn_rect, duration=0.3)
                item = client.find_menu_item(probe_text)

            if item:
                # 4) НЕМЕДЛЕННО переводим OS-курсор на пункт меню — hover переходит
                # с «...» на меню, и оно остаётся открытым.
                ivx = item["x"] + item["w"] / 2
                ivy = item["y"] + item["h"] / 2
                isx, isy = self._viewport_to_os(client, ivx, ivy)
                try:
                    if pyautogui:
                        pyautogui.moveTo(isx, isy, duration=0.15, _pause=False)
                    client.dispatch_mouse("mouseMoved", ivx, ivy)
                except Exception:
                    pass
                return item

            # Меню не открылось — закрываем и пробуем заново
            if pyautogui:
                try: pyautogui.press("escape")
                except Exception: pass
            _human_pause(0.6, 1.0, self._stop_event)

        self._log(f"  ⚠ Меню не удалось открыть после {attempts} попыток")
        self._dump_menus(client)
        return None

    # ── Назначить администратором ─────────────────────────────────────────────

    def _make_admin(self, client: cdp.CDPClient, uid: str) -> bool:
        # 1. Открываем меню и получаем rect «Назначить руководителем»
        item = self._open_action_menu(client, uid, "Назначить руководителем")
        if not item:
            return False
        if self._stopped():
            return False

        # 2. Курсор уже на пункте меню (после _open_action_menu).
        # Делаем настоящий OS-клик там же — это trusted event, надёжно сработает.
        ivx = item["x"] + item["w"] / 2
        ivy = item["y"] + item["h"] / 2
        isx, isy = self._viewport_to_os(client, ivx, ivy)
        time.sleep(random.uniform(0.15, 0.3))
        if pyautogui:
            try:
                pyautogui.click(isx, isy, _pause=False)
            except Exception:
                pass
        # JS-fallback на случай если OS-клик не сработал
        try:
            client.js_click_text("Назначить руководителем", popup_only=True)
        except Exception:
            pass
        self._log("  → клик «Назначить руководителем»")
        _human_pause(1.2, 2.2, self._stop_event)
        if self._stopped():
            return False

        # Опция «Администратор» — JS-клик
        ok = self._wait_for(
            lambda: self._click_text_js(client, "Администратор", popup_only=False),
            timeout=6
        )
        if not ok:
            self._log("  ⚠ Опция «Администратор» не найдена / клик не прошёл")
            self._dump_menus(client)
            if pyautogui:
                pyautogui.press("escape")
            return False
        self._log("  → выбрана «Администратор»")
        _human_pause(0.6, 1.2, self._stop_event)
        if self._stopped():
            return False

        # Кнопка «Сохранить» — можно через mouse-event (это обычная кнопка)
        save = self._wait_for(
            lambda: client.find_confirm_button("Сохранить"), timeout=6
        )
        if not save:
            self._log("  ⚠ Кнопка «Сохранить» не найдена")
            self._dump_menus(client)
            if pyautogui:
                pyautogui.press("escape")
            return False
        self._log("  → нажимаю «Сохранить»")
        self._click_rect(client, save)
        try:
            client.js_click_text("Сохранить", popup_only=False)
        except Exception:
            pass
        _human_pause(0.8, 1.3, self._stop_event)
        if self._stopped():
            return False

        # Финальное подтверждение: диалог «Назначение администратором»
        confirm = self._wait_for(
            lambda: client.find_confirm_button("Назначить администратором"),
            timeout=6,
        )
        if not confirm:
            self._log("  ⚠ Кнопка «Назначить администратором» (подтверждение) не найдена")
            self._dump_menus(client)
            if pyautogui:
                pyautogui.press("escape")
            return False
        self._log("  → подтверждаю «Назначить администратором»")
        self._click_rect(client, confirm)
        try:
            client.js_click_text("Назначить администратором", popup_only=False)
        except Exception:
            pass

        # VK может показать капчу «Я не робот» — ищем её до 12 сек.
        # Начинаем СРАЗУ, без _human_pause, чтобы не упустить.
        self._log("  🔎 жду появления капчи (до 12 сек)...")
        self._handle_captcha(client, wait_seconds=12.0)
        if self._stopped():
            return False
        return True

    # ── Снять с должности ─────────────────────────────────────────────────────

    def _remove_admin(self, client: cdp.CDPClient, uid: str) -> bool:
        # 1. Открываем меню. У админа пункт обычно — «Разжаловать»
        item = self._open_action_menu(client, uid, "Разжаловать")
        if not item:
            item = self._open_action_menu(client, uid, "Убрать из руководителей")
        if not item:
            item = self._open_action_menu(client, uid, "Снять с должности")
        if not item:
            return False
        if self._stopped():
            return False

        # 2. Курсор уже на пункте — настоящий OS-клик
        ivx = item["x"] + item["w"] / 2
        ivy = item["y"] + item["h"] / 2
        isx, isy = self._viewport_to_os(client, ivx, ivy)
        time.sleep(random.uniform(0.15, 0.3))
        if pyautogui:
            try:
                pyautogui.click(isx, isy, _pause=False)
            except Exception:
                pass
        for txt in ("Разжаловать", "Убрать из руководителей", "Снять с должности"):
            try:
                if client.js_click_text(txt, popup_only=True):
                    break
            except Exception:
                pass
        self._log("  → клик пункта снятия")
        _human_pause(1.0, 2.0, self._stop_event)
        if self._stopped():
            return False

        # 3. Подтверждение в плашке (как у назначения — большая кнопка справа)
        btn = self._wait_for(
            lambda: (client.find_confirm_button("Разжаловать")
                     or client.find_confirm_button("Убрать")
                     or client.find_confirm_button("Снять")
                     or client.find_confirm_button("Подтвердить")),
            timeout=4,
        )
        if btn:
            self._log("  → подтверждаю снятие")
            self._click_rect(client, btn)
            for txt in ("Разжаловать", "Убрать", "Снять", "Подтвердить"):
                try:
                    if client.js_click_text(txt, popup_only=False):
                        break
                except Exception:
                    pass
        _human_pause(1.0, 1.6, self._stop_event)
        return True

