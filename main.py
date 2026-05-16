"""
VK Admin Notifier
pip install customtkinter undetected-chromedriver selenium
"""
import logging
import os
import threading
from tkinter import filedialog

import customtkinter as ctk

import config as cfg_module
import selectors as sel_module
import storage
import calibrator
from scroll_panel import ScrollPanel

try:
    import keyboard as _keyboard_lib
    HAS_KEYBOARD = True
except Exception:
    HAS_KEYBOARD = False

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ── Палитра ──────────────────────────────────────────────────────────────────
C = {
    "bg":       "#F5F7FF",
    "white":    "#FFFFFF",
    "blue":     "#2563EB",
    "blue_h":   "#1D4ED8",
    "blue_lt":  "#EFF6FF",
    "blue_mid": "#DBEAFE",
    "border":   "#E2E8F5",
    "text":     "#0F172A",
    "muted":    "#64748B",
    "green":    "#059669",
    "green_lt": "#D1FAE5",
    "red":      "#DC2626",
    "red_lt":   "#FEE2E2",
    "yellow":   "#D97706",
    "yellow_lt":"#FEF3C7",
}

FH1  = ("Segoe UI", 20, "bold")
FH2  = ("Segoe UI", 15, "bold")
FB   = ("Segoe UI", 13)
FSM  = ("Segoe UI", 11)
FMONO= ("Consolas", 12)

logging.basicConfig(level=logging.INFO)


# ─── Хелперы ─────────────────────────────────────────────────────────────────

def card(parent, **kw) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color=C["white"], corner_radius=12,
                        border_width=1, border_color=C["border"], **kw)


def label(parent, text, font=FB, color=None, **kw) -> ctk.CTkLabel:
    return ctk.CTkLabel(parent, text=text, font=font,
                        text_color=color or C["text"], **kw)


def entry(parent, placeholder="", width=None, **kw) -> ctk.CTkEntry:
    return ctk.CTkEntry(
        parent,
        font=FB, height=40,
        fg_color=C["white"],
        border_color=C["border"],
        border_width=1,
        text_color=C["text"],
        placeholder_text=placeholder,
        placeholder_text_color=C["muted"],
        **({"width": width} if width else {}),
        **kw,
    )


