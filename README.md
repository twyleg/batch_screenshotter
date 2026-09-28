# Batch Screenshotter

A small Tkinter desktop app for repeated screenshot capture:

1. Select a rectangular screenshot area.
2. Select a screen position to click after every capture.
3. Configure the initial delay, delay between captures, and number of cycles.
4. Start the run.

Each screenshot is saved as a PNG, and the captured images are combined into a PDF at the end.
The main window hides while a run is active, and a small progress overlay remains visible outside the selected capture area when possible.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python batch_screenshotter.py
```

On macOS, grant the terminal or Python app Screen Recording and Accessibility permissions when prompted. The click automation and screen capture will not work reliably without them.

Move the mouse to a screen corner to trigger PyAutoGUI's fail-safe if you need to abort urgently.
