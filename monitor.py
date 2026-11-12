"""Floating network monitor — red/black/white, minimal, wide & short.

No title bar, no minimize/maximize buttons. Always-on-top.
Updates every 2 seconds with live network rates.

Run with pythonw (no console window).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from linecheck.diagnostics import network_rates


# ---------------------------------------------------------------------------
# Colors — red / black / white
# ---------------------------------------------------------------------------

BG = "#0a0a0a"
TEXT = "#ffffff"
TEXT_DIM = "#666666"
RX = "#ff3333"
TX = "#ffffff"
FONT_MONO = ("Consolas", 10)
FONT_UI = ("Segoe UI", 9)


def _bps(value: float) -> str:
    if value < 0:
        return "0 B/s"
    if value < 1_000:
        return f"{value:.0f} B/s"
    if value < 1_000_000:
        return f"{value / 1_000:.1f} KB/s"
    if value < 1_000_000_000:
        return f"{value / 1_000_000:.2f} MB/s"
    return f"{value / 1_000_000_000:.2f} GB/s"


def _mbps(value: float) -> str:
    if value < 0:
        return "0.00"
    return f"{value / 1_000_000:.2f}"


class MonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self._running = True

        # No title bar, always-on-top
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=BG)

        # DPI awareness
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # Style
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Border.TFrame", background=BG, borderwidth=1, relief="solid")
        style.configure("TLabel", background=BG, foreground=TEXT_DIM, font=FONT_UI)
        style.configure("Dim.TLabel", foreground=TEXT_DIM, font=("Consolas", 8))

        # ── Main container with visible border ──
        border = ttk.Frame(self, style="Border.TFrame")
        border.pack(fill="both", expand=True, padx=2, pady=2)

        main = ttk.Frame(border)
        main.pack(padx=12, pady=10)

        # ── Header: red dot + name ──
        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 8))

        self.dot = tk.Canvas(header, width=6, height=6, bg=BG,
                              highlightthickness=0, bd=0)
        self.dot.pack(side="left")
        self.dot.create_oval(0, 0, 6, 6, fill=TEXT_DIM, outline="")

        ttk.Label(header, text="  OpenLineCheck", font=("Segoe UI", 9, "bold"),
                  foreground=TEXT, background=BG).pack(side="left")

        # ── Interface cards ──
        self.cards = ttk.Frame(main)
        self.cards.pack(fill="both", expand=True)

        # ── Footer ──
        footer = ttk.Frame(main)
        footer.pack(fill="x", pady=(6, 0))

        self.total_label = ttk.Label(footer, text="Total: ↓ 0  ↑ 0", style="Dim.TLabel")
        self.total_label.pack()

        self.status_label = ttk.Label(footer, text="Scanning...", style="Dim.TLabel")
        self.status_label.pack()

        # Set size and position
        self.minsize(340, 200)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"340x200+{sw-360}+{sh-240}")

        # ── Drag support ──
        self._drag_x = 0
        self._drag_y = 0
        self.bind("<ButtonPress-1>", self._on_drag_start)
        self.bind("<B1-Motion>", self._on_drag_move)

        # Start polling from main thread
        self.after(100, self._poll)

    def _poll(self):
        """Poll network rates and update UI — runs entirely in main thread."""
        try:
            data = network_rates()
            self._draw(data)
        except Exception:
            pass
        self.after(2000, self._poll)

    def _draw(self, data: dict):
        # Clear cards
        for w in self.cards.winfo_children():
            w.destroy()

        if "error" in data:
            self.dot.delete("all")
            self.dot.create_oval(0, 0, 6, 6, fill="#ff3333", outline="")
            self.status_label.config(text=data["error"])
            ttk.Label(self.cards, text="No data", font=FONT_UI,
                      foreground=TEXT_DIM, background=BG).pack(pady=16)
            return

        ifaces = data.get("interfaces", {})
        if not ifaces:
            self.dot.delete("all")
            self.dot.create_oval(0, 0, 6, 6, fill=TEXT_DIM, outline="")
            self.status_label.config(text="No interfaces")
            return

        # Green dot = active
        self.dot.delete("all")
        self.dot.create_oval(0, 0, 6, 6, fill="#3fb950", outline="")
        self.status_label.config(text=f"{len(ifaces)} interface{'s' if len(ifaces) != 1 else ''}")

        total_rx = 0
        total_tx = 0

        for name, rates in ifaces.items():
            rx = rates.get("rx_bps", 0)
            tx = rates.get("tx_bps", 0)
            total_rx += rx
            total_tx += tx

            # Card
            card = ttk.Frame(self.cards)
            card.pack(fill="x", pady=1)

            # Interface name
            ttk.Label(card, text=name, font=("Segoe UI", 9, "bold"),
                      foreground=TEXT, background=BG).pack(anchor="w", pady=(0, 2))

            # Download (red)
            ttk.Label(card, text="↓", font=FONT_MONO, foreground=RX,
                      background=BG).pack(side="left")
            ttk.Label(card, text=_bps(rx), font=FONT_MONO, foreground=RX,
                      background=BG).pack(side="left", padx=(2, 0))
            ttk.Label(card, text=f" {_mbps(rx)} Mbps", font=("Consolas", 8),
                      foreground="#882222", background=BG).pack(side="left", padx=(4, 0))

            # Upload (white)
            ttk.Label(card, text="↑", font=FONT_MONO, foreground=TX,
                      background=BG).pack(side="left")
            ttk.Label(card, text=_bps(tx), font=FONT_MONO, foreground=TX,
                      background=BG).pack(side="left", padx=(2, 0))
            ttk.Label(card, text=f" {_mbps(tx)} Mbps", font=("Consolas", 8),
                      foreground="#888888", background=BG).pack(side="left", padx=(4, 0))

        # Total
        self.total_label.config(text=f"Total: ↓ {_bps(total_rx)}  ↑ {_bps(total_tx)}")

    def _on_drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_move(self, event):
        deltax = event.x - self._drag_x
        deltay = event.y - self._drag_y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")


if __name__ == "__main__":
    MonitorApp().mainloop()
