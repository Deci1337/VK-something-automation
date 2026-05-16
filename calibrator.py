"""
Координатная калибровка.

Пользователь выделяет на экране области (кнопки), программа сохраняет их
центральные точки и кликает по ним по порядку.

Файл сохранений: presets.json  — список именованных пресетов.
Текущий активный: areas.json   — массив областей в порядке кликов.
"""
import json
import os
import tkinter as tk
from typing import Callable, List, Dict, Optional

import customtkinter as ctk

try:
    import keyboard
    HAS_KEYBOARD = True
except Exception:
    HAS_KEYBOARD = False

DIR = os.path.dirname(__file__)
AREAS_PATH = os.path.join(DIR, "areas.json")
PRESETS_PATH = os.path.join(DIR, "presets.json")


# ─── Хранилище ───────────────────────────────────────────────────────────────

def load_areas() -> List[Dict]:
    if os.path.exists(AREAS_PATH):
        try:
            with open(AREAS_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("areas", [])
        except Exception:
            return []
    return []


def save_areas(areas: List[Dict]) -> None:
    with open(AREAS_PATH, "w", encoding="utf-8") as f:
        json.dump({"areas": areas}, f, ensure_ascii=False, indent=2)


def load_presets() -> Dict[str, List[Dict]]:
    if os.path.exists(PRESETS_PATH):
        try:
            with open(PRESETS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_presets(presets: Dict[str, List[Dict]]) -> None:
    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)


# ─── Overlay для выделения прямоугольника ────────────────────────────────────

class AreaSelector:
    """Полноэкранный полупрозрачный overlay — пользователь выделяет прямоугольник."""

    def __init__(self, on_done: Callable[[Optional[Dict]], None]):
        self.on_done = on_done
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.35)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#1f2937")
        self.root.update_idletasks()
        try:
            import pyautogui as _pag
            sw, sh = _pag.size()
        except Exception:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")
        self.root.update_idletasks()

        self.canvas = tk.Canvas(self.root, cursor="cross",
                                bg="#1f2937", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.create_text(sw // 2, 40,
                                text="Выделите кнопку прямоугольником.  ESC — отмена.",
                                fill="white", font=("Segoe UI", 18, "bold"))

        self.start_x = 0
        self.start_y = 0
        self.rect = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", self._cancel)

    def _on_press(self, ev):
        self.start_x, self.start_y = ev.x, ev.y
        self.rect = self.canvas.create_rectangle(
            ev.x, ev.y, ev.x, ev.y,
            outline="#ef4444", width=3, fill="#fca5a5", stipple="gray25"
        )

    def _on_drag(self, ev):
        if self.rect:
            self.canvas.coords(self.rect, self.start_x, self.start_y, ev.x, ev.y)

    def _on_release(self, ev):
        x1, y1 = min(self.start_x, ev.x), min(self.start_y, ev.y)
        x2, y2 = max(self.start_x, ev.x), max(self.start_y, ev.y)
        # игнор очень маленьких выделений
        if (x2 - x1) < 4 or (y2 - y1) < 4:
            self._cancel()
            return
        self.root.destroy()
        self.on_done({
            "x": x1, "y": y1,
            "w": x2 - x1, "h": y2 - y1,
            "cx": (x1 + x2) // 2,
            "cy": (y1 + y2) // 2,
        })

    def _cancel(self, *_):
        self.root.destroy()
        self.on_done(None)


# ─── Overlay для калибровки шага прокрутки ───────────────────────────────────

class StepSelector:
    """Два клика: первый — центр 1-го участника, второй — центр 2-го.
    Разница по Y = шаг прокрутки на одного участника.
    """

    def __init__(self, on_done: Callable[[Optional[Dict]], None]):
        self.on_done = on_done
        self._y1: Optional[int] = None
        self._x1: Optional[int] = None
        self._phase = 1
        self._open_overlay("Кликните на центр ПЕРВОГО участника.  ESC — отмена.")

    def _open_overlay(self, prompt: str):
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.4)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0f172a")
        self.root.update_idletasks()
        try:
            import pyautogui as _pag
            sw, sh = _pag.size()
        except Exception:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        self._sw, self._sh = sw, sh
        self.root.geometry(f"{sw}x{sh}+0+0")
        self.root.update_idletasks()

        self.canvas = tk.Canvas(self.root, cursor="crosshair",
                                bg="#0f172a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_text(sw // 2, 40, text=prompt,
                                fill="#facc15", font=("Segoe UI", 18, "bold"))
        if self._y1 is not None:
            self.canvas.create_oval(
                self._x1 - 8, self._y1 - 8, self._x1 + 8, self._y1 + 8,
                fill="#f97316", outline="#fff", width=2,
            )
            self.canvas.create_line(
                self._x1, self._y1, sw // 2, self._y1,
                fill="#f97316", width=1, dash=(4, 4),
            )
        self.canvas.bind("<ButtonRelease-1>", self._on_click)
        self.root.bind("<Escape>", self._cancel)

    def _on_click(self, ev):
        if self._phase == 1:
            self._x1, self._y1 = ev.x, ev.y
            self._phase = 2
            self.root.destroy()
            self._open_overlay(
                f"Кликните на центр ВТОРОГО участника.  (Y₁={self._y1})  ESC — отмена."
            )
        else:
            dy = ev.y - self._y1
            self.root.destroy()
            self.on_done({
                "type": "step",
                "y1": self._y1, "y2": ev.y,
                "dy": dy,
                "cx": ev.x, "cy": ev.y,
                "w": 1, "h": 1,
            })

    def _cancel(self, *_):
        self.root.destroy()
        self.on_done(None)


