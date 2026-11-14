"""Native "choose a folder" dialog.

Browsers never reveal a folder's real path to a page, but this backend runs
on the user's own machine, so it can show the system dialog itself. The
dialog runs in a separate process: GUI toolkits want their own main thread,
and a stuck dialog must not tie up the server.
"""
import subprocess
import sys
from pathlib import Path


# How long to wait for the user to pick a folder.
TIMEOUT_SECONDS = 10 * 60

_DIALOG = """
import sys, tkinter
from tkinter import filedialog

root = tkinter.Tk()
root.withdraw()
# Show in front of the browser rather than behind it.
root.attributes("-topmost", True)
path = filedialog.askdirectory(
    parent=root,
    title="Choose a folder for TidyByte to organize",
    initialdir=sys.argv[1] or None,
    mustexist=True,
)
root.destroy()
sys.stdout.write(path or "")
"""


class PickerUnavailable(RuntimeError):
    pass


def pick_folder(initial: str | None = None) -> str | None:
    """The folder the user chose, or None if they cancelled."""
    start = initial if initial and Path(initial).is_dir() else ""
    try:
        result = subprocess.run(
            [sys.executable, "-c", _DIALOG, start],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError as error:
        raise PickerUnavailable(f"Could not open the folder dialog: {error}") from error

    if result.returncode != 0:
        raise PickerUnavailable("Could not open the folder dialog on this computer.")

    chosen = result.stdout.strip()
    # tkinter answers with forward slashes; show the path the Windows way.
    return str(Path(chosen)) if chosen else None
