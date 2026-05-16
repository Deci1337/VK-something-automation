"""
Автоопределение CSS-селекторов VK.

Работает в двух режимах:
  1. open_chrome()  — открывает Chrome с профилем и отладочным портом
  2. scan()         — подключается к уже открытому Chrome и ищет селекторы
"""
import logging
import os
import socket
import subprocess
import time
from typing import Callable, Optional

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

log = logging.getLogger("detector")

DEBUG_PORT = 9222

CANDIDATES = {
    "member_row": [
        "div.vkuiRichCell__host",
        "div[class*='RichCell__host']",
        "div[class*='RichCell']",
        "li[class*='RichCell']",
    ],
    "member_more_btn": [
        "button.vkuiIconButton",
        "button[class*='IconButton']",
        "button[aria-label='Ещё']",
        "button[aria-label='More']",
    ],
    "member_link": [
        "a.vkuiAvatar__host",
        "a[class*='Avatar__host']",
        "a[class*='RichAvatar']",
    ],
    "make_admin_item": [
        "//span[contains(text(),'Назначить руководителем')]",
        "//div[contains(text(),'Назначить руководителем')]",
        "//*[contains(text(),'Назначить руководителем')]",
        "//*[contains(text(),'Назначить администратором')]",
    ],
    "admin_confirm_btn": [
        "//button[contains(@class,'vkuiButton') and contains(.,'Назначить')]",
        "//button[contains(.,'Назначить')]",
        "//button[contains(.,'Сохранить')]",
    ],
    "remove_admin_item": [
        "//span[contains(text(),'Убрать из руководителей')]",
        "//div[contains(text(),'Убрать из руководителей')]",
        "//*[contains(text(),'Убрать из руководителей')]",
        "//span[contains(text(),'Снять с должности')]",
        "//*[contains(text(),'Снять с должности')]",
    ],
    "remove_confirm_btn": [
        "//button[contains(.,'Убрать') and contains(@class,'vkuiButton')]",
        "//button[contains(.,'Снять') and contains(@class,'vkuiButton')]",
        "//button[contains(.,'Убрать')]",
        "//button[contains(.,'Подтвердить')]",
    ],
    "captcha_iframe": [
        "//iframe[contains(@src,'vk.com')]",
        "//iframe",
    ],
    "captcha_checkbox": [
        ".vkc__Checkbox-module__Checkbox",
        "[class*='Checkbox-module__Checkbox']",
        "input[type='checkbox']",
    ],
}

CSS_KEYS = {"member_row", "member_more_btn", "member_link", "captcha_checkbox"}


def parse_html_selectors(html: str) -> dict:
    """
    Извлекает CSS-селекторы из вставленного outerHTML строки участника.
    Пользователь копирует HTML через DevTools → ПКМ → Copy outerHTML.
    """
    import re
    result = {}

    def best_class(tag: str, priority_words: list) -> str:
        m = re.search(rf'<{tag}[^>]+class="([^"]+)"', html, re.IGNORECASE)
        if not m:
            return ""
        classes = m.group(1).split()
        for word in priority_words:
            cls = next((c for c in classes if word in c), None)
            if cls:
                return cls
        return next((c for c in classes if c.startswith("vkui")), classes[0] if classes else "")

    # member_row — первый div
    cls = best_class("div", ["RichCell", "Cell", "MemberRow", "Row"])
    if cls:
        result["member_row"] = f"div.{cls}"

    # member_link — первый <a>
    cls = best_class("a", ["Avatar", "Photo", "Link"])
    if cls:
        result["member_link"] = f"a.{cls}"

    # member_more_btn — первый <button>
    cls = best_class("button", ["IconButton", "ActionButton", "MoreButton", "Button"])
    if cls:
        result["member_more_btn"] = f"button.{cls}"

    return result


def _chrome_version() -> int:
    """Читает мажорную версию установленного Chrome."""
    import re
    exe = _chrome_exe()
    try:
        out = subprocess.check_output([exe, "--version"],
                                      stderr=subprocess.DEVNULL).decode()
        m = re.search(r"(\d+)\.", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    # Fallback: читаем из реестра Windows
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Google\Chrome\BLBeacon")
        val, _ = winreg.QueryValueEx(key, "version")
        m = re.search(r"(\d+)\.", val)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0


def _chrome_exe() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""),
                     r"Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return "chrome"


