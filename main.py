"""VK Admin Notifier"""
import logging
import os
import threading
from tkinter import filedialog

import customtkinter as ctk

import config as cfg_module
import storage

try:
    import keyboard as _keyboard_lib
    HAS_KEYBOARD = True
except Exception:
    HAS_KEYBOARD = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C = {
    "bg":       "#0F1117",
    "panel":    "#1A1D27",
    "card":     "#20232F",
    "blue":     "#3B82F6",
    "blue_h":   "#2563EB",
    "blue_lt":  "#1E3A5F",
    "border":   "#2D3148",
    "text":     "#E2E8F0",
    "muted":    "#64748B",
    "green":    "#10B981",
    "green_lt": "#064E3B",
    "red":      "#EF4444",
    "red_lt":   "#450A0A",
}

FH1  = ("Segoe UI", 18, "bold")
FH2  = ("Segoe UI", 14, "bold")
FB   = ("Segoe UI", 13)
FSM  = ("Segoe UI", 11)
FMONO= ("Consolas", 12)

logging.basicConfig(level=logging.INFO)


def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=10,
                        border_width=1, border_color=C["border"], **kw)


def lbl(parent, text, font=FB, color=None, **kw):
    return ctk.CTkLabel(parent, text=text, font=font,
                        text_color=color or C["text"], **kw)


def inp(parent, placeholder="", **kw):
    return ctk.CTkEntry(parent, font=FB, height=40,
                        fg_color=C["panel"], border_color=C["border"],
                        border_width=1, text_color=C["text"],
                        placeholder_text=placeholder,
                        placeholder_text_color=C["muted"], **kw)


def btn_primary(parent, text, cmd, height=40, **kw):
    return ctk.CTkButton(parent, text=text, command=cmd, height=height,
                         font=(FB[0], FB[1], "bold"),
                         fg_color=C["blue"], hover_color=C["blue_h"],
                         text_color="#fff", corner_radius=8, **kw)