# ─── Overlay для рисования стрелки прокрутки ─────────────────────────────────

class ArrowSelector:
    """Полноэкранный overlay — пользователь рисует стрелку от участника к следующему."""

    def __init__(self, on_done: Callable[[Optional[Dict]], None]):
        self.on_done = on_done
        self.root = tk.Toplevel()
        self.root.overrideredirect(True)
        self.root.attributes("-alpha", 0.4)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#0f172a")
        self.root.update_idletasks()
        try:
            import pyautogui as _pag
            sw, sh = _pag.size()
        except Exception:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")
        self.root.update_idletasks()

        self.canvas = tk.Canvas(self.root, cursor="cross",
                                bg="#0f172a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.create_text(sw // 2, 40,
                                text="Нарисуйте стрелку: от текущего участника → к следующему.  ESC — отмена.",
                                fill="#60a5fa", font=("Segoe UI", 18, "bold"))

        self.start_x = 0
        self.start_y = 0
        self.line = None
        self.dot = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", self._cancel)

    def _on_press(self, ev):
        self.start_x, self.start_y = ev.x, ev.y
        self.dot = self.canvas.create_oval(
            ev.x - 6, ev.y - 6, ev.x + 6, ev.y + 6,
            fill="#f97316", outline="#fff", width=2,
        )
        self.line = self.canvas.create_line(
            ev.x, ev.y, ev.x, ev.y,
            fill="#60a5fa", width=4, arrow=tk.LAST, arrowshape=(16, 20, 6),
        )

    def _on_drag(self, ev):
        if self.line:
            self.canvas.coords(self.line, self.start_x, self.start_y, ev.x, ev.y)

    def _on_release(self, ev):
        dx = ev.x - self.start_x
        dy = ev.y - self.start_y
        if abs(dx) < 4 and abs(dy) < 4:
            self._cancel()
            return
        self.root.destroy()
        self.on_done({
            "type": "scroll",
            "x1": self.start_x, "y1": self.start_y,
            "x2": ev.x, "y2": ev.y,
            "cx": self.start_x, "cy": self.start_y,
            "w": 1, "h": 1,
        })

    def _cancel(self, *_):
        self.root.destroy()
        self.on_done(None)


# ─── Плавающий тулбар ────────────────────────────────────────────────────────

