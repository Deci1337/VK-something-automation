"""Детекция и обработка капчи VK."""
import time
import logging
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import human

log = logging.getLogger("captcha")


def check_and_solve(driver: WebDriver, selectors: dict, timeout: float = 3.0) -> bool:
    """
    Проверяет наличие капчи и пробует её решить (простой чекбокс VK).
    Возвращает True если капча была и решена, False если капчи не было.
    """
    try:
        # Ищем iframe с капчей
        iframes = driver.find_elements(By.XPATH, selectors.get("captcha_iframe", "//iframe"))
        for iframe in iframes:
            src = iframe.get_attribute("src") or ""
            if "vk.com" not in src and "vkcaptcha" not in src.lower():
                continue
            log.info("Обнаружена капча-iframe, пробую решить чекбокс...")
            try:
                driver.switch_to.frame(iframe)
                human.pause(0.8, 1.5)
                css = selectors.get("captcha_checkbox", ".vkc__Checkbox-module__Checkbox")
                wait = WebDriverWait(driver, 5)
                checkbox = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, css)))
                human.move_to_element(driver, checkbox)
                human.pause(0.3, 0.7)
                checkbox.click()
                human.pause(1.0, 2.0)
                driver.switch_to.default_content()
                log.info("Капча кликнута успешно")
                return True
            except Exception as e:
                log.warning(f"Не удалось решить капчу: {e}")
                driver.switch_to.default_content()

        # Проверяем капчу на самой странице (не iframe)
        page_caps = driver.find_elements(By.CSS_SELECTOR, selectors.get("captcha_checkbox", ".vkc__Checkbox-module__Checkbox"))
        if page_caps:
            log.info("Обнаружена капча на странице, решаю...")
            human.move_to_element(driver, page_caps[0])
            human.pause(0.4, 0.9)
            page_caps[0].click()
            human.pause(1.0, 2.0)
            return True

    except Exception as e:
        log.debug(f"captcha check error: {e}")

    return False


def wait_for_captcha_pass(driver: WebDriver, selectors: dict, max_attempts: int = 5) -> bool:
    """
    Пытается решить капчу несколько раз.
    Если не получилось — возвращает False (бот должен сделать паузу).
    """
    for attempt in range(max_attempts):
        solved = check_and_solve(driver, selectors)
        if not solved:
            return True  # Капчи нет — продолжаем
        # Капча была, подождём и проверим снова
        time.sleep(2.5)
        still_there = check_and_solve(driver, selectors)
        if not still_there:
            return True
        log.warning(f"Капча всё ещё есть, попытка {attempt + 1}/{max_attempts}")
        time.sleep(3.0)

    log.error("Капча не решена за все попытки")
    return False