def btn_ghost(parent, text, cmd, height=36, **kw):
    return ctk.CTkButton(parent, text=text, command=cmd, height=height,
                         font=FSM, fg_color=C["panel"],
                         hover_color=C["blue_lt"], text_color=C["blue"],
                         border_width=1, border_color=C["border"],
                         corner_radius=8, **kw)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("VK Admin Notifier")
        self.geometry("900x620")
        self.minsize(800, 560)
        self.configure(fg_color=C["bg"])

        self.cfg = cfg_module.load()
        self.bot = None
        self._running = False
        self._session_done = 0

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=C["panel"], corner_radius=0, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        lbl(hdr, "VK Admin Notifier", FH1, C["text"]).pack(side="left", padx=20, pady=10)
        self._dot = ctk.CTkLabel(hdr, text="● Остановлен",
                                 font=FSM, text_color=C["muted"])
        self._dot.pack(side="right", padx=20)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # Sidebar
        sidebar = ctk.CTkFrame(body, fg_color=C["panel"], corner_radius=0,
                               width=160, border_width=1, border_color=C["border"])
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        self._content = ctk.CTkFrame(body, fg_color="transparent")
        self._content.pack(side="left", fill="both", expand=True, padx=14, pady=12)

        self._pages: dict[str, ctk.CTkFrame] = {}
        self._nav_btns: dict[str, ctk.CTkButton] = {}

        pages = [
            ("▶  Запуск",    self._page_run),
            ("⚙  Настройки", self._page_settings),
            ("📋  История",   self._page_history),
        ]

        ctk.CTkFrame(sidebar, fg_color="transparent", height=10).pack()
        for name, builder in pages:
            pg = ctk.CTkFrame(self._content, fg_color="transparent")
            builder(pg)
            self._pages[name] = pg

            nb = ctk.CTkButton(
                sidebar, text=name, anchor="w",
                font=FSM, height=38, corner_radius=6,
                fg_color="transparent", hover_color=C["blue_lt"],
                text_color=C["muted"],
                command=lambda n=name: self._show(n),
            )
            nb.pack(fill="x", padx=8, pady=2)
            self._nav_btns[name] = nb

        self._show("▶  Запуск")

    def _show(self, name: str):
        for pg in self._pages.values():
            pg.pack_forget()
        for n, nb in self._nav_btns.items():
            active = n == name
            nb.configure(
                fg_color=C["blue_lt"] if active else "transparent",
                text_color=C["blue"] if active else C["muted"],
                font=(FSM[0], FSM[1], "bold") if active else FSM,
            )
        self._pages[name].pack(fill="both", expand=True)

    # ── Страница «Запуск» ─────────────────────────────────────────────────────

    def _page_run(self, pg):
        left = ctk.CTkFrame(pg, fg_color="transparent", width=320)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)

        right = card(pg)
        right.pack(side="left", fill="both", expand=True)

        # Настройки запуска
        c1 = card(left)
        c1.pack(fill="x", pady=(0, 10))

        lbl(c1, "Ссылка на группу", FSM, C["muted"]).pack(anchor="w", padx=14, pady=(12, 3))
        gr = ctk.CTkFrame(c1, fg_color="transparent")
        gr.pack(fill="x", padx=14)
        self._inp_group = inp(gr, "https://vk.com/mygroup")
        self._inp_group.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(gr, text="📋", width=40, height=40, corner_radius=8,
                      fg_color=C["border"], hover_color=C["blue_lt"],
                      text_color=C["text"], font=FB,
                      command=lambda: self._paste_into(self._inp_group)
                      ).pack(side="left", padx=(6, 0))
        self._inp_group.insert(0, self.cfg.get("group_url", ""))

        lbl(c1, "Папка профиля Chrome", FSM, C["muted"]).pack(anchor="w", padx=14, pady=(10, 3))
        pr = ctk.CTkFrame(c1, fg_color="transparent")
        pr.pack(fill="x", padx=14)
        self._inp_profile = inp(pr, "Путь к профилю Chrome")
        self._inp_profile.pack(side="left", fill="x", expand=True)
        self._inp_profile.insert(0, self.cfg.get("profile_path", ""))
        ctk.CTkButton(pr, text="…", width=40, height=40, corner_radius=8,
                      fg_color=C["border"], hover_color=C["blue_lt"],
                      text_color=C["text"], font=FB,
                      command=self._pick_profile).pack(side="left", padx=(6, 0))

        default_prof = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "VKAdminBot", "chrome-profile")
        btn_ghost(c1, "Профиль по умолчанию", height=30,
                  cmd=lambda: (self._inp_profile.delete(0, "end"),
                               self._inp_profile.insert(0, default_prof))
                  ).pack(anchor="w", padx=14, pady=(6, 0))

        # Лимит
        lim_row = ctk.CTkFrame(c1, fg_color="transparent")
        lim_row.pack(fill="x", padx=14, pady=(12, 4))
        self._var_limit = ctk.BooleanVar(value=self.cfg.get("use_limit", False))
        ctk.CTkCheckBox(lim_row, text="Ограничить количеством",
                        variable=self._var_limit, font=FSM, text_color=C["text"],
                        fg_color=C["blue"], hover_color=C["blue_h"],
                        checkmark_color="#fff",
                        command=self._toggle_limit).pack(side="left")
        self._inp_count = inp(c1, "Например: 50", width=120)
        self._inp_count.pack(anchor="w", padx=14, pady=(0, 12))
        self._inp_count.insert(0, str(self.cfg.get("count", 50)))
        self._toggle_limit()

        # Старт/стоп
        c2 = card(left)
        c2.pack(fill="x", pady=(0, 10))

        br = ctk.CTkFrame(c2, fg_color="transparent")
        br.pack(fill="x", padx=14, pady=12)
        self._btn_start = btn_primary(br, "▶  СТАРТ", self._on_start, height=44)
        self._btn_start.pack(side="left", fill="x", expand=True)
        self._btn_stop = ctk.CTkButton(br, text="⏹ Стоп", height=44, width=80,
                                       font=FB, corner_radius=8,
                                       fg_color=C["border"], hover_color=C["red_lt"],
                                       text_color=C["muted"], state="disabled",
                                       command=self._on_stop)
        self._btn_stop.pack(side="left", padx=(8, 0))

        lbl(c2, "F8 — экстренная остановка", FSM, C["muted"]).pack(
            anchor="w", padx=14, pady=(0, 10))

        # Статистика
        c3 = card(left)
        c3.pack(fill="x")

        sr = ctk.CTkFrame(c3, fg_color="transparent")
        sr.pack(fill="x", padx=14, pady=12)

        def stat_box(parent, label_text, var_color, side="left"):
            f = ctk.CTkFrame(parent, fg_color=C["panel"], corner_radius=8)
            f.pack(side=side, fill="both", expand=True, padx=(0, 6) if side == "left" else 0)
            lbl(f, label_text, FSM, C["muted"]).pack(pady=(8, 0))
            v = ctk.CTkLabel(f, text="0", font=("Segoe UI", 24, "bold"), text_color=var_color)
            v.pack(pady=(0, 8))
            return v

        self._lbl_total   = stat_box(sr, "Всего", C["blue"])
        self._lbl_session = stat_box(sr, "Сессия", C["green"], side="right")
        self._lbl_total.configure(text=str(storage.get_count()))

        self._progress = ctk.CTkProgressBar(c3, height=5, corner_radius=3,
                                            fg_color=C["border"],
                                            progress_color=C["blue"])
        self._progress.set(0)
        self._progress.pack(fill="x", padx=14, pady=(0, 12))

        # Лог
        lbl(right, "Журнал", FH2).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkFrame(right, fg_color=C["border"], height=1).pack(fill="x", padx=16)
        self._log_box = ctk.CTkTextbox(right, font=FMONO,
                                       fg_color=C["panel"], text_color=C["text"],
                                       corner_radius=8, wrap="word", state="disabled")
        self._log_box.pack(fill="both", expand=True, padx=12, pady=10)

    # ── Страница «Настройки» ─────────────────────────────────────────────────

    def _page_settings(self, pg):
        c = card(pg)
        c.pack(fill="x")

        lbl(c, "Параметры работы", FH2).pack(anchor="w", padx=18, pady=(16, 4))
        ctk.CTkFrame(c, fg_color=C["border"], height=1).pack(fill="x", padx=18, pady=(0, 6))

        def row(text, attr, default, hint=""):
            lbl(c, text, FSM, C["muted"]).pack(anchor="w", padx=18, pady=(10, 2))
            if hint:
                lbl(c, hint, ("Segoe UI", 10), C["muted"]).pack(anchor="w", padx=18)
            e = inp(c)
            e.insert(0, str(self.cfg.get(attr, default)))
            e.pack(fill="x", padx=18, pady=(2, 0))
            return e

        self._s_delay_min = row("Минимальная пауза между участниками (сек)",
                                "delay_min", 8, "Рекомендуется ≥ 8 сек")
        self._s_delay_max = row("Максимальная пауза (сек)", "delay_max", 20)
        self._s_hold      = row("Держать должность администратора (сек)",
                                "admin_hold_seconds", 15, "Рекомендуется 15–30 сек")

        btn_primary(c, "Сохранить", self._save_settings, height=40
                    ).pack(anchor="w", padx=18, pady=18)

    # ── Страница «История» ───────────────────────────────────────────────────

    def _page_history(self, pg):
        c = card(pg)
        c.pack(fill="both", expand=True)

        hr = ctk.CTkFrame(c, fg_color="transparent")
        hr.pack(fill="x", padx=16, pady=(12, 8))
        lbl(hr, "Обработанные аккаунты", FH2).pack(side="left")
        btn_ghost(hr, "Обновить", self._refresh_history).pack(side="right")
        btn_ghost(hr, "Очистить", self._clear_history).pack(side="right", padx=(0, 6))

        ctk.CTkFrame(c, fg_color=C["border"], height=1).pack(fill="x", padx=16)
        self._hist = ctk.CTkTextbox(c, font=FMONO, fg_color=C["panel"],
                                    text_color=C["text"], corner_radius=8,
                                    state="disabled")
        self._hist.pack(fill="both", expand=True, padx=12, pady=10)
        self._refresh_history()

    # ── Логика ───────────────────────────────────────────────────────────────

    def _toggle_limit(self):
        on = self._var_limit.get()
        self._inp_count.configure(
            state="normal" if on else "disabled",
            fg_color=C["panel"] if on else C["bg"],
            border_color=C["blue"] if on else C["border"],
        )

    def _append_log(self, msg: str):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _on_log(self, msg: str):
        self.after(0, lambda m=msg: self._append_log(m))

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
            self._dot.configure(text="● Остановлен", text_color=C["muted"])
            self._lbl_total.configure(text=str(storage.get_count()))
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
        self._dot.configure(text="● Работает", text_color=C["green"])

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
        self._dot.configure(text="● Останавливается…", text_color=C["muted"])

    def _paste_into(self, e: ctk.CTkEntry):
        try:
            text = self.clipboard_get()
            e.delete(0, "end")
            e.insert(0, text.strip())
        except Exception:
            pass

    def _pick_profile(self):
        p = filedialog.askdirectory(title="Выберите папку профиля Chrome")
        if p:
            self._inp_profile.delete(0, "end")
            self._inp_profile.insert(0, p)

    def _save_settings(self):
        try:
            self.cfg["delay_min"]          = float(self._s_delay_min.get())
            self.cfg["delay_max"]          = float(self._s_delay_max.get())
            self.cfg["admin_hold_seconds"] = float(self._s_hold.get())
            cfg_module.save(self.cfg)
            self._append_log("✅  Настройки сохранены")
        except Exception as e:
            self._append_log(f"⚠  {e}")

    def _clear_history(self):
        storage.clear_all()
        self._lbl_total.configure(text="0")
        self._refresh_history()
        self._append_log("🗑  База очищена")

    def _refresh_history(self):
        data = storage.get_all()
        self._hist.configure(state="normal")
        self._hist.delete("1.0", "end")
        if not data:
            self._hist.insert("end", "Нет обработанных аккаунтов\n")
        else:
            self._hist.insert("end", f"Всего: {len(data)}\n\n")
            for aid, info in list(data.items())[-300:]:
                self._hist.insert("end", f"{info.get('date','?')}   {aid}\n")
        self._hist.configure(state="disabled")

    def _on_close(self):
        if self.bot:
            self.bot.stop()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
