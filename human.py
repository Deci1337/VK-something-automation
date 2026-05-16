"""
Человекоподобное поведение.

Движения мыши — через pyautogui (НАСТОЯЩИЙ ОС-курсор, видно как двигается).
Кривые Безье с рандомными контрольными точками и случайной скоростью.
"""
import random
import time
import math
from typing import Tuple, Optional

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

try:
    import pyautogui
    pyautogui.FAILSAFE = False  # Не падать при движении в угол экрана
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
    pyautogui.PAUSE = 0
    PYAUTOGUI_OK = True
except Exception:
    PYAUTOGUI_OK = False


# ─── Паузы ───────────────────────────────────────────────────────────────────

def pause(min_s: float = 0.4, max_s: float = 1.2) -> None:
    time.sleep(random.uniform(min_s, max_s))


def long_pause(min_s: float = 8.0, max_s: float = 20.0) -> None:
    """Пауза между участниками."""
    time.sleep(random.uniform(min_s, max_s))


def micro_pause() -> None:
    """Крошечная пауза (имитация реакции руки)."""
    time.sleep(random.uniform(0.05, 0.18))


# ─── Безье ───────────────────────────────────────────────────────────────────

def _cubic_bezier(p0, p1, p2, p3, t: float) -> Tuple[float, float]:
    u = 1 - t
    x = u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0]
    y = u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1]
    return x, y


