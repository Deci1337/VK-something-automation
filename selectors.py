"""
VK CSS-селекторы. Когда VK обновляет интерфейс — меняй значения здесь.
Редактировать можно прямо в GUI (вкладка "Калибровка").
"""
import json
import os

SEL_PATH = os.path.join(os.path.dirname(__file__), "selectors.json")

DEFAULTS = {
    # Строка участника на странице /settings/subscribers
    "member_row": "div[data-testid*='settings-subscriber-item'],div.vkuiRichCell__host",
    # Кнопка "..." (три точки) справа у участника
    "member_more_btn": "button.vkuiIconButton",
    # Пункт контекстного меню "Назначить руководителем"
    "make_admin_item": "//span[contains(text(),'Назначить руководителем')]",
    # Кнопка подтверждения назначения в диалоге
    "admin_confirm_btn": "//button[contains(@class,'vkuiButton') and contains(.,'Назначить')]",
    # Пункт контекстного меню "Убрать из руководителей"
    "remove_admin_item": "//span[contains(text(),'Убрать из руководителей') or contains(text(),'Снять с должности')]",
    # Кнопка подтверждения снятия в диалоге
    "remove_confirm_btn": "//button[contains(@class,'vkuiButton') and (contains(.,'Снять') or contains(.,'Подтвердить') or contains(.,'Убрать'))]",
    # Капча
    "captcha_iframe": "//iframe[contains(@src,'vk.com')]",
    "captcha_checkbox": ".vkc__Checkbox-module__Checkbox",
    # Ссылка на профиль участника (для получения ID)
    "member_link": "a[data-testid*='settings-subscriber-link'],a.vkuiAvatar__host,a[href*='/id']",
    # Не используется, оставлено для совместимости
    "role_select": "",
}

LABELS = {
    "member_row": "Строка участника",
    "member_more_btn": "Кнопка '...' (три точки)",
    "make_admin_item": "Пункт 'Назначить руководителем' (XPath)",
    "admin_confirm_btn": "Кнопка подтверждения назначения (XPath)",
    "remove_admin_item": "Пункт 'Снять с должности' (XPath)",
    "remove_confirm_btn": "Кнопка подтверждения снятия (XPath)",
    "captcha_iframe": "Iframe капчи (XPath)",
    "captcha_checkbox": "Чекбокс капчи (CSS)",
    "member_link": "Ссылка аватара участника (CSS)",
    "role_select": "Поле роли в диалоге (необязательно)",
}


def load() -> dict:
    if os.path.exists(SEL_PATH):
        with open(SEL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULTS, **data}
    return dict(DEFAULTS)


def save(sel: dict) -> None:
    with open(SEL_PATH, "w", encoding="utf-8") as f:
        json.dump(sel, f, ensure_ascii=False, indent=2)
