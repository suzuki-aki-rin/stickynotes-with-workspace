# For Nuitka , something bad code
# import sys
# import subprocess
#
# # Must happen before pystray or any gi-dependent import
# if getattr(sys, "frozen", False) or "__compiled__" in dir():  # running as Nuitka binary
#     result = subprocess.run(
#         [
#             "python3",
#             "-c",
#             "import gi, os; print(os.path.dirname(os.path.dirname(gi.__file__)))",
#         ],
#         capture_output=True,
#         text=True,
#     )
#     gi_parent = result.stdout.strip()
#     if gi_parent:
#         sys.path.insert(0, gi_parent)

import logging
import os
import sys
import threading


from stickynotes import StickyNotesApp

# Without it, pystray_background is xorg.
# gtk and appindicator maybe same
os.environ["PYSTRAY_BACKEND"] = "gtk"
import pystray
from PIL import Image, ImageDraw


#  -------- for pyinstaller  ------------------------------------------------------------------------

# If gi is not bundled, fall back to system gi
if getattr(sys, "frozen", False):  # running as PyInstaller binary
    # Add system Python's site-packages to path
    sys.path.insert(0, "/usr/lib/python3/dist-packages")  # Linux (Debian/Ubuntu)
    # or: '/usr/lib64/python3/site-packages'


#  SECTION:=============================================================
#            Task tray
#  =====================================================================
class StikcyNoteTray:
    def __init__(self, app: StickyNotesApp):
        self.app = app

    # ---- Tray setup ----
    def create_image(self):
        """Generate a simple tray icon image."""
        img = Image.new("RGB", (64, 64), (0, 128, 255))
        d = ImageDraw.Draw(img)
        d.rectangle((16, 16, 48, 48), fill=(255, 255, 0))
        return img

    def on_exit(self, icon, item):
        icon.stop()  # Stop pystray
        if self.app:
            self.app.after(0, self.app.close_all)  # Stop Tkinter mainloop

    def run_tray(self):
        icon = pystray.Icon(
            "Sticky Notes",
            self.create_image(),
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Show all notes",
                    self.app.show_all,
                ),
                pystray.MenuItem(
                    "Hide all notes",
                    self.app.hide_all,
                ),
                pystray.MenuItem("Exit", self.on_exit),
            ),
        )
        icon.run()


def main():
    import fcntl

    #  SECTION:=============================================================
    #            Check if running
    #  =====================================================================
    def check_single_instance(lockfile):
        fp = open(lockfile, "w")
        try:
            fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            logger.error("Another instance is already running.")
            raise SystemExit()

        return fp  # Keep the file open to hold lock

    lockfile = "/tmp/my_sticknote_app.lock"
    lock_fp = check_single_instance(lockfile)

    #  SECTION:=============================================================
    #            Logger
    #  =====================================================================

    logging.basicConfig(
        # level=logging.DEBUG,
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(funcName)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    #  SECTION:=============================================================
    #            Main loop
    #  =====================================================================

    try:
        app = StickyNotesApp()
        tray = StikcyNoteTray(app)

        # Run tray in background
        threading.Thread(target=tray.run_tray, daemon=True).start()

        app.mainloop()
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        # Ensure lock file is cleaned up
        try:
            lock_fp.close()
            os.unlink(lockfile)
        except Exception as e:
            logger.error(
                f"Bad lockfile.: {e}",
            )


if __name__ == "__main__":
    main()