def _random_control_points(start, end):
    """Два случайных контрольных точки для кубической кривой Безье."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.hypot(dx, dy) or 1

    # Отклонение пропорционально расстоянию, но не слишком большое
    dev = min(dist * random.uniform(0.15, 0.45), 120)

    c1 = (
        start[0] + dx * random.uniform(0.2, 0.4) + random.uniform(-dev, dev),
        start[1] + dy * random.uniform(0.2, 0.4) + random.uniform(-dev, dev),
    )
    c2 = (
        start[0] + dx * random.uniform(0.6, 0.8) + random.uniform(-dev, dev),
        start[1] + dy * random.uniform(0.6, 0.8) + random.uniform(-dev, dev),
    )
    return c1, c2


def _bezier_steps(start, end) -> list:
    """
    Возвращает список (x, y) вдоль кривой Безье.
    Количество шагов и «ускорение/торможение» — случайные.
    """
    dist = math.hypot(end[0] - start[0], end[1] - start[1])
    # Больше шагов для дальних расстояний
    steps = int(random.uniform(8, 18) + dist / 40)
    steps = max(steps, 5)

    c1, c2 = _random_control_points(start, end)

    # Случайное «ускорение»: ease-in, ease-out, или равномерно
    profile = random.choice(["ease_in_out", "ease_in", "ease_out", "linear"])

    points = []
    for i in range(steps + 1):
        raw_t = i / steps
        if profile == "ease_in_out":
            t = raw_t * raw_t * (3 - 2 * raw_t)
        elif profile == "ease_in":
            t = raw_t ** 2
        elif profile == "ease_out":
            t = 1 - (1 - raw_t) ** 2
        else:
            t = raw_t
        points.append(_cubic_bezier(start, c1, c2, end, t))

    return points


# ─── Экранные координаты ─────────────────────────────────────────────────────

def _viewport_to_screen(driver: WebDriver, vp_x: float, vp_y: float) -> Tuple[int, int]:
    """
    Конвертирует координаты внутри viewport браузера → координаты экрана ОС.
    Учитывает позицию окна Chrome, высоту заголовка и адресной строки.
    """
    try:
        meta = driver.execute_script("""
            return {
                screenX: window.screenX,
                screenY: window.screenY,
                outerWidth: window.outerWidth,
                outerHeight: window.outerHeight,
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                dpr: window.devicePixelRatio || 1
            };
        """)
        chrome_x = meta["screenX"]
        chrome_y = meta["screenY"]
        # Высота заголовка + панели вкладок + адресной строки
        chrome_ui = meta["outerHeight"] - meta["innerHeight"]
        side_border = (meta["outerWidth"] - meta["innerWidth"]) // 2
        sx = int(chrome_x + side_border + vp_x)
        sy = int(chrome_y + chrome_ui + vp_y)
        return sx, sy
    except Exception:
        return int(vp_x), int(vp_y)


def _get_pos() -> Tuple[float, float]:
    if PYAUTOGUI_OK:
        x, y = pyautogui.position()
        return float(x), float(y)
    return 640.0, 400.0


# ─── Движение мыши ───────────────────────────────────────────────────────────

def _move_along_curve_screen(target_x: int, target_y: int) -> None:
    """
    Двигает РЕАЛЬНЫЙ ОС-курсор от текущей позиции к цели по кривой Безье.
    Видно как мышь плавно движется.
    """
    if not PYAUTOGUI_OK:
        return

    start = _get_pos()
    end = (float(target_x), float(target_y))

    if math.hypot(end[0] - start[0], end[1] - start[1]) < 2:
        return

    points = _bezier_steps(start, end)

    # Случайная скорость
    step_delay = random.uniform(0.006, 0.018)
    for (px, py) in points[1:]:
        try:
            pyautogui.moveTo(int(px), int(py), duration=0, _pause=False)
        except Exception:
            pass
        time.sleep(step_delay)


def _element_screen_center(driver: WebDriver, element: WebElement) -> Tuple[int, int]:
    """Возвращает экранные координаты центра элемента с лёгким случайным смещением."""
    rect = driver.execute_script("""
        const r = arguments[0].getBoundingClientRect();
        return {x: r.left, y: r.top, w: r.width, h: r.height};
    """, element)
    vx = rect["x"] + rect["w"] * random.uniform(0.3, 0.7)
    vy = rect["y"] + rect["h"] * random.uniform(0.3, 0.7)
    return _viewport_to_screen(driver, vx, vy)


def move_to_element(driver: WebDriver, element: WebElement) -> None:
    """Плавное движение РЕАЛЬНОГО курсора к элементу по кривой Безье."""
    try:
        sx, sy = _element_screen_center(driver, element)
        _move_along_curve_screen(sx, sy)
        micro_pause()
    except Exception:
        try:
            ActionChains(driver).move_to_element(element).perform()
        except Exception:
            pass


def click_element(driver: WebDriver, element: WebElement) -> None:
    """Движение к элементу → пауза → клик настоящим ОС-кликом."""
    move_to_element(driver, element)
    pause(0.15, 0.4)
    clicked = False
    if PYAUTOGUI_OK:
        try:
            pyautogui.click(_pause=False)
            clicked = True
        except Exception:
            pass
    if not clicked:
        try:
            element.click()
        except Exception:
            driver.execute_script("arguments[0].click();", element)
    micro_pause()
    # Иногда мышь чуть отводится после клика
    if random.random() < 0.4 and PYAUTOGUI_OK:
        try:
            x, y = pyautogui.position()
            dx = random.randint(-20, 20)
            dy = random.randint(-12, 12)
            pyautogui.moveTo(x + dx, y + dy, duration=0.15, _pause=False)
        except Exception:
            pass
    pause(0.2, 0.5)


# ─── Скролл ──────────────────────────────────────────────────────────────────

def scroll_to(driver: WebDriver, element: WebElement) -> None:
    """Плавный скролл к элементу."""
    driver.execute_script(
        "arguments[0].scrollIntoView({behavior:'smooth', block:'center'});",
        element,
    )
    pause(0.3, 0.8)


def random_scroll(driver: WebDriver) -> None:
    """Случайный скролл — имитация чтения списка."""
    amount = random.randint(80, 350)
    driver.execute_script(f"window.scrollBy({{top:{amount}, behavior:'smooth'}});")
    pause(0.4, 1.0)
    if random.random() < 0.35:
        back = random.randint(20, 90)
        driver.execute_script(f"window.scrollBy({{top:-{back}, behavior:'smooth'}});")
        pause(0.2, 0.5)
    # Иногда двигаем мышь в сторону — «осматриваемся»
    if random.random() < 0.3 and PYAUTOGUI_OK:
        try:
            x, y = pyautogui.position()
            dx = random.randint(-100, 100)
            dy = random.randint(-60, 60)
            pyautogui.moveTo(x + dx, y + dy, duration=random.uniform(0.2, 0.5), _pause=False)
        except Exception:
            pass


# ─── Ввод текста ─────────────────────────────────────────────────────────────

def type_text(element: WebElement, text: str) -> None:
    """Ввод текста с рандомными задержками между символами."""
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(0.04, 0.16))
        # Иногда — более длинная пауза («задумался»)
        if random.random() < 0.08:
            time.sleep(random.uniform(0.3, 0.7))


# ─── Idle-движения (между действиями) ────────────────────────────────────────

def idle_move(driver: WebDriver) -> None:
    """
    Случайное движение РЕАЛЬНОГО курсора «на холостом ходу» — пока бот ждёт.
    """
    if not PYAUTOGUI_OK:
        return
    try:
        x, y = pyautogui.position()
        sw, sh = pyautogui.size()
        dx = random.randint(-150, 150)
        dy = random.randint(-100, 100)
        nx = max(50, min(sw - 50, x + dx))
        ny = max(50, min(sh - 50, y + dy))
        _move_along_curve_screen(nx, ny)
    except Exception:
        pass