def open_chrome(profile_path: str, group_url: str,
                on_log: Optional[Callable[[str], None]] = None) -> bool:
    """
    Открывает Chrome с профилем и отладочным портом 9222.
    Возвращает True если успешно запущен.
    """
    def lg(m):
        log.info(m)
        if on_log: on_log(m)

    url = group_url.rstrip("/")
    for suffix in ["/settings/subscribers", "/members", "/settings"]:
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    url = url + "/settings/subscribers"

    exe = _chrome_exe()
    args = [
        exe,
        f"--remote-debugging-port={DEBUG_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if profile_path and os.path.exists(profile_path):
        # user-data-dir — папка НАД "Default", не сам Default
        udd = profile_path
        if os.path.basename(udd).lower() == "default":
            udd = os.path.dirname(udd)
        args.append(f"--user-data-dir={udd}")
    args.append(url)

    import socket

    # Если порт уже открыт — Chrome уже запущен с debug-портом
    try:
        with socket.create_connection(("localhost", DEBUG_PORT), timeout=1):
            lg(f"✅ Chrome уже слушает порт {DEBUG_PORT} — можно сканировать")
            return True
    except Exception:
        pass

    # Проверяем, запущен ли Chrome вообще (без debug-порта)
    chrome_running = False
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
            stderr=subprocess.DEVNULL
        ).decode("cp866", errors="ignore")
        chrome_running = "chrome.exe" in out.lower()
    except Exception:
        pass

    if chrome_running:
        lg("⚠️  Chrome уже запущен БЕЗ порта отладки!")
        lg("   Закройте все окна Chrome, затем нажмите «Открыть Chrome» снова.")
        return False

    try:
        subprocess.Popen(args)
    except Exception as e:
        lg(f"❌ Не удалось запустить Chrome: {e}")
        lg(f"   Путь к Chrome: {exe}")
        return False

    lg("⏳ Ожидаю запуска Chrome...")
    for i in range(15):
        time.sleep(1)
        try:
            with socket.create_connection(("localhost", DEBUG_PORT), timeout=1):
                lg(f"✅ Chrome запущен с портом {DEBUG_PORT}")
                lg("📌 Дождитесь загрузки страницы участников, затем нажмите «Сканировать»")
                return True
        except Exception:
            pass

    lg(f"❌ Chrome не открыл порт {DEBUG_PORT} за 15 секунд")
    lg("   Возможные причины:")
    lg("   • В фоне остался процесс chrome.exe — откройте Диспетчер задач")
    lg("     (Ctrl+Shift+Esc) и завершите ВСЕ процессы chrome.exe, затем повторите")
    lg("   • Антивирус блокирует отладочный порт")
    return False


def scan(on_log: Optional[Callable[[str], None]] = None) -> dict:
    """
    Подключается к уже открытому Chrome (порт 9222) и ищет селекторы.
    """
    def lg(m):
        log.info(m)
        if on_log: on_log(m)

    result = {}
    driver = None

    try:
        lg(f"🔌 Проверяю порт {DEBUG_PORT}...")

        try:
            with socket.create_connection(("localhost", DEBUG_PORT), timeout=4):
                pass
        except Exception:
            lg(f"❌ Chrome не слушает порт {DEBUG_PORT}")
            lg("   Сначала нажмите «Открыть Chrome» (Шаг 1) и дождитесь загрузки страницы")
            return result

        lg("✅ Порт открыт, подключаюсь...")

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        ver = _chrome_version()
        patcher = uc.Patcher(version_main=ver if ver else None)
        patcher.auto()

        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"localhost:{DEBUG_PORT}")
        svc = Service(executable_path=patcher.executable_path)
        driver = webdriver.Chrome(service=svc, options=opts)
        driver.set_page_load_timeout(10)
        driver.implicitly_wait(3)
        lg(f"✅ Подключился. Страница: {driver.title}")
        lg("🔍 Сканирую элементы...")

        for key, candidates in CANDIDATES.items():
            is_css = key in CSS_KEYS
            found = None
            for candidate in candidates:
                try:
                    by = By.CSS_SELECTOR if is_css else By.XPATH
                    els = driver.find_elements(by, candidate)
                    if els:
                        found = candidate
                        lg(f"  ✅ {key}: {candidate}")
                        break
                except Exception:
                    continue
            if not found:
                lg(f"  ⚠  {key}: не найден")
            else:
                result[key] = found

    except Exception as e:
        lg(f"❌ Ошибка подключения: {e}")
        lg("   Убедитесь что Chrome открыт через кнопку «Открыть Chrome»")
    finally:
        try:
            if driver:
                # Разрываем соединение не закрывая браузер
                driver.service.stop()
        except Exception:
            pass

    return result