def btn_primary(parent, text, cmd, height=40, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(parent, text=text, command=cmd, height=height,
                         font=(FB[0], FB[1], "bold"),
                         fg_color=C["blue"], hover_color=C["blue_h"],
                         text_color="#fff", corner_radius=8, **kw)


def btn_ghost(parent, text, cmd, height=36, **kw) -> ctk.CTkButton:
    return ctk.CTkButton(parent, text=text, command=cmd, height=height,
                         font=FSM, fg_color=C["white"],
                         hover_color=C["blue_lt"], text_color=C["blue"],
                         border_width=1, border_color=C["border"],
                         corner_radius=8, **kw)


def info_box(parent, text, color=None, text_color=None) -> ctk.CTkFrame:
    f = ctk.CTkFrame(parent, fg_color=color or C["blue_lt"],
                     corner_radius=8, border_width=0)
    f.pack(fill="x", pady=(0, 12))
    ctk.CTkLabel(f, text=text, font=FSM,
                 text_color=text_color or C["blue"],
                 justify="left", wraplength=560).pack(
        anchor="w", padx=14, pady=10)
    return f


# ─── Главное окно ─────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("VK Admin Notifier")
        self.geometry("980x700")
        self.minsize(860, 600)
        self.configure(fg_color=C["bg"])

        self.cfg = cfg_module.load()
        self.bot = None
        self._running = False
        self._session_done = 0
        self._scroll_panel: ScrollPanel | None = None

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Каркас ───────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=C["blue"], corner_radius=0, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        label(hdr, "VK Admin Notifier", FH1, "#fff").pack(side="left", padx=22, pady=10)
        self._dot = ctk.CTkLabel(hdr, text="⬤  Остановлен",
                                 font=FSM, text_color="#93C5FD")
        self._dot.pack(side="right", padx=22)

        # Sidebar + content
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # Sidebar
        self._sidebar = ctk.CTkFrame(body, fg_color=C["white"],
                                     corner_radius=0, width=176,
                                     border_width=1, border_color=C["border"])
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        # Content area
        self._content = ctk.CTkFrame(body, fg_color="transparent")
        self._content.pack(side="left", fill="both", expand=True, padx=16, pady=14)

        # Страницы
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._nav_btns: dict[str, ctk.CTkButton] = {}

        pages = [
            ("▶   Запуск",       self._page_run),
            ("⚙   Настройки",    self._page_settings),
            ("🔧  Калибровка",   self._page_calibration),
            ("📖  Инструкция",   self._page_guide),
            ("📋  История",      self._page_history),
        ]

        ctk.CTkFrame(self._sidebar, fg_color="transparent", height=12).pack()
        for name, builder in pages:
            pg = ctk.CTkFrame(self._content, fg_color="transparent")
            builder(pg)
            self._pages[name] = pg

            nb = ctk.CTkButton(
                self._sidebar, text=name, anchor="w",
                font=FSM, height=38, corner_radius=6,
                fg_color="transparent", hover_color=C["blue_lt"],
                text_color=C["muted"],
                command=lambda n=name: self._show(n),
            )
            nb.pack(fill="x", padx=8, pady=2)
            self._nav_btns[name] = nb

        self._show("▶   Запуск")

    def _show(self, name: str):
        for n, pg in self._pages.items():
            pg.pack_forget()
        for n, nb in self._nav_btns.items():
            nb.configure(fg_color=C["blue_lt"] if n == name else "transparent",
                         text_color=C["blue"] if n == name else C["muted"],
                         font=(FSM[0], FSM[1], "bold") if n == name else FSM)
        self._pages[name].pack(fill="both", expand=True)

    # ── Страница «Запуск» ─────────────────────────────────────────────────────

    def _page_run(self, pg):
        pg.configure(fg_color="transparent")

        # Две колонки
        left = ctk.CTkFrame(pg, fg_color="transparent", width=340)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)

        right = card(pg)
        right.pack(side="left", fill="both", expand=True)

        # ── Левая: настройки запуска
        c1 = card(left)
        c1.pack(fill="x", pady=(0, 10))

        label(c1, "Ссылка на группу", FSM, C["muted"]).pack(anchor="w", padx=16, pady=(14, 3))
        gr = ctk.CTkFrame(c1, fg_color="transparent")
        gr.pack(fill="x", padx=16)
        self._inp_group = entry(gr, "https://vk.com/mygroup")
        self._inp_group.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(gr, text="📋", width=40, height=40, corner_radius=8,
                      fg_color=C["border"], hover_color=C["blue_lt"],
                      text_color=C["text"], font=FB,
                      command=lambda: self._paste_into(self._inp_group)
                      ).pack(side="left", padx=(6, 0))
        self._inp_group.insert(0, self.cfg.get("group_url", ""))

        label(c1, "Папка профиля Chrome", FSM, C["muted"]).pack(anchor="w", padx=16, pady=(12, 3))
        pr = ctk.CTkFrame(c1, fg_color="transparent")
        pr.pack(fill="x", padx=16)
        self._inp_profile = entry(pr, "Путь к профилю Chrome")
        self._inp_profile.pack(side="left", fill="x", expand=True)
        self._inp_profile.insert(0, self.cfg.get("profile_path", ""))
        ctk.CTkButton(pr, text="📋", width=40, height=40, corner_radius=8,
                      fg_color=C["border"], hover_color=C["blue_lt"],
                      text_color=C["text"], font=FB,
                      command=lambda: self._paste_into(self._inp_profile)
                      ).pack(side="left", padx=(6, 0))
        ctk.CTkButton(pr, text="…", width=40, height=40, corner_radius=8,
                      fg_color=C["border"], hover_color=C["blue_lt"],
                      text_color=C["text"], font=FB,
                      command=self._pick_profile).pack(side="left", padx=(6, 0))

        default_prof = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "VKAdminBot", "chrome-profile")
        btn_ghost(c1, "⬆  Использовать профиль бота (по умолчанию)", height=32,
                  cmd=lambda: (self._inp_profile.delete(0, "end"),
                               self._inp_profile.insert(0, default_prof))
                  ).pack(anchor="w", padx=16, pady=(6, 0))

        # Лимит
        lim_row = ctk.CTkFrame(c1, fg_color="transparent")
        lim_row.pack(fill="x", padx=16, pady=(14, 4))
        self._var_limit = ctk.BooleanVar(value=self.cfg.get("use_limit", False))
        ctk.CTkCheckBox(lim_row, text="Ограничить количеством",
                        variable=self._var_limit,
                        font=FSM, text_color=C["text"],
                        fg_color=C["blue"], hover_color=C["blue_h"],
                        checkmark_color="#fff",
                        command=self._toggle_limit).pack(side="left")
        self._inp_count = entry(c1, "Например: 50", width=140)
        self._inp_count.pack(anchor="w", padx=16, pady=(0, 6))
        self._inp_count.insert(0, str(self.cfg.get("count", 50)))
        self._toggle_limit()

        label(c1, "Без галочки — обработает всех новых участников",
              FSM, C["muted"]).pack(anchor="w", padx=16, pady=(0, 14))

        # ── Кнопки старт/стоп
        c2 = card(left)
        c2.pack(fill="x", pady=(0, 10))

        br = ctk.CTkFrame(c2, fg_color="transparent")
        br.pack(fill="x", padx=16, pady=14)
        self._btn_start = btn_primary(br, "▶  СТАРТ", self._on_start, height=44)
        self._btn_start.pack(side="left", fill="x", expand=True)
        self._btn_stop = ctk.CTkButton(br, text="⏹ Стоп", height=44, width=90,
                                       font=FB, corner_radius=8,
                                       fg_color=C["border"], hover_color=C["red_lt"],
                                       text_color=C["muted"], state="disabled",
                                       command=self._on_stop)
        self._btn_stop.pack(side="left", padx=(8, 0))

        hint_row = ctk.CTkFrame(c2, fg_color="transparent")
        hint_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(hint_row,
                     text="⌨ Клавиша F8 = экстренная остановка во время работы",
                     font=FSM, text_color=C["muted"]).pack(side="left")

        # ── Статистика
        c3 = card(left)
        c3.pack(fill="x")

        sr = ctk.CTkFrame(c3, fg_color="transparent")
        sr.pack(fill="x", padx=16, pady=12)

        stat_box = ctk.CTkFrame(sr, fg_color=C["blue_lt"], corner_radius=8)
        stat_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        label(stat_box, "Всего обработано", FSM, C["muted"]).pack(pady=(8, 0))
        self._lbl_total = ctk.CTkLabel(stat_box, text=str(storage.get_count()),
                                       font=("Segoe UI", 26, "bold"),
                                       text_color=C["blue"])
        self._lbl_total.pack(pady=(0, 8))

        ses_box = ctk.CTkFrame(sr, fg_color=C["green_lt"], corner_radius=8)
        ses_box.pack(side="left", fill="both", expand=True)
        label(ses_box, "В этой сессии", FSM, C["muted"]).pack(pady=(8, 0))
        self._lbl_session = ctk.CTkLabel(ses_box, text="0",
                                         font=("Segoe UI", 26, "bold"),
                                         text_color=C["green"])
        self._lbl_session.pack(pady=(0, 8))

        self._progress = ctk.CTkProgressBar(c3, height=6, corner_radius=3,
                                            fg_color=C["border"],
                                            progress_color=C["blue"])
        self._progress.set(0)
        self._progress.pack(fill="x", padx=16, pady=(0, 14))

        # ── Правая: лог
        label(right, "Журнал действий", FH2).pack(anchor="w", padx=18, pady=(14, 6))
        ctk.CTkFrame(right, fg_color=C["border"], height=1).pack(fill="x", padx=18)
        self._log_box = ctk.CTkTextbox(right, font=FMONO,
                                       fg_color=C["bg"],
                                       text_color=C["text"],
                                       corner_radius=8,
                                       wrap="word", state="disabled")
        self._log_box.pack(fill="both", expand=True, padx=14, pady=12)

    # ── Страница «Настройки» ─────────────────────────────────────────────────

    def _page_settings(self, pg):
        pg.configure(fg_color="transparent")
        c = card(pg)
        c.pack(fill="x")

        label(c, "Параметры работы", FH2).pack(anchor="w", padx=20, pady=(18, 4))
        ctk.CTkFrame(c, fg_color=C["border"], height=1).pack(fill="x", padx=20, pady=(0, 6))

        def row(lbl, attr, default, hint=""):
            label(c, lbl, FSM, C["muted"]).pack(anchor="w", padx=20, pady=(10, 2))
            if hint:
                label(c, hint, ("Segoe UI", 10), C["muted"]).pack(anchor="w", padx=20)
            e = entry(c)
            e.insert(0, str(self.cfg.get(attr, default)))
            e.pack(fill="x", padx=20, pady=(2, 0))
            return e

        self._s_delay_min = row("Минимальная пауза между участниками (сек)",
                                "delay_min", 8, "Рекомендуем не менее 8 сек")
        self._s_delay_max = row("Максимальная пауза (сек)", "delay_max", 20)
        self._s_hold      = row("Держать роль администратора (сек)",
                                "admin_hold_seconds", 15, "Рекомендуем 15–30 сек")

        btn_primary(c, "💾  Сохранить настройки",
                    self._save_settings, height=40
                    ).pack(anchor="w", padx=20, pady=20)

    # ── Страница «Калибровка» ────────────────────────────────────────────────

    def _page_calibration(self, pg):
        pg.configure(fg_color="transparent")

        sc = ctk.CTkScrollableFrame(pg, fg_color="transparent", corner_radius=0)
        sc.pack(fill="both", expand=True)

        # ── Главная карточка
        main_card = card(sc)
        main_card.pack(fill="x", pady=(0, 10))

        hdr = ctk.CTkFrame(main_card, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(16, 4))
        label(hdr, "🎯  Координатная калибровка", FH2).pack(side="left")
        ctk.CTkButton(hdr, text="⚙", width=36, height=36, corner_radius=8,
                      fg_color=C["border"], hover_color=C["blue_lt"],
                      text_color=C["text"], font=("Segoe UI", 16),
                      command=self._open_presets).pack(side="right")
        label(main_card,
              "Программа кликает по областям экрана, которые вы заранее выделите.\n"
              "Это полностью имитирует человека — никакого кода, чистая мышь.",
              FSM, C["muted"]).pack(anchor="w", padx=20, pady=(0, 12))

        # ── Инструкция
        instr = ctk.CTkFrame(main_card, fg_color=C["blue_lt"], corner_radius=8)
        instr.pack(fill="x", padx=20, pady=(0, 12))
        label(instr, "📖  Как настроить (один раз):",
              ("Segoe UI", 12, "bold"), C["blue"]).pack(anchor="w", padx=14, pady=(10, 4))
        label(instr,
              "1. Запустите Chrome через start-chrome.bat (важно — именно через него!)\n"
              "2. В этом Chrome войдите в VK и откройте vk.com/[группа]/settings/subscribers\n"
              "3. Прокрутите список так, чтобы у одного участника были видны: «...», аватарка, имя\n"
              "4. Нажмите ▶ Начать калибровку — выделите по порядку 6 кнопок:\n"
              "  ① «...» (три точки) у участника\n"
              "  ② Пункт меню «Назначить руководителем»\n"
              "  ③ Кнопка «Назначить» в диалоге подтверждения\n"
              "  ④ Снова «...» у того же участника\n"
              "  ⑤ Пункт «Убрать из руководителей»\n"
              "  ⑥ Кнопка «Убрать» / «Подтвердить» в диалоге\n\n"
              "5. ✅ Применить → СТАРТ.\n\n"
              "ℹ Прокрутка и проверка ID теперь автоматические — через Chrome DevTools.",
              FSM, C["text"], justify="left", wraplength=620
              ).pack(anchor="w", padx=14, pady=(0, 12))

        # ── Кнопки управления калибровкой
        actions = ctk.CTkFrame(main_card, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(0, 16))

        self._btn_start_cal = btn_primary(
            actions, "▶  Начать калибровку", self._on_start_calibration, height=44
        )
        self._btn_start_cal.pack(side="left", fill="x", expand=True)
        btn_ghost(actions, "🗑  Очистить", self._on_clear_calibration, height=44
                  ).pack(side="left", padx=(10, 0))
        btn_ghost(actions, "📜 Прокрутка", self._open_scroll_panel, height=44
                  ).pack(side="left", padx=(10, 0))

        # ── Превью сохранённых областей
        prev = card(sc)
        prev.pack(fill="x", pady=(0, 10))
        label(prev, "Сохранённые области", FH2).pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkFrame(prev, fg_color=C["border"], height=1).pack(fill="x", padx=20)
        self._areas_box = ctk.CTkTextbox(prev, height=160, font=FMONO,
                                         fg_color=C["bg"], text_color=C["text"],
                                         corner_radius=8, state="disabled")
        self._areas_box.pack(fill="x", padx=20, pady=(10, 16))
        self._refresh_areas_preview()

    def _refresh_areas_preview(self):
        areas = calibrator.load_areas()
        self._areas_box.configure(state="normal")
        self._areas_box.delete("1.0", "end")
        clicks = [a for a in areas if a.get("type", "click") == "click"]
        if not clicks:
            self._areas_box.insert("end", "Областей пока нет.\nНажмите «▶ Начать калибровку».")
        else:
            self._areas_box.insert("end", f"Всего областей: {len(clicks)}\n\n")
            for i, a in enumerate(clicks, 1):
                self._areas_box.insert(
                    "end",
                    f"#{i}  центр: ({a['cx']}, {a['cy']})   размер: {a['w']}×{a['h']}\n"
                )
        self._areas_box.configure(state="disabled")

    def _open_scroll_panel(self):
        """Открыть панель прокрутки в режиме калибровки."""
        if hasattr(self, "_calib_panel") and self._calib_panel and self._calib_panel.winfo_exists():
            self._calib_panel.lift()
            return
        self._calib_panel = ScrollPanel(self, mode="calibrate")

    def _on_start_calibration(self):
        def _on_close(areas):
            self._refresh_areas_preview()
            self._append_log(f"✅  Калибровка сохранена ({len(areas)} областей)")
        calibrator.CalibrationToolbar(self, on_close=_on_close)

    def _on_clear_calibration(self):
        calibrator.save_areas([])
        self._refresh_areas_preview()
        self._append_log("🗑  Калибровка очищена")

    def _open_presets(self):
        """Окно загрузки/сохранения пресетов."""
        win = ctk.CTkToplevel(self)
        win.title("Пресеты калибровки")
        win.geometry("420x420+120+120")
        win.attributes("-topmost", True)
        win.configure(fg_color=C["white"])

        label(win, "💾  Пресеты", FH2).pack(anchor="w", padx=16, pady=(14, 4))
        label(win, "Сохраняйте разные конфигурации (например, для разных групп)",
              FSM, C["muted"]).pack(anchor="w", padx=16, pady=(0, 10))

        # Поле имени + сохранить
        save_row = ctk.CTkFrame(win, fg_color="transparent")
        save_row.pack(fill="x", padx=16, pady=(0, 10))
        name_inp = entry(save_row, "Название пресета")
        name_inp.pack(side="left", fill="x", expand=True)

        def _do_save():
            n = name_inp.get().strip()
            if not n:
                return
            presets = calibrator.load_presets()
            presets[n] = calibrator.load_areas()
            calibrator.save_presets(presets)
            name_inp.delete(0, "end")
            _refresh()
            self._append_log(f"💾  Пресет «{n}» сохранён")

        ctk.CTkButton(save_row, text="💾", width=44, height=40, corner_radius=8,
                      fg_color=C["blue"], hover_color=C["blue_h"],
                      text_color="#fff", command=_do_save
                      ).pack(side="left", padx=(6, 0))

        # Список
        list_frame = ctk.CTkScrollableFrame(win, fg_color=C["bg"], corner_radius=8)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        def _refresh():
            for w in list_frame.winfo_children():
                w.destroy()
            presets = calibrator.load_presets()
            if not presets:
                label(list_frame, "Нет сохранённых пресетов",
                      FSM, C["muted"]).pack(anchor="w", padx=10, pady=10)
                return
            for n, areas in presets.items():
                row = ctk.CTkFrame(list_frame, fg_color=C["white"], corner_radius=6)
                row.pack(fill="x", pady=4, padx=4)
                label(row, f"{n}  ({len(areas)} обл.)", FSM, C["text"]
                      ).pack(side="left", padx=10, pady=8)

                def _load(name=n):
                    p = calibrator.load_presets()
                    calibrator.save_areas(p.get(name, []))
                    self._refresh_areas_preview()
                    self._append_log(f"✅  Загружен пресет «{name}»")
                    win.destroy()

                def _del(name=n):
                    p = calibrator.load_presets()
                    p.pop(name, None)
                    calibrator.save_presets(p)
                    _refresh()

                ctk.CTkButton(row, text="🗑", width=32, height=28, corner_radius=6,
                              fg_color=C["red_lt"], hover_color=C["red"],
                              text_color=C["red"], command=_del
                              ).pack(side="right", padx=(0, 6), pady=6)
                ctk.CTkButton(row, text="Загрузить", width=80, height=28,
                              corner_radius=6, fg_color=C["blue"],
                              hover_color=C["blue_h"], text_color="#fff",
                              font=FSM, command=_load
                              ).pack(side="right", padx=(0, 6), pady=6)

        _refresh()

    # ── Страница «Инструкция» ────────────────────────────────────────────────

    def _page_guide(self, pg):
        pg.configure(fg_color="transparent")
        sc = ctk.CTkScrollableFrame(pg, fg_color="transparent", corner_radius=0)
        sc.pack(fill="both", expand=True)

        def block(title, bg=None, title_color=None, body_text=""):
            f = ctk.CTkFrame(sc, fg_color=bg or C["white"], corner_radius=10,
                             border_width=1, border_color=C["border"])
            f.pack(fill="x", pady=(0, 10))
            label(f, title, FH2, title_color or C["blue"]
                  ).pack(anchor="w", padx=18, pady=(14, 6))
            ctk.CTkFrame(f, fg_color=C["border"], height=1
                         ).pack(fill="x", padx=18, pady=(0, 6))
            label(f, body_text, FSM, C["text"], justify="left", wraplength=620
                  ).pack(anchor="w", padx=18, pady=(0, 14))

        block("📌  Что делает программа", C["green_lt"], C["green"],
              body_text=(
                  "Программа заходит в вашу группу ВКонтакте, берёт новых участников и каждому:\n"
                  "  1. Назначает администратором\n"
                  "  2. Ждёт 15 секунд\n"
                  "  3. Снимает с должности\n\n"
                  "Человек получает уведомление от VK: «Вас назначили администратором в группе X»\n"
                  "Это легальный способ о себе напомнить. Повторно одни и те же люди не обрабатываются."
              ))

        block("1️⃣   Установка и первый запуск",
              body_text=(
                  "1. Установите Python 3.10+ если ещё не установлен  →  python.org\n\n"
                  "2. Дважды кликните на  install.bat  — подождите установки\n\n"
                  "3. Запускайте через  run.bat  (или  python main.py)"
              ))

        block("2️⃣   Настройка профиля Chrome",
              body_text=(
                  "Программа использует СВОЙ изолированный Chrome — не трогает ваш основной.\n"
                  "Это значит вы можете спокойно работать в обычном Chrome пока бот работает.\n\n"
                  "При первом запуске:\n"
                  "  1. Нажмите «Использовать профиль бота (по умолчанию)»\n"
                  "  2. Нажмите ▶ СТАРТ\n"
                  "  3. Откроется чистый Chrome — войдите в vk.com под админом группы\n"
                  "  4. Остановите бота (⏹ Стоп) и закройте этот Chrome\n"
                  "  5. Запустите бот снова — он уже будет залогинен\n\n"
                  "⚠  Аккаунт должен быть администратором нужной группы."
              ))

        block("3️⃣   Запуск",
              body_text=(
                  "Вкладка «Запуск»:\n\n"
                  "  • Ссылка на группу  —  например: https://vk.com/mygroup\n\n"
                  "  • Папка профиля Chrome  —  шаг 2 выше\n\n"
                  "  • Ограничить количеством  —  галочка если нужно обработать\n"
                  "    только N человек. Без галочки идёт по всем новым.\n\n"
                  "Нажмите  ▶ СТАРТ  и смотрите журнал справа.\n"
                  "Для остановки — кнопка  ⏹ Стоп."
              ))

        block("4️⃣   Калибровка кнопок", C["yellow_lt"], C["yellow"],
              body_text=(
                  "Программа кликает по областям экрана, которые вы выделяете мышкой.\n"
                  "Это нужно сделать ОДИН РАЗ при первом запуске.\n\n"
                  "  1. Откройте Chrome → vk.com/[группа]/settings/subscribers\n"
                  "  2. Перейдите на вкладку «🔧 Калибровка»\n"
                  "  3. Нажмите ▶ Начать калибровку\n"
                  "  4. ➕ Добавьте области в таком порядке:\n"
                  "     ① «...» у участника\n"
                  "     ② «Назначить руководителем»\n"
                  "     ③ Подтвердить «Назначить»\n"
                  "     ④ Снова «...»\n"
                  "     ⑤ «Убрать из руководителей»\n"
                  "     ⑥ Подтвердить «Убрать»\n"
                  "  5. ✅ Применить\n\n"
                  "Если VK изменит интерфейс — повторите калибровку."
              ))

        block("5️⃣   Капча",
              body_text=(
                  "VK иногда показывает капчу (галочку «Я не робот»).\n"
                  "Программа определяет её и нажимает автоматически.\n\n"
                  "Чтобы капча появлялась реже:\n"
                  "  • Не ставьте паузу меньше 8 секунд (вкладка «Настройки»)\n"
                  "  • Обрабатывайте не больше 30 человек в час"
              ))

        block("❓  Частые вопросы",
              body_text=(
                  "В:  Браузер открывается, но ничего не происходит?\n"
                  "О:  Проверьте что вы залогинены в VK в этом профиле Chrome.\n\n"
                  "В:  Пишет «Не нашёл участников»?\n"
                  "О:  Сделайте автокалибровку — VK обновился.\n\n"
                  "В:  Могут ли заблокировать группу?\n"
                  "О:  Риск минимальный при паузах 8–20 сек. Программа имитирует\n"
                  "    человека: случайные движения мыши, разные задержки.\n\n"
                  "В:  Где список обработанных?\n"
                  "О:  Файл processed.json рядом с программой. Также — вкладка «История»."
              ))

    # ── Страница «История» ───────────────────────────────────────────────────

    def _page_history(self, pg):
        pg.configure(fg_color="transparent")
        c = card(pg)
        c.pack(fill="both", expand=True)

        hr = ctk.CTkFrame(c, fg_color="transparent")
        hr.pack(fill="x", padx=18, pady=(14, 8))
        label(hr, "Обработанные аккаунты", FH2).pack(side="left")
        btn_ghost(hr, "🔄  Обновить", self._refresh_history,
                  ).pack(side="right")
        btn_ghost(hr, "🗑  Очистить базу", self._clear_history,
                  ).pack(side="right", padx=(0, 6))

        ctk.CTkFrame(c, fg_color=C["border"], height=1).pack(fill="x", padx=18)
        self._hist = ctk.CTkTextbox(c, font=FMONO, fg_color=C["bg"],
                                    text_color=C["text"], corner_radius=8,
                                    state="disabled")
        self._hist.pack(fill="both", expand=True, padx=14, pady=12)
        self._refresh_history()

    # ── Логика ───────────────────────────────────────────────────────────────

    def _toggle_limit(self):
        on = self._var_limit.get()
        self._inp_count.configure(
            state="normal" if on else "disabled",
            fg_color=C["white"] if on else C["bg"],
            border_color=C["blue"] if on else C["border"],
        )

    def _append_log(self, msg: str):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _on_log(self, msg: str):
        self.after(0, lambda m=msg: self._append_log(m))
        if self._scroll_panel:
            self._scroll_panel.add_log(msg)

    def _on_progress(self, done: int, total: int):
        def _u():
            self._session_done = done
            self._lbl_session.configure(text=str(done))
            self._progress.set(done / total if total else (done % 10) / 10)
            self._lbl_total.configure(text=str(storage.get_count()))
        self.after(0, _u)

    def _on_done(self):
        def _u():
            self._running = False
            self._btn_start.configure(state="normal")
            self._btn_stop.configure(state="disabled")
            self._dot.configure(text="⬤  Остановлен", text_color="#93C5FD")
            self._lbl_total.configure(text=str(storage.get_count()))
            if self._scroll_panel:
                self._scroll_panel.set_scroll_callback(None)
        self.after(0, _u)

    def _on_start(self):
        if self._running:
            return
        group   = self._inp_group.get().strip()
        profile = self._inp_profile.get().strip()
        use_lim = self._var_limit.get()
        count   = 0
        if use_lim:
            try:
                count = int(self._inp_count.get().strip())
                assert count > 0
            except Exception:
                self._append_log("⚠  Введите корректное число (больше 0)")
                return

        self.cfg.update(group_url=group, profile_path=profile,
                        use_limit=use_lim, count=count)
        cfg_module.save(self.cfg)

        self._running = True
        self._session_done = 0
        self._progress.set(0)
        self._lbl_session.configure(text="0")
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._dot.configure(text="⬤  Работает", text_color="#6EE7B7")

        from bot import VKBot
        self.bot = VKBot(
            group_url=group, profile_path=profile, count=count,
            delay_min=float(self.cfg.get("delay_min", 8)),
            delay_max=float(self.cfg.get("delay_max", 20)),
            admin_hold=float(self.cfg.get("admin_hold_seconds", 15)),
            on_log=self._on_log,
            on_progress=self._on_progress,
            on_done=self._on_done,
        )
        self.bot.start()

        if HAS_KEYBOARD:
            try:
                _keyboard_lib.add_hotkey("f8", self._on_stop)
            except Exception:
                pass

    def _on_stop(self):
        if HAS_KEYBOARD:
            try:
                _keyboard_lib.remove_hotkey("f8")
            except Exception:
                pass
        if self.bot:
            self.bot.stop()
        self._dot.configure(text="⬤  Останавливается…", text_color="#FCD34D")

    def _paste_into(self, inp: ctk.CTkEntry):
        try:
            text = self.clipboard_get()
            inp.delete(0, "end")
            inp.insert(0, text.strip())
        except Exception:
            pass

    def _pick_profile(self):
        p = filedialog.askdirectory(title="Выберите папку профиля Chrome")
        if p:
            self._inp_profile.delete(0, "end")
            self._inp_profile.insert(0, p)

    def _save_settings(self):
        try:
            self.cfg["delay_min"]           = float(self._s_delay_min.get())
            self.cfg["delay_max"]           = float(self._s_delay_max.get())
            self.cfg["admin_hold_seconds"]  = float(self._s_hold.get())
            cfg_module.save(self.cfg)
            self._append_log("✅  Настройки сохранены")
        except Exception as e:
            self._append_log(f"⚠  {e}")

    def _clear_history(self):
        storage.clear_all()
        self._lbl_total.configure(text="0")
        self._refresh_history()
        self._append_log("🗑  База обработанных аккаунтов очищена")

    def _refresh_history(self):
        data = storage.get_all()
        self._hist.configure(state="normal")
        self._hist.delete("1.0", "end")
        if not data:
            self._hist.insert("end", "Нет обработанных аккаунтов\n")
        else:
            self._hist.insert("end", f"Всего: {len(data)}\n\n")
            for aid, info in list(data.items())[-200:]:
                self._hist.insert("end", f"{info.get('date','?')}   {aid}\n")
        self._hist.configure(state="disabled")

    def _on_close(self):
        if self.bot:
            self.bot.stop()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