class CalibrationToolbar(ctk.CTkToplevel):
    """Маленькое окно поверх всех с 3 кнопками: добавить / удалить / сохранить."""

    def __init__(self, parent_app, on_close: Callable[[List[Dict]], None]):
        super().__init__(parent_app)
        self.parent_app = parent_app
        self.on_close = on_close
        self.areas: List[Dict] = list(load_areas())

        self.title("Калибровка")
        self.attributes("-topmost", True)
        sh = self.winfo_screenheight()
        sw = self.winfo_screenwidth()
        self.geometry(f"{sw}x160+0+{sh - 170}")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_finish)

        self.configure(fg_color="#FFFFFF")

        title = ctk.CTkLabel(
            self, text="🎯  Калибровка по координатам",
            font=("Segoe UI", 14, "bold"), text_color="#0F172A",
        )
        title.pack(anchor="w", padx=14, pady=(10, 2))

        self._hotkey_registered = False
        if HAS_KEYBOARD:
            try:
                keyboard.add_hotkey("7", self._hotkey_add)
                self._hotkey_registered = True
            except Exception:
                pass

        self.lbl_count = ctk.CTkLabel(
            self, text=self._count_text(),
            font=("Segoe UI", 11), text_color="#64748B",
        )
        self.lbl_count.pack(anchor="w", padx=14)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=10)

        ctk.CTkButton(
            btn_row, text="➕  Добавить клик", command=self._add,
            fg_color="#2563EB", hover_color="#1D4ED8", height=38, corner_radius=8,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", fill="x", expand=True, padx=(0, 5))

        ctk.CTkButton(
            btn_row, text="↩  Удалить последнюю", command=self._remove_last,
            fg_color="#E2E8F5", hover_color="#FEE2E2",
            text_color="#0F172A", height=38, corner_radius=8,
            font=("Segoe UI", 11),
        ).pack(side="left", fill="x", expand=True, padx=5)

        ctk.CTkButton(
            btn_row, text="📏  Шаг прокрутки", command=self._add_step,
            fg_color="#7C3AED", hover_color="#6D28D9", text_color="#fff",
            height=38, corner_radius=8, font=("Segoe UI", 11),
        ).pack(side="left", fill="x", expand=True, padx=5)

        ctk.CTkButton(
            btn_row, text="✅  Применить", command=self._on_finish,
            fg_color="#059669", hover_color="#047857", height=38, corner_radius=8,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", fill="x", expand=True, padx=(5, 0))

    def _count_text(self) -> str:
        hint = "  ⌨ клавиша 7 = добавить" if HAS_KEYBOARD else ""
        clicks = [a for a in self.areas if a.get("type", "click") == "click"]
        steps = [a for a in self.areas if a.get("type") == "step"]
        step_info = f"  📏 шаг={steps[0]['dy']}px" if steps else "  📏 шаг не задан"
        if not clicks:
            return f"Областей пока нет. Нажмите «Добавить клик» или клавишу 7.{hint}{step_info}"
        names = ", ".join(f"#{i+1}" for i in range(len(clicks)))
        return f"Сохранено областей: {len(clicks)}  ({names}){hint}{step_info}"

    def _hotkey_add(self):
        try:
            self.after(0, self._add)
        except Exception:
            pass

    def _hotkey_scroll(self):
        try:
            self.after(0, self._add_scroll)
        except Exception:
            pass

    def _update(self):
        self.lbl_count.configure(text=self._count_text())

    def _add(self):
        if getattr(self, "_selecting", False):
            return
        self._selecting = True
        self.iconify()
        self.parent_app.iconify()

        def _done(area):
            self._selecting = False
            if area:
                area["order"] = len(self.areas) + 1
                self.areas.append(area)
                self._update()

        self.after(150, lambda: AreaSelector(_done))

    def _add_copy_link(self):
        """Добавляет шаг захвата ID: правый клик → Copy link address → проверка дублей."""
        if getattr(self, "_selecting", False):
            return
        self._selecting = True
        self.iconify()
        self.parent_app.iconify()

        def _done(area):
            self._selecting = False
            if area:
                area["type"] = "copy_link"
                area["order"] = len(self.areas) + 1
                self.areas.append(area)
                self._update()

        self.after(150, lambda: AreaSelector(_done))

    def _add_scroll(self):
        if getattr(self, "_selecting", False):
            return
        self._selecting = True
        self.iconify()
        self.parent_app.iconify()

        def _done(area):
            self._selecting = False
            if area:
                area["order"] = len(self.areas) + 1
                self.areas.append(area)
                self._update()

        self.after(150, lambda: ArrowSelector(_done))

    def _add_step(self):
        if getattr(self, "_selecting", False):
            return
        self._selecting = True
        self.iconify()
        self.parent_app.iconify()

        def _done(area):
            self._selecting = False
            if area:
                # Заменяем предыдущий step (если был)
                self.areas = [a for a in self.areas if a.get("type") != "step"]
                self.areas.append(area)
                self._update()

        self.after(150, lambda: StepSelector(_done))

    def _remove_last(self):
        if self.areas:
            self.areas.pop()
            self._update()

    def _on_finish(self):
        if self._hotkey_registered and HAS_KEYBOARD:
            try:
                keyboard.remove_hotkey("7")
            except Exception:
                pass
        save_areas(self.areas)
        self.destroy()
        self.on_close(self.areas)
