from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import (
    BOTH,
    DISABLED,
    END,
    HORIZONTAL,
    LEFT,
    NORMAL,
    RIGHT,
    VERTICAL,
    Canvas,
    DoubleVar,
    IntVar,
    Label,
    Listbox,
    StringVar,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
    ttk,
)

import pyautogui
from PIL import Image


pyautogui.FAILSAFE = True


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    width: int
    height: int

    @property
    def display(self) -> str:
        return f"x={self.left}, y={self.top}, w={self.width}, h={self.height}"


@dataclass(frozen=True)
class Point:
    x: int
    y: int

    @property
    def display(self) -> str:
        return f"x={self.x}, y={self.y}"


class SelectionOverlay(Toplevel):
    def __init__(self, parent: Tk, mode: str, on_done):
        super().__init__(parent)
        self.parent = parent
        self.mode = mode
        self.on_done = on_done
        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.25)
        self.configure(bg="black")

        width, height = pyautogui.size()
        self.geometry(f"{width}x{height}+0+0")

        self.canvas = Canvas(self, cursor="crosshair", bg="black", highlightthickness=0)
        self.canvas.pack(fill=BOTH, expand=True)

        prompt = (
            "Drag to select the screenshot area. Press Esc to cancel."
            if mode == "rect"
            else "Click the position to automate. Press Esc to cancel."
        )
        self.canvas.create_text(
            width // 2,
            40,
            fill="white",
            text=prompt,
            font=("Helvetica", 22, "bold"),
        )

        if mode == "rect":
            self.canvas.bind("<ButtonPress-1>", self._start_rect)
            self.canvas.bind("<B1-Motion>", self._draw_rect)
            self.canvas.bind("<ButtonRelease-1>", self._finish_rect)
        else:
            self.canvas.bind("<ButtonRelease-1>", self._finish_point)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.focus_force()
        self.grab_set()

    def destroy(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self.parent.deiconify()
        super().destroy()

    def _start_rect(self, event) -> None:
        self.start_x = event.x_root
        self.start_y = event.y_root
        self.rect_id = self.canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#2dd4bf",
            width=3,
        )

    def _draw_rect(self, event) -> None:
        if self.rect_id is None:
            return
        self.canvas.coords(
            self.rect_id,
            self.start_x,
            self.start_y,
            event.x_root,
            event.y_root,
        )

    def _finish_rect(self, event) -> None:
        left = min(self.start_x, event.x_root)
        top = min(self.start_y, event.y_root)
        right = max(self.start_x, event.x_root)
        bottom = max(self.start_y, event.y_root)

        if right - left < 2 or bottom - top < 2:
            messagebox.showwarning("Selection too small", "Please drag a larger area.")
            return

        self.on_done(Rect(left, top, right - left, bottom - top))
        self.destroy()

    def _finish_point(self, event) -> None:
        self.on_done(Point(event.x_root, event.y_root))
        self.destroy()


class ProgressOverlay(Toplevel):
    WIDTH = 230
    HEIGHT = 74
    MARGIN = 12

    def __init__(self, parent: Tk, rect: Rect, cycles: int, stop_command):
        super().__init__(parent)
        self.progress_text = StringVar(value=f"Preparing... 0/{cycles}")

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#111827", padx=10, pady=8)

        Label(
            self,
            textvariable=self.progress_text,
            fg="white",
            bg="#111827",
            font=("Helvetica", 13, "bold"),
        ).pack(anchor="w")

        ttk.Button(self, text="Stop", command=stop_command).pack(anchor="e", pady=(6, 0))
        self.geometry(self._geometry_for(rect))

    def _geometry_for(self, rect: Rect) -> str:
        screen_width, _screen_height = pyautogui.size()
        left_corner = (self.MARGIN, self.MARGIN, self.WIDTH, self.HEIGHT)
        right_corner = (
            max(self.MARGIN, screen_width - self.WIDTH - self.MARGIN),
            self.MARGIN,
            self.WIDTH,
            self.HEIGHT,
        )

        chosen = right_corner if self._intersects(left_corner, rect) else left_corner
        if self._intersects(chosen, rect) and not self._intersects(right_corner, rect):
            chosen = right_corner

        x, y, width, height = chosen
        return f"{width}x{height}+{x}+{y}"

    def _intersects(self, box: tuple[int, int, int, int], rect: Rect) -> bool:
        x, y, width, height = box
        return not (
            x + width <= rect.left
            or rect.left + rect.width <= x
            or y + height <= rect.top
            or rect.top + rect.height <= y
        )

    def update_progress(self, text: str) -> None:
        self.progress_text.set(text)


class BatchScreenshotterApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title("Batch Screenshotter")
        self.root.geometry("680x520")
        self.root.minsize(620, 480)

        self.rect: Rect | None = None
        self.click_point: Point | None = None
        self.worker: threading.Thread | None = None
        self.progress_overlay: ProgressOverlay | None = None
        self.stop_requested = threading.Event()
        self.closing = False

        self.cycles_var = IntVar(value=10)
        self.delay_var = DoubleVar(value=1.0)
        self.initial_delay_var = DoubleVar(value=3.0)
        self.output_dir_var = StringVar(value=str(Path.cwd() / "screenshots"))
        self.pdf_name_var = StringVar(value="batch_screenshots.pdf")
        self.status_var = StringVar(value="Select an area and click position to begin.")
        self.progress_var = IntVar(value=0)

        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill=BOTH, expand=True)

        selection = ttk.LabelFrame(outer, text="Capture Setup", padding=12)
        selection.pack(fill="x")

        area_row = ttk.Frame(selection)
        area_row.pack(fill="x", pady=(0, 8))
        ttk.Label(area_row, text="Screenshot area:", width=18).pack(side=LEFT)
        self.area_label = ttk.Label(area_row, text="Not selected")
        self.area_label.pack(side=LEFT, fill="x", expand=True)
        self.area_button = ttk.Button(area_row, text="Select Area", command=self.select_area)
        self.area_button.pack(side=RIGHT)

        click_row = ttk.Frame(selection)
        click_row.pack(fill="x")
        ttk.Label(click_row, text="Click position:", width=18).pack(side=LEFT)
        self.click_label = ttk.Label(click_row, text="Not selected")
        self.click_label.pack(side=LEFT, fill="x", expand=True)
        self.click_button = ttk.Button(click_row, text="Select Click", command=self.select_click)
        self.click_button.pack(side=RIGHT)

        config = ttk.LabelFrame(outer, text="Run Options", padding=12)
        config.pack(fill="x", pady=14)

        grid = ttk.Frame(config)
        grid.pack(fill="x")
        ttk.Label(grid, text="Cycles").grid(row=0, column=0, sticky="w")
        self.cycles_spin = ttk.Spinbox(grid, from_=1, to=10000, textvariable=self.cycles_var, width=10)
        self.cycles_spin.grid(row=1, column=0, sticky="w", padx=(0, 18))

        ttk.Label(grid, text="Delay after click (seconds)").grid(row=0, column=1, sticky="w")
        self.delay_spin = ttk.Spinbox(
            grid,
            from_=0.0,
            to=3600.0,
            increment=0.25,
            textvariable=self.delay_var,
            width=12,
        )
        self.delay_spin.grid(row=1, column=1, sticky="w", padx=(0, 18))

        ttk.Label(grid, text="Initial delay (seconds)").grid(row=0, column=2, sticky="w")
        self.initial_delay_spin = ttk.Spinbox(
            grid,
            from_=0.0,
            to=3600.0,
            increment=0.25,
            textvariable=self.initial_delay_var,
            width=12,
        )
        self.initial_delay_spin.grid(row=1, column=2, sticky="w", padx=(0, 18))

        ttk.Label(grid, text="PDF file name").grid(row=0, column=3, sticky="w")
        self.pdf_entry = ttk.Entry(grid, textvariable=self.pdf_name_var, width=28)
        self.pdf_entry.grid(row=1, column=3, sticky="ew")
        grid.columnconfigure(3, weight=1)

        output_row = ttk.Frame(config)
        output_row.pack(fill="x", pady=(12, 0))
        ttk.Label(output_row, text="Output folder:", width=14).pack(side=LEFT)
        self.output_entry = ttk.Entry(output_row, textvariable=self.output_dir_var)
        self.output_entry.pack(side=LEFT, fill="x", expand=True, padx=(0, 8))
        self.browse_button = ttk.Button(output_row, text="Browse", command=self.choose_output_dir)
        self.browse_button.pack(side=RIGHT)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 12))
        self.start_button = ttk.Button(actions, text="Start", command=self.start)
        self.start_button.pack(side=LEFT)
        self.stop_button = ttk.Button(actions, text="Stop", command=self.stop, state=DISABLED)
        self.stop_button.pack(side=LEFT, padx=(8, 0))

        self.progress = ttk.Progressbar(actions, variable=self.progress_var, orient=HORIZONTAL)
        self.progress.pack(side=LEFT, fill="x", expand=True, padx=12)

        log_frame = ttk.LabelFrame(outer, text="Log", padding=8)
        log_frame.pack(fill=BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, orient=VERTICAL)
        self.log = Listbox(log_frame, yscrollcommand=scrollbar.set, height=10)
        scrollbar.config(command=self.log.yview)
        self.log.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill="y")

        ttk.Label(outer, textvariable=self.status_var).pack(fill="x", pady=(10, 0))

    def select_area(self) -> None:
        self.root.withdraw()
        self.root.after(250, lambda: SelectionOverlay(self.root, "rect", self._set_area))

    def select_click(self) -> None:
        self.root.withdraw()
        self.root.after(250, lambda: SelectionOverlay(self.root, "point", self._set_click))

    def _set_area(self, rect: Rect) -> None:
        self.root.deiconify()
        self.rect = rect
        self.area_label.config(text=rect.display)
        self._log(f"Selected area: {rect.display}")

    def _set_click(self, point: Point) -> None:
        self.root.deiconify()
        self.click_point = point
        self.click_label.config(text=point.display)
        self._log(f"Selected click position: {point.display}")

    def choose_output_dir(self) -> None:
        directory = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(Path.cwd()))
        if directory:
            self.output_dir_var.set(directory)

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            config = self._validated_config()
        except ValueError as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            return

        self.stop_requested.clear()
        self.progress.config(maximum=config["cycles"])
        self.progress_var.set(0)
        self._set_running(True)
        self._log("Starting batch capture.")
        self._show_progress_overlay(config["rect"], config["cycles"])
        self.root.withdraw()

        self.worker = threading.Thread(target=self._run_capture, kwargs=config, daemon=True)
        self.worker.start()

    def stop(self) -> None:
        self.stop_requested.set()
        self.status_var.set("Stopping after the current step...")
        self._log("Stop requested.")

    def _validated_config(self) -> dict:
        if self.rect is None:
            raise ValueError("Please select a screenshot area.")
        if self.click_point is None:
            raise ValueError("Please select a click position.")

        cycles = int(self.cycles_var.get())
        delay = float(self.delay_var.get())
        initial_delay = float(self.initial_delay_var.get())
        if cycles < 1:
            raise ValueError("Cycles must be at least 1.")
        if delay < 0:
            raise ValueError("Delay must not be negative.")
        if initial_delay < 0:
            raise ValueError("Initial delay must not be negative.")

        output_dir = Path(self.output_dir_var.get()).expanduser()
        pdf_name = self.pdf_name_var.get().strip()
        if not pdf_name:
            raise ValueError("Please enter a PDF file name.")
        if not pdf_name.lower().endswith(".pdf"):
            pdf_name += ".pdf"

        return {
            "rect": self.rect,
            "click_point": self.click_point,
            "cycles": cycles,
            "delay": delay,
            "initial_delay": initial_delay,
            "output_dir": output_dir,
            "pdf_path": output_dir / pdf_name,
        }

    def _run_capture(
        self,
        rect: Rect,
        click_point: Point,
        cycles: int,
        delay: float,
        initial_delay: float,
        output_dir: Path,
        pdf_path: Path,
    ) -> None:
        images: list[Path] = []
        run_dir = output_dir / datetime.now().strftime("run_%Y%m%d_%H%M%S")

        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            pdf_path.parent.mkdir(parents=True, exist_ok=True)

            if initial_delay > 0:
                self._countdown_initial_delay(initial_delay, cycles)

            for index in range(1, cycles + 1):
                if self.stop_requested.is_set():
                    break

                self._ui(lambda i=index: self.status_var.set(f"Capturing screenshot {i} of {cycles}..."))
                self._ui(lambda i=index: self._set_overlay_text(f"Capturing {i}/{cycles}"))
                screenshot = pyautogui.screenshot(region=(rect.left, rect.top, rect.width, rect.height))
                image_path = run_dir / f"screenshot_{index:04d}.png"
                screenshot.save(image_path)
                images.append(image_path)

                self._ui(lambda i=index, p=image_path: self._log(f"Saved {i}: {p.name}"))
                self._ui(lambda i=index: self.progress_var.set(i))
                self._ui(lambda i=index: self._set_overlay_text(f"Saved {i}/{cycles}"))

                pyautogui.click(click_point.x, click_point.y)
                if index < cycles:
                    self._ui(lambda i=index: self._set_overlay_text(f"Waiting... {i}/{cycles}"))
                    self._sleep_with_stop(delay)

            if images:
                self._ui(lambda: self.status_var.set("Building PDF..."))
                self._ui(lambda: self._set_overlay_text("Building PDF..."))
                self._create_pdf(images, pdf_path)
                self._ui(lambda: self._log(f"PDF created: {pdf_path}"))
                if self.stop_requested.is_set() and len(images) < cycles:
                    final_status = f"Stopped early. Saved {len(images)} image(s) and PDF."
                else:
                    final_status = f"Finished. Saved {len(images)} image(s) and PDF."
            else:
                final_status = "Stopped before any screenshots were captured."

            self._ui(lambda: self._finish_run(final_status, show_error=False))
        except Exception as exc:
            self._ui(lambda exc=exc: self._log(f"Error: {exc}"))
            self._ui(lambda exc=exc: self._finish_run(str(exc), show_error=True))
        finally:
            pass

    def _countdown_initial_delay(self, initial_delay: float, cycles: int) -> None:
        end_time = time.monotonic() + initial_delay
        while time.monotonic() < end_time:
            if self.stop_requested.is_set():
                return
            remaining = max(0.0, end_time - time.monotonic())
            self._ui(
                lambda r=remaining: self._set_overlay_text(
                    f"Starting in {r:.1f}s 0/{cycles}"
                )
            )
            time.sleep(min(0.1, remaining))

    def _sleep_with_stop(self, delay: float) -> None:
        end_time = time.monotonic() + delay
        while time.monotonic() < end_time:
            if self.stop_requested.is_set():
                return
            time.sleep(min(0.1, end_time - time.monotonic()))

    def _create_pdf(self, image_paths: list[Path], pdf_path: Path) -> None:
        pdf_images: list[Image.Image] = []
        for path in image_paths:
            with Image.open(path) as image:
                pdf_images.append(image.convert("RGB"))

        first, *rest = pdf_images
        first.save(pdf_path, save_all=True, append_images=rest)

        for image in pdf_images:
            image.close()

    def _set_running(self, running: bool) -> None:
        state = DISABLED if running else NORMAL
        self.start_button.config(state=state)
        self.stop_button.config(state=NORMAL if running else DISABLED)
        for widget in (
            self.area_button,
            self.click_button,
            self.cycles_spin,
            self.delay_spin,
            self.initial_delay_spin,
            self.pdf_entry,
            self.output_entry,
            self.browse_button,
        ):
            widget.config(state=state)

    def _show_progress_overlay(self, rect: Rect, cycles: int) -> None:
        self._hide_progress_overlay()
        self.progress_overlay = ProgressOverlay(
            parent=self.root,
            rect=rect,
            cycles=cycles,
            stop_command=self.stop,
        )

    def _hide_progress_overlay(self) -> None:
        if self.progress_overlay is None:
            return
        self.progress_overlay.destroy()
        self.progress_overlay = None

    def _set_overlay_text(self, text: str) -> None:
        if self.progress_overlay is not None:
            self.progress_overlay.update_progress(text)

    def _finish_run(self, message: str, show_error: bool) -> None:
        self._hide_progress_overlay()
        self.root.deiconify()
        self._set_running(False)

        if show_error:
            self.status_var.set("Capture failed.")
            messagebox.showerror("Capture failed", message)
            return

        self.status_var.set(message)
        messagebox.showinfo("Batch complete", message)

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.insert(END, f"[{timestamp}] {message}")
        self.log.yview_moveto(1)

    def _ui(self, callback) -> None:
        if self.closing:
            return
        self.root.after(0, callback)

    def close(self) -> None:
        self.closing = True
        self.stop_requested.set()
        self._hide_progress_overlay()
        self.root.destroy()


def main() -> None:
    root = Tk()
    app = BatchScreenshotterApp(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
