"""
Плавающая панель прокрутки.

mode="calibrate" — полная: CDP самостоятельно, Тест, Сохранить, Num2/Num8.
mode="run"       — упрощённая: стрелки + лог, CDP передаётся снаружи.
"""
import threading
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

import calibrator

try:
    import keyboard as _kb
    HAS_KB = True
except Exception:
    HAS_KB = False


class ScrollPanel(ctk.CTkToplevel):
    W = 420

    def __init__(self, parent, mode: str = "calibrate"):
        super().__init__(parent)
        self._mode = mode  # "calibrate" | "run"
        self._scroll_cb: Optional[Callable[[int], dict]] = None
        self._cdp = None          # собственный CDP-клиент (только calibrate)
        self._kb_bound = False
        self._px_var = tk.StringVar(value=str(self._load_step()))

        title = "Панель прокрутки — Калибровка" if mode == "calibrate" else "Панель прокрутки"
        self.title(title)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close_btn)

        H = 340 if mode == "calibrate" else 290
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{self.W}x{H}+{sw - self.W - 16}+{sh - H - 60}")

        self._build()

        if mode == "calibrate":
            self._connect_cdp()
            self._bind_numpad()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build(self):
        self.configure(fg_color="#0f172a")

        # Заголовок
        hdr = ctk.CTkFrame(self, fg_color="#1e293b", corner_radius=0, height=34)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        icon = "🔧" if self._mode == "calibrate" else "⚙"
        ctk.CTkLabel(hdr, text=f"{icon}  Панель прокрутки",
                     font=("Segoe UI", 11, "bold"),
                     text_color="#94a3b8").pack(side="left", padx=12, pady=6)
        if self._mode == "calibrate":
            ctk.CTkLabel(hdr, text="Num2 ↓  Num8 ↑",
                         font=("Segoe UI", 9), text_color="#475569"
                         ).pack(side="right", padx=10)

        # Строка управления
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=10, pady=8)

        ctk.CTkButton(ctrl, text="⬆", width=46, height=38,
                      fg_color="#1e3a5f", hover_color="#2563eb",
                      text_color="#93c5fd", font=("Segoe UI", 18),
                      command=self._scroll_up).pack(side="left", padx=(0, 4))

        ctk.CTkButton(ctrl, text="⬇", width=46, height=38,
                      fg_color="#1e3a5f", hover_color="#2563eb",
                      text_color="#93c5fd", font=("Segoe UI", 18),
                      command=self._scroll_down).pack(side="left", padx=(0, 10))

        ctk.CTkEntry(ctrl, textvariable=self._px_var, width=68,
                     font=("Segoe UI", 13),
                     fg_color="#1e293b", border_color="#334155",
                     text_color="#f1f5f9").pack(side="left", padx=(0, 4))

        ctk.CTkLabel(ctrl, text="px", font=("Segoe UI", 11),
                     text_color="#64748b").pack(side="left", padx=(0, 10))

        if self._mode == "calibrate":
            ctk.CTkButton(ctrl, text="Тест ↓", width=66, height=34,
                          fg_color="#0d9488", hover_color="#0f766e",
                          text_color="#fff", font=("Segoe UI", 11),
                          command=self._test).pack(side="left", padx=(0, 4))

            ctk.CTkButton(ctrl, text="💾 Сохранить", width=96, height=34,
                          fg_color="#1d4ed8", hover_color="#1e40af",
                          text_color="#fff", font=("Segoe UI", 11),
                          command=self._save).pack(side="left")

        if self._mode == "calibrate":
            # Кнопка переподключения CDP
            rconn = ctk.CTkFrame(self, fg_color="transparent")
            rconn.pack(fill="x", padx=10, pady=(0, 4))
            ctk.CTkButton(rconn, text="🔌 Переподключить CDP", height=28,
                          fg_color="#1e293b", hover_color="#334155",
                          text_color="#64748b", font=("Segoe UI", 10),
                          command=self._connect_cdp).pack(side="left")

        # Разделитель
        ctk.CTkFrame(self, fg_color="#1e293b", height=1).pack(fill="x", padx=10)

        # Лог
        self._log = ctk.CTkTextbox(
            self, height=200,
            font=("Consolas", 10),
            fg_color="#020617",
            text_color="#94a3b8",
            corner_radius=0,
        )
        self._log.pack(fill="both", expand=True, padx=0, pady=0)
        self._log.configure(state="disabled")

    # ── Публичный API ─────────────────────────────────────────────────────────

    def set_scroll_callback(self, cb: Optional[Callable[[int], dict]]):
        self._scroll_cb = cb

    def add_log(self, msg: str):
        self.after(0, lambda m=msg: self._insert_log(m))

    def close(self):
        self._cleanup()
        try:
            self.destroy()
        except Exception:
            pass

    # ── CDP (только calibrate) ────────────────────────────────────────────────

    def _connect_cdp(self):
        import cdp as cdp_module

        def _try():
            try:
                self._insert_log_ts("🔌 Подключение к CDP (порт 9222)...")
                if self._cdp:
                    try:
                        self._cdp.close()
                    except Exception:
                        pass
                client = cdp_module.CDPClient()
                client.connect("vk.com")
                self._cdp = client
                self._scroll_cb = client.scroll_by_delta
                self.after(0, lambda: self._insert_log("✅ CDP подключён — можно крутить"))
            except Exception as e:
                self.after(0, lambda err=e: self._insert_log(f"⚠ CDP: {err}"))

        threading.Thread(target=_try, daemon=True).start()

    # ── Numpad ────────────────────────────────────────────────────────────────

    def _bind_numpad(self):
        if not HAS_KB:
            return
        try:
            _kb.add_hotkey("num 2", self._scroll_down)
            _kb.add_hotkey("num 8", self._scroll_up)
            self._kb_bound = True
            self.after(200, lambda: self._insert_log("⌨ Num2=↓  Num8=↑ — активны"))
        except Exception:
            pass

    def _unbind_numpad(self):
        if not self._kb_bound:
            return
        try:
            _kb.remove_hotkey("num 2")
            _kb.remove_hotkey("num 8")
        except Exception:
            pass
        self._kb_bound = False

    # ── Внутренние ───────────────────────────────────────────────────────────

    def _cleanup(self):
        self._unbind_numpad()
        if self._cdp:
            try:
                self._cdp.close()
            except Exception:
                pass
            self._cdp = None

    def _on_close_btn(self):
        if self._mode == "calibrate":
            self._cleanup()
            try:
                self.destroy()
            except Exception:
                pass
        # run-mode нельзя закрыть

    def _insert_log(self, msg: str):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        lines = int(self._log.index("end-1c").split(".")[0])
        if lines > 200:
            self._log.delete("1.0", f"{lines - 200}.0")
        self._log.configure(state="disabled")

    def _insert_log_ts(self, msg: str):
        self.after(0, lambda m=msg: self._insert_log(m))

    def _get_px(self) -> int:
        try:
            return max(1, int(self._px_var.get()))
        except ValueError:
            return 100

    def _do_scroll(self, px: int):
        if not self._scroll_cb:
            self._insert_log("⚠ CDP не подключён")
            return
        try:
            info = self._scroll_cb(px)
            direction = "⬇" if px > 0 else "⬆"
            actual = info.get("actual", "?")
            container = info.get("container", "?")
            self._insert_log(f"{direction} {px}px → применено {actual}px  [{container}]")
        except Exception as e:
            self._insert_log(f"❌ {e}")

    def _scroll_down(self):
        self._do_scroll(self._get_px())

    def _scroll_up(self):
        self._do_scroll(-self._get_px())

    def _test(self):
        if not self._scroll_cb:
            self._insert_log("⚠ CDP не подключён")
            return
        px = self._get_px()
        try:
            info = self._scroll_cb(px)
            actual = info.get("actual", "?")
            ok = actual == px
            mark = "✅" if ok else "⚠"
            self._insert_log(
                f"{mark} Тест: запрошено {px}px, применено {actual}px"
                + ("  ← точно!" if ok else f"  ← расхождение {abs(px - (actual or 0))}px")
            )
        except Exception as e:
            self._insert_log(f"❌ {e}")

    def _save(self):
        px = self._get_px()
        areas = calibrator.load_areas()
        areas = [a for a in areas if a.get("type") != "step"]
        areas.append({
            "type": "step",
            "dy": px,
            "y1": 0, "y2": px,
            "cx": 0, "cy": 0, "w": 1, "h": 1,
        })
        calibrator.save_areas(areas)
        self._insert_log(f"✅ Шаг сохранён: {px}px")

    def _load_step(self) -> int:
        areas = calibrator.load_areas()
        steps = [a for a in areas if a.get("type") == "step"]
        return steps[0]["dy"] if steps else 100
