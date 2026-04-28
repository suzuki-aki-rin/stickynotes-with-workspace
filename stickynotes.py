import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import colorchooser, font, messagebox, simpledialog, ttk

from tkfontselector import ask_font

#  SECTION:=============================================================
#            Constants
#  =====================================================================

# Save contents and setting to this file when exiting.
STATE_FILE = str(Path("~/.config/my_stickynotes/notes_state_work.json").expanduser())
BACKUP_DIR = str(Path("~/.config/my_stickynotes/backups").expanduser())

# Default values. Values in STATE_FILE are preferred.
# UI FONT requires an Emoji font.
# UI_FONT = ("Noto Color Emoji", 14)
UI_FONT = ("Cica", 16)
TEXT_FONT = ("Cica", 16)
TEXT_COLOR = "black"
TEXT_BG_COLOR = "white"

# save timing - longer delays reduce disk writes
FAST_SAVE_DELAY = 500  # ms - for critical changes (was 200)
NORMAL_SAVE_DELAY = 3000  # ms - for regular typing (was 1000)
GEOMETRY_SAVE_DELAY = 2000  # ms - for window resizing (was 500)
IDLE_SAVE_DELAY = 10000  # ms - save when user goes idle

# Backup optimization
# MAX_BACKUPS = 3             # Fewer backups (was 5)
MAX_BACKUPS = 0  # Trun-off backup
BACKUP_INTERVAL = 300  # seconds - only backup every 5 minutes
MIN_CHANGES_FOR_BACKUP = 10  # Only backup after significant changes

# Change detection thresholds
MIN_CONTENT_CHANGE = 5  # characters - minimum change to trigger save
MIN_GEOMETRY_CHANGE = 10  # pixels - minimum movement to trigger save


#  SECTION:=============================================================
#            Logging, module
#  =====================================================================

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


#  SECTION:=============================================================
#            Functions, helper
#  =====================================================================


def font_exists(font_name):
    root = tk.Tk()
    root.withdraw()  # Hide main window
    available_fonts = font.families()
    root.destroy()  # Clean up the Tk instance
    return font_name in available_fonts


def shorten_text(text, max_length=15):
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def get_all_current_workspaces() -> list[dict]:
    # Run wmctrl -d and capture output
    try:
        result = subprocess.run(
            ["wmctrl", "-d"], capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split("\n")

        workspaces = []

        for line in lines:
            parts = line.split()
            if len(parts) >= 10:
                number = int(parts[0])
                is_current = parts[1] == "*"
                # Workspace name starts from column 10 onward in wmctrl output
                name = " ".join(parts[9:])
                workspaces.append(
                    {"number": number, "name": name, "is_current": is_current}
                )

        return workspaces
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ) as e:
        logger.warning(f"Could not get workspaces: {e}")
        return [{"number": 0, "name": "Desktop", "is_current": True}]


def get_current_workspace_number(workspaces: list[dict] | None = None) -> int | None:
    if not workspaces:
        workspaces = get_all_current_workspaces()
    for ws in workspaces:
        if ws["is_current"]:
            return ws["number"]
    logger.error(f"Something bad. workspaces: {workspaces}")
    return 0  # Default to workspace 0


#  SECTION:=============================================================
#            SafeSaver Class
#  =====================================================================


class SafeSaver:
    """Enhanced saver with change detection and reduced disk writes"""

    last_backup_time = 0
    change_counter = 0
    last_saved_content_hash = {}  # Track content hashes to detect real changes

    @staticmethod
    def should_create_backup():
        if MAX_BACKUPS == 0:
            return False
        """Decide if we should create a backup based on time and changes"""
        current_time = time.time()
        time_since_backup = current_time - SafeSaver.last_backup_time

        # Only backup if enough time has passed AND we have significant changes
        return (
            time_since_backup >= BACKUP_INTERVAL
            and SafeSaver.change_counter >= MIN_CHANGES_FOR_BACKUP
        )

    @staticmethod
    def content_changed(note_name, content):
        """Check if content actually changed using hash comparison"""
        content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
        old_hash = SafeSaver.last_saved_content_hash.get(note_name)

        if old_hash != content_hash:
            SafeSaver.last_saved_content_hash[note_name] = content_hash
            SafeSaver.change_counter += 1
            return True
        return False

    @staticmethod
    def atomic_save(file_path, data, force_backup=False):
        """
        atomic save with intelligent backup creation
        Returns True if successful, False otherwise
        """
        try:
            # Check if we actually need to save by comparing data
            if os.path.exists(file_path) and not force_backup:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)

                    # Skip save if data hasn't changed (deep comparison)
                    if SafeSaver._data_equal(existing_data, data):
                        logger.debug("Data unchanged, skipping disk write")
                        return True
                except:
                    pass  # If we can't read existing data, proceed with save

            # Ensure directory exists
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)

            # Create backup only if conditions are met
            create_backup = MAX_BACKUPS != 0 and (
                force_backup
                or (os.path.exists(file_path) and SafeSaver.should_create_backup())
            )

            # create_backup = (force_backup or
            #                (os.path.exists(file_path) and SafeSaver.should_create_backup()))
            if create_backup:
                SafeSaver.create_backup(file_path)

            # Write to temporary file first
            temp_file = file_path + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=None, separators=(",", ":"))  # Compact JSON

            # Atomic rename
            os.rename(temp_file, file_path)

            logger.debug(f"Successfully saved to {file_path}")
            return True

        except Exception as e:
            logger.error(f"Error in save to {file_path}: {e}")

            # Clean up temp file
            temp_file = file_path + ".tmp"
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass

            return False

    @staticmethod
    def _data_equal(data1, data2):
        """Deep comparison of data structures"""
        try:
            return json.dumps(data1, sort_keys=True) == json.dumps(
                data2, sort_keys=True
            )
        except:
            return False

    @staticmethod
    def create_backup(file_path):
        """Create backup only when needed"""
        try:
            current_time = time.time()

            # Update counters
            SafeSaver.last_backup_time = current_time
            SafeSaver.change_counter = 0

            # Ensure backup directory exists
            os.makedirs(BACKUP_DIR, exist_ok=True)

            # Create timestamped backup
            timestamp = datetime.now().strftime(
                "%Y%m%d_%H%M"
            )  # Less granular timestamp
            file_name = Path(file_path).stem
            backup_file = os.path.join(BACKUP_DIR, f"{file_name}_{timestamp}.json")

            # Don't create duplicate backups with same timestamp
            if not os.path.exists(backup_file):
                shutil.copy2(file_path, backup_file)
                logger.debug(f"Created smart backup: {backup_file}")

                # Clean old backups
                SafeSaver.cleanup_old_backups()
            else:
                logger.debug("Backup with same timestamp exists, skipping")

        except Exception as e:
            logger.warning(f"Could not create smart backup: {e}")

    @staticmethod
    def cleanup_old_backups():
        """Keep only the most recent backups"""
        try:
            if not os.path.exists(BACKUP_DIR):
                return

            # Get all backup files
            backup_files = []
            for filename in os.listdir(BACKUP_DIR):
                if filename.endswith(".json"):
                    file_path = os.path.join(BACKUP_DIR, filename)
                    mtime = os.path.getmtime(file_path)
                    backup_files.append((mtime, file_path))

            # Sort by modification time (newest first)
            backup_files.sort(reverse=True)

            # Remove old backups
            for i, (mtime, file_path) in enumerate(backup_files):
                if i >= MAX_BACKUPS:
                    try:
                        os.unlink(file_path)
                        logger.debug(f"Removed old backup: {file_path}")
                    except:
                        pass

        except Exception as e:
            logger.warning(f"Error cleaning up backups: {e}")

    @staticmethod
    def load_with_fallback(file_path):
        """Load data with fallback to backups if main file is corrupted"""

        # Try main file first
        files_to_try = [file_path]

        # Add backup files as fallbacks
        if os.path.exists(BACKUP_DIR):
            backup_files = []
            for filename in os.listdir(BACKUP_DIR):
                if filename.endswith(".json"):
                    backup_path = os.path.join(BACKUP_DIR, filename)
                    mtime = os.path.getmtime(backup_path)
                    backup_files.append((mtime, backup_path))

            # Sort by modification time (newest first)
            backup_files.sort(reverse=True)
            files_to_try.extend([path for _, path in backup_files])

        # Try each file until one works
        for file_path_try in files_to_try:
            if os.path.exists(file_path_try):
                try:
                    with open(file_path_try, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    if file_path_try != file_path:
                        logger.warning(f"Loaded from backup: {file_path_try}")
                    else:
                        logger.info(f"Loaded state from {file_path_try}")

                    return data

                except Exception as e:
                    logger.warning(f"Could not load from {file_path_try}: {e}")
                    continue

        # If all files fail, return empty state
        logger.info("Starting with fresh state - no valid save files found")
        return {"notes": {}}


#  SECTION:=============================================================
#            Main App
#  =====================================================================


class StickyNotesApp(tk.Tk):
    """app with reduced disk writes"""

    def __init__(self):
        super().__init__()
        # Hide this window
        self.withdraw()
        self.app_state = {"notes": {}}
        self.save_after_id = None
        self.last_save_time = 0
        self.save_queue = []  # Queue saves to batch them
        self.batch_save_timer = None
        self.ui_font = None
        self.text_font = None
        # Load state from file with fallback
        self.load_state()

        # Set UI_FONT to all child widgets.
        if font_exists(UI_FONT[0]):
            self.ui_font = font.Font(family=UI_FONT[0], size=UI_FONT[1])
            self.option_add("*Font", self.ui_font)
        else:
            logger.error(f"Given UI font: {UI_FONT[0]} is not available.")

        # Set TEXT_FONT to all child Text widgets.
        if font_exists(TEXT_FONT[0]):
            self.ui_font = font.Font(family=TEXT_FONT[0], size=TEXT_FONT[1])
            self.option_add("*Text.font", self.ui_font)
        else:
            logger.error(f"Given text font: {TEXT_FONT[0]} is not available.")

        if self.app_state["notes"]:
            for note_name, state in self.app_state["notes"].items():
                self.open_note_window(note_name, state)
        else:
            self.open_note_window("New Note")

        self.protocol("WM_DELETE_WINDOW", self.close_all)

        # Auto-cleanup old backups on startup (only if backups enabled)
        if MAX_BACKUPS > 0:
            self.after(1000, SafeSaver.cleanup_old_backups)

    def open_note_window(self, note_name, state=None):
        if state is None:
            state = {}
        NoteWindow(master=self, app=self, note_name=note_name, state=state)

    def load_state(self):
        """Load state with fallback to backups"""
        try:
            self.app_state = SafeSaver.load_with_fallback(STATE_FILE)
            logger.info("State loaded successfully")
        except Exception as e:
            logger.error(f"Critical error loading state: {e}")
            self.app_state = {"notes": {}}

    def schedule_save(self, fast=False):
        """save scheduling with batching"""
        current_time = time.time()

        # Cancel existing timer
        if self.save_after_id:
            self.after_cancel(self.save_after_id)

        # Batch saves - if multiple saves are requested quickly, batch them
        if fast or (current_time - self.last_save_time) > 1.0:
            delay = FAST_SAVE_DELAY if fast else NORMAL_SAVE_DELAY
        else:
            # Recent save - use longer delay to batch changes
            delay = NORMAL_SAVE_DELAY * 2

        self.save_after_id = self.after(delay, self.save_state)

    def save_state(self):
        """state saving"""
        if self.save_after_id:
            self.after_cancel(self.save_after_id)
            self.save_after_id = None

        success = SafeSaver.atomic_save(STATE_FILE, self.app_state, force_backup=False)

        if success:
            self.last_save_time = time.time()
            logger.debug("App state saved successfully")
        else:
            logger.error("Failed to save app state")
            # Retry once after a delay
            self.after(
                5000,
                lambda: SafeSaver.atomic_save(
                    STATE_FILE, self.app_state, force_backup=True
                ),
            )

    def save_state_now(self):
        """Immediate save without debouncing"""
        return SafeSaver.atomic_save(STATE_FILE, self.app_state, force_backup=False)

    def close_all(self):
        """Close all windows and save state"""
        try:
            # Force save any pending changes
            for window in NoteWindow.open_windows.values():
                if window.is_modified:
                    window.save_note()

            # Save final state
            self.save_state_now()

            # Close all windows
            for win in list(NoteWindow.open_windows.values()):
                win.destroy()

            logger.info("Application closed successfully")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        finally:
            self.destroy()

    def show_all(self):
        """Show all windows"""
        for window in NoteWindow.open_windows.values():
            if window:
                window.lift()
        logger.info("Showed all notes")

    def hide_all(self):
        """hide all windows"""
        window: NoteWindow | None = None
        for window in NoteWindow.open_windows.values():
            if window:
                window.lower()
        logger.info("Hide all notes")


#  SECTION:=============================================================
#            Note Window
#  =====================================================================


class NoteWindow(tk.Toplevel):
    open_windows = {}

    def __init__(self, master, app, note_name, state):
        super().__init__(master)
        self.app = app
        # Not to appear window list.
        # self.attributes("-type", "toolbar")
        # self.overrideredirect(True)

        # self.wm_attributes("-type", "splash")
        self.wm_attributes("-type", "utility")

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.note_name = note_name

        # Enhanced change tracking
        self.save_after_id = None
        self.last_save_time = 0
        self.is_modified = False
        self.critical_save_pending = False
        self.last_content_length = len(state.get("content", ""))
        self.last_geometry = None
        self.geometry_change_threshold = MIN_GEOMETRY_CHANGE
        self.content_change_count = 0
        self.idle_timer_id = None
        # self.minsize(width=300, height=900)

        # Track when user was last active
        self.last_activity_time = time.time()

        # Load previous state of the app
        self.bg_color = state.get("bg_color", TEXT_BG_COLOR)
        self.fg_color = state.get("fg_color", TEXT_COLOR)

        # Font: load and initialize
        self.text_font_family = state.get("text_font_family", TEXT_FONT[0])
        self.text_font_size = state.get("text_font_size", TEXT_FONT[1])
        self.ui_font_family = state.get("ui_font_family", UI_FONT[0])
        self.ui_font_size = state.get("ui_font_size", UI_FONT[1])
        # Use this font reference to change font
        self.ui_shared_font = font.Font(
            family=self.ui_font_family, size=self.ui_font_size
        )
        # May separate emoji font from ui shared font
        self.emoji_font = self.ui_shared_font
        # Text is editable or not
        self.locked: bool = state.get("locked", False)

        # Set title
        self.title(f"myStickyNote - {self.note_name}")

        # Load the note data including workspace
        ws = get_current_workspace_number()
        self.workspace: str = state.get("workspace", str(ws))
        logger.debug(f"self.workspace: {self.workspace}, current_ws: {ws}")

        # text content
        content = state.get("content", "")
        # window geometry
        geometry = state.get("geometry")

        # Save geometry when <Configure> event occurs
        self.bind("<Configure>", self.on_geometry_change)

        # Save on focus out for additional safety
        self.bind("<FocusOut>", self.on_focus_out)

        NoteWindow.open_windows[self.note_name] = self

        self.schedule_save(fast=False)
        #  SECTION:=============================================================
        #            Bar, which shows note name and buttons
        #  =====================================================================

        # Tittle bar structure:
        # title_bar_frame ----------------------------
        # └ title_name_frame -----------buttons_frame-
        title_bar_frame = tk.Frame(self)
        title_bar_frame.pack(side=tk.TOP, fill=tk.X)
        # title_bar_frame.bind("<ButtonPress-1>", self.start_move)
        # title_bar_frame.bind("<B1-Motion>", self.do_move)

        # title_name_frame is used for moving note window
        # title_name_frame = tk.Frame(title_bar_frame, bg="gray")
        # title_name_frame.pack(side=tk.LEFT, fill=tk.X, expand=tk.TRUE)
        # title_name_frame.bind("<ButtonPress-1>", self.start_move)
        # title_name_frame.bind("<B1-Motion>", self.do_move)
        # title_name_frame.bind("<ButtonRelease-1>", self.finish_move)

        # Note name label on the left
        self.note_name_label = tk.Label(
            title_bar_frame, text=self.note_name, font=self.ui_shared_font
        )
        self.note_name_label.pack(side=tk.LEFT, padx=10)

        # Spacer frame to push buttons to right
        spacer = tk.Frame(title_bar_frame)
        spacer.pack(side=tk.LEFT, fill=tk.BOTH, expand=tk.TRUE)

        def bind_move_events(widget):
            widget.bind("<ButtonPress-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
            widget.bind("<ButtonRelease-1>", self.finish_move)

        bind_move_events(self.note_name_label)
        bind_move_events(spacer)

        # Buttons ----------------------------------------------------------------------
        # Frame to contain buttons aligned to right
        buttons_frame = tk.Frame(title_bar_frame)
        buttons_frame.pack(side="right")

        self.add_btn = tk.Button(
            buttons_frame, text="➕️", font=self.emoji_font, command=self.add_note
        )
        self.add_btn.pack(side="left")

        self.remove_btn = tk.Button(
            buttons_frame, text="➖️", font=self.emoji_font, command=self.remove_note
        )
        self.remove_btn.pack(side="left")

        self.save_btn = tk.Button(
            buttons_frame, text="💾", font=self.emoji_font, command=self.force_save
        )
        self.save_btn.pack(side="left")

        self.lock_btn = tk.Button(
            buttons_frame, text="🔒", font=self.emoji_font, command=self.toggle_lock
        )
        self.lock_btn.pack(side="left")

        # Workspace switcher ------------------------------------------------------------
        workspace_switcher_container = tk.Frame(buttons_frame, relief=tk.SOLID)
        workspace_switcher_container.pack(side=tk.LEFT, fill=tk.BOTH)

        # Dropdown label
        tk.Label(workspace_switcher_container, text="💼", font=self.emoji_font).pack(
            side="left"
        )
        #  Dropdown menu, to move to another workspace
        self.workspace_var = tk.StringVar()
        self.option_menu = ttk.Combobox(
            workspace_switcher_container,
            width=6,
            font=self.ui_shared_font,
            state="readonly",
        )
        self.option_menu.pack(side=tk.LEFT, fill=tk.BOTH, padx=3)
        # Bind selection event
        self.option_menu.bind("<<ComboboxSelected>>", self.on_workspace_selected)

        # Update workspace values by using the state from the setting file.
        update_workspace_options(self, self.workspace)

        # Setting button --------------------------------------------------------
        self.settings_btn = tk.Button(
            buttons_frame,
            text="⚙",
            font=self.emoji_font,
            command=self.open_settings,
        )
        self.settings_btn.pack(side="left")

        # Close button --------------------------------------------------------
        close_btn = tk.Button(
            buttons_frame, text="✖", font=self.emoji_font, command=self.close
        )
        close_btn.pack(side="left")

        #  SECTION:=============================================================
        #            Textbox
        #  =====================================================================

        self.text_box = tk.Text(
            self,
            wrap="word",
            bg=self.bg_color,
            fg=self.fg_color,
            font=(self.text_font_family, self.text_font_size),
            undo=True,
        )
        self.text_box.pack(side=tk.TOP, expand=tk.TRUE, fill=tk.BOTH)
        self.text_box.insert("1.0", content)
        self.text_box.bind("<<Modified>>", self.on_text_change)

        # Update font in the texbox
        self.update_font("text")

        # Bind events for activity tracking
        self.text_box.bind("<Key>", self.on_user_activity)
        self.text_box.bind("<Button>", self.on_user_activity)
        self.bind("<Motion>", self.on_user_activity)

        self.context_menu = self.set_context_menu(self.text_box)

        # Start idle detection
        self.check_idle_state()

        # For shortcut keys. Undo, redo.
        def safe_undo(text_widget):
            try:
                text_widget.edit_undo()
            except tk.TclError:
                pass  # Nothing to undo, ignore error

        def safe_redo(text_widget):
            try:
                text_widget.edit_redo()
            except tk.TclError:
                pass  # Nothing to redo, ignore error

        self.text_box.bind(
            "<Control-z>", lambda event: (safe_undo(self.text_box), "break")
        )
        self.text_box.bind(
            "<Control-y>", lambda event: (safe_redo(self.text_box), "break")
        )

        # Manual save shortcut
        self.text_box.bind("<Control-s>", lambda event: (self.force_save(), "break"))

        # Context menu in text_box

        # update lock_btn label by using the state from the setting file.
        # This function lock the text_box. So, placed here, not to the place lock button is written.
        self.update_lock_button()

        #  SECTION:=============================================================
        #            Sizegrip at the window bottom
        #  =====================================================================

        bottom_frame = tk.Frame(self)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        # Grip for resizing this window
        size_grip = ttk.Sizegrip(bottom_frame)
        size_grip.pack(side=tk.RIGHT)
        size_grip.bind("<B1-Motion>", self.resize)

        # Prevent container from shrinking below size grip size
        bottom_frame.pack_propagate(False)
        bottom_frame.config(height=size_grip.winfo_reqheight())

        #
        # To make this window too small, size_grip disappears.
        # Not so that define the self window minimum size.
        self.update_idletasks()  # Ensure geometry is calculated

        # Set minimum size of the window.
        self.minsize(
            # width
            title_bar_frame.winfo_reqwidth(),
            # height
            title_bar_frame.winfo_reqheight()
            + self.text_box.winfo_reqheight()
            + size_grip.winfo_reqheight(),
        )

        #  SECTION:=============================================================
        #            Settings after window is created
        #  =====================================================================

        # Restore window geometry
        if geometry:
            self.geometry(geometry)
        else:
            # Place the self window at the center of the screen
            win_width = self.winfo_width()
            win_height = self.winfo_height()
            screen_w = self.app.winfo_screenwidth()
            screen_h = self.app.winfo_screenheight()
            x = (screen_w // 2) - (win_width // 2)
            y = (screen_h // 2) - (win_height // 2)
            self.geometry(f"{win_width}x{win_height}+{x}+{y}")

        # After window is created and mapped, move it to the workspace
        # Delay to ensure window exists. If not, wmctrl throws error.
        self.after(500, self.move_to_workspace, self.workspace)

    #  SECTION:=============================================================
    #            Functions, Move and resize self window
    #  =====================================================================

    def start_move(self, event):
        self._offset_x = event.x
        self._offset_y = event.y
        # logger.debug("start:Move window")

    def do_move(self, event):
        # Change cursor to 'fleur' (commonly used for move/drag)
        self.configure(cursor="fleur")
        # x = self.winfo_pointerx() - self._offset_x
        # y = self.winfo_pointery() - self._offset_y
        # event.x or .y are bad. Flicker happens.
        x = event.x_root - self._offset_x
        y = event.y_root - self._offset_y
        self.geometry(f"+{x}+{y}")
        # logger.debug("end:Move window")

    def finish_move(self, event):
        # Restore cursor to default when done
        self.configure(cursor="")

    def resize(self, event):
        x = self.winfo_pointerx()
        y = self.winfo_pointery()
        geo = f"{x - self.winfo_rootx()}x{y - self.winfo_rooty()}+{self.winfo_rootx()}+{self.winfo_rooty()}"
        self.geometry(geo)

    #  SECTION:=============================================================
    #            Functions, Response for user activity and change detection
    #  =====================================================================

    def on_user_activity(self, event=None):
        """Track user activity for idle detection"""
        self.last_activity_time = time.time()

    def check_idle_state(self):
        """Check if user is idle and save if needed"""
        current_time = time.time()
        idle_time = current_time - self.last_activity_time

        # If user has been idle for 5+ seconds and there are unsaved changes
        if idle_time >= 5 and self.is_modified:
            logger.debug("User idle, performing save")
            self.schedule_save(fast=False, delay_ms=IDLE_SAVE_DELAY)

        # Check again in 5 seconds
        self.after(5000, self.check_idle_state)

    def on_text_change(self, event=None):
        """text change handler with smart detection"""
        if not self.text_box.edit_modified():
            return

        current_content = self.text_box.get("1.0", "end-1c")
        content_length = len(current_content)

        # Only trigger save if significant change
        length_diff = abs(content_length - self.last_content_length)

        if length_diff >= MIN_CONTENT_CHANGE:
            # Check if content actually changed (not just cursor movement)
            if SafeSaver.content_changed(self.note_name, current_content):
                self.is_modified = True
                self.content_change_count += 1
                self.last_content_length = content_length

                # Use longer delay for frequent changes
                delay = NORMAL_SAVE_DELAY
                if self.content_change_count > 10:  # Lots of rapid changes
                    delay = NORMAL_SAVE_DELAY * 2  # Even longer delay

                self.schedule_save(fast=False, delay_ms=delay)

        self.text_box.edit_modified(False)

    def on_geometry_change(self, event=None):
        """geometry change handler"""
        if event and event.widget != self:
            return

        current_geometry = self.geometry()

        if self.last_geometry is None:
            self.last_geometry = current_geometry
            return

        # Parse geometry strings to check for significant change
        try:

            def parse_geometry(geom_str):
                # Format: "widthxheight+x+y"
                size_part, pos_part = geom_str.split("+", 1)
                if "+" in pos_part:
                    x_pos, y_pos = pos_part.split("+", 1)
                else:
                    x_pos, y_pos = pos_part.split("-", 1)
                    y_pos = "-" + y_pos

                width, height = size_part.split("x")
                return int(width), int(height), int(x_pos), int(y_pos)

            curr_w, curr_h, curr_x, curr_y = parse_geometry(current_geometry)
            last_w, last_h, last_x, last_y = parse_geometry(self.last_geometry)

            # Check if change is significant enough
            width_diff = abs(curr_w - last_w)
            height_diff = abs(curr_h - last_h)
            x_diff = abs(curr_x - last_x)
            y_diff = abs(curr_y - last_y)

            max_diff = max(width_diff, height_diff, x_diff, y_diff)

            if max_diff >= self.geometry_change_threshold:
                self.last_geometry = current_geometry
                self.schedule_save(fast=False, delay_ms=GEOMETRY_SAVE_DELAY)

        except Exception as e:
            logger.debug(f"Geometry parsing error: {e}")
            # Fallback to simple string comparison
            if current_geometry != self.last_geometry:
                self.last_geometry = current_geometry
                self.schedule_save(fast=False, delay_ms=GEOMETRY_SAVE_DELAY)

    #  SECTION:=============================================================
    #            Functions, Update display
    #  =====================================================================

    def update_font(self, text_or_ui):
        if text_or_ui == "text":
            self.text_box.config(font=(self.text_font_family, self.text_font_size))
            logging.debug(
                f"after update_font, text: font_family:{self.text_font_family}, font_size: {self.text_font_size}"
            )
        elif text_or_ui == "ui":
            # Change all font in this object
            self.ui_shared_font.configure(
                family=self.ui_font_family, size=self.ui_font_size
            )
            logging.debug(
                f"after update_font, ui: font_family:{self.ui_font_family}, font_size: {self.ui_font_size}"
            )
            # Change text font
            self.update_font("text")
        else:
            logging.error(f"text_or_ui: {text_or_ui}. Use 'text' or 'ui'.")

    def update_lock_button(self):
        if self.locked:
            self.lock_btn.config(text="🔒️")
            self.text_box.config(state=tk.DISABLED)
        else:
            self.lock_btn.config(text="🔓️")
            self.text_box.config(state=tk.NORMAL)

    #  SECTION:=============================================================
    #            Functions, for events
    #  =====================================================================

    def on_focus_out(self, event=None):
        """Save when window loses focus for additional safety"""
        if self.is_modified:
            self.schedule_save(fast=True)

    def is_critical_change(self):
        """Determine if this is a critical change that needs fast saving"""
        return self.critical_save_pending

    def schedule_save(self, fast=False, delay_ms=None):
        """Schedule a save with appropriate timing"""
        if self.save_after_id:
            self.after_cancel(self.save_after_id)

        # Determine delay
        if delay_ms is not None:
            delay = delay_ms
        elif fast or self.is_critical_change():
            delay = FAST_SAVE_DELAY
        else:
            delay = NORMAL_SAVE_DELAY

        self.save_after_id = self.after(delay, self.save_note)

    #  SECTION:=============================================================
    #            Functions, for buttons
    #  =====================================================================

    def save_note(self):
        """save with change detection"""
        if self.save_after_id:
            self.after_cancel(self.save_after_id)
            self.save_after_id = None

        try:
            content = self.text_box.get("1.0", "end-1c")
            geometry = self.geometry()

            # Create new note data
            new_note_data = {
                "content": content,
                "bg_color": self.bg_color,
                "fg_color": self.fg_color,
                "text_font_family": self.text_font_family,
                "text_font_size": self.text_font_size,
                "ui_font_family": self.ui_font_family,
                "ui_font_size": self.ui_font_size,
                "geometry": geometry,
                "locked": self.locked,
                "workspace": self.workspace,
            }

            # Check if data actually changed
            old_note_data = self.app.app_state["notes"].get(self.note_name, {})

            if SafeSaver._data_equal(old_note_data, new_note_data):
                logger.debug(f"Note '{self.note_name}' data unchanged, skipping save")
                return

            # Update app state only if changed
            self.app.app_state["notes"][self.note_name] = new_note_data

            self.app.schedule_save()
            self.is_modified = False
            self.critical_save_pending = False
            self.last_save_time = time.time()
            self.content_change_count = 0  # Reset change counter

            logger.debug(f"Note '{self.note_name}' saved successfully")

        except Exception as e:
            logger.error(f"Error saving note '{self.note_name}': {e}")

    def force_save(self):
        """Force immediate save - called by save button or Ctrl+S"""
        self.critical_save_pending = True
        self.schedule_save(fast=True)

    def open_settings(self):
        SettingsWindow(self, self.app)

    def add_note(self):
        note_name = simpledialog.askstring("Add Note", "Enter note name:", parent=self)
        if (
            note_name
            and note_name not in NoteWindow.open_windows
            and note_name not in self.app.app_state["notes"]
        ):
            self.app.open_note_window(note_name)

    def remove_note(self):
        if messagebox.askyesno("Remove Note", f"Delete note '{self.note_name}'?"):
            if self.note_name in self.app.app_state["notes"]:
                del self.app.app_state["notes"][self.note_name]
            self.close()

    def close(self):
        # When the note window is the last window, alert.
        logger.debug(f"open window number: {len(self.open_windows)}")
        if len(self.open_windows) == 1:
            if not messagebox.askyesno("Close the last note", "Close the last note?"):
                return

        # Force save before closing
        if self.is_modified:
            self.save_note()

        if self.note_name in NoteWindow.open_windows:
            del NoteWindow.open_windows[self.note_name]
        self.destroy()
        if not NoteWindow.open_windows:
            self.app.save_state_now()
            self.app.destroy()
        else:
            self.app.schedule_save()

    def toggle_lock(self):
        self.locked = not self.locked
        self.critical_save_pending = True  # Lock state is critical
        self.update_lock_button()
        self.schedule_save(fast=True)

    def move_to_workspace(self, target_workspace_num: str):
        try:
            if target_workspace_num == "*":
                if self.workspace == "*":
                    return
                # Sticky window on all workspaces
                subprocess.run(
                    ["wmctrl", "-r", self.title(), "-b", "add,sticky"],
                    check=True,
                    timeout=5,
                )
            else:
                if self.workspace == "*":
                    subprocess.run(
                        ["wmctrl", "-r", self.title(), "-b", "remove,sticky"],
                        check=True,
                        timeout=5,
                    )

                subprocess.run(
                    ["wmctrl", "-r", self.title(), "-t", target_workspace_num],
                    check=True,
                    timeout=5,
                )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            FileNotFoundError,
        ):
            logger.error(
                f"Failed to move window '{self.note_name}' to workspace {target_workspace_num}"
            )

    def on_workspace_selected(self, event):
        selected = event.widget.get()
        logger.debug(f"selected: {selected}")
        new_ws_num = selected.split(":")[0]
        self.move_to_workspace(new_ws_num)
        update_workspace_options(self, new_ws_num)
        self.critical_save_pending = True  # Workspace change is critical
        self.schedule_save(fast=True)

    #  =====================================================================
    #            Functions: Context menu
    #  =====================================================================

    def show_context_menu(self, event):
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def set_context_menu(self, textarea):
        # --- context menu ---
        context_menu = tk.Menu(self, tearoff=0)
        context_menu.add_command(
            label="Cut", command=lambda: textarea.event_generate("<<Cut>>")
        )
        context_menu.add_command(
            label="Copy", command=lambda: textarea.event_generate("<<Copy>>")
        )
        context_menu.add_command(
            label="Paste", command=lambda: textarea.event_generate("<<Paste>>")
        )
        context_menu.add_separator()
        context_menu.add_command(
            label="Select All",
            command=lambda: textarea.tag_add("sel", "1.0", "end"),
        )

        # right click binding
        textarea.bind("<Button-3>", self.show_context_menu)  # Linux / Windows
        textarea.bind("<Button-2>", self.show_context_menu)  # some systems (optional)
        return context_menu


#  SECTION:=============================================================
#            Setting window
#  =====================================================================


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent: NoteWindow, app: StickyNotesApp):
        super().__init__(parent)
        self.title("Settings")
        self.parent = parent
        self.app = app
        self.ui_shared_font = self.parent.ui_shared_font
        self.workspace = self.parent.workspace

        self.geometry("800x600")
        # Set only the position relative to parent
        x = parent.winfo_x() + 50
        y = parent.winfo_y() + 50
        self.geometry("+{}+{}".format(x, y))

        #  SECTION:=============================================================
        #            Left: Note lists and general setting button
        #  =====================================================================
        left_frame = tk.Frame(self)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Left: list of notes
        tk.Label(left_frame, text="Select a note:", font=self.ui_shared_font).pack(
            anchor=tk.W
        )
        self.note_list = tk.Listbox(
            left_frame, exportselection=False, font=self.ui_shared_font
        )
        self.note_list.pack(fill=tk.BOTH, expand=tk.TRUE, pady=10)
        for note in app.app_state["notes"].keys():
            self.note_list.insert("end", note)
            self.note_list.bind("<<ListboxSelect>>", self.on_note_select)

        # Default selection: current note
        try:
            current_index = list(app.app_state["notes"].keys()).index(parent.note_name)
            self.note_list.selection_set(current_index)
        except ValueError:
            pass

        # Button for "general setting"
        tk.Button(
            left_frame, text="General Setting", command="", font=self.ui_shared_font
        ).pack(
            side=tk.BOTTOM,
        )
        #  SECTION:=============================================================
        #            Right: Settings for each note
        #  =====================================================================

        # Right: settings frame
        right_frame = tk.Frame(self)
        right_frame.pack(
            anchor=tk.N, side="left", fill=tk.BOTH, expand=tk.TRUE, padx=10, pady=10
        )

        # Rename note ---------------------------------------------------
        rename_frame = tk.Frame(right_frame)
        rename_frame.pack(fill=tk.X, padx=0, pady=10)
        tk.Label(rename_frame, font=self.ui_shared_font, text="Note Name:").pack(
            anchor=tk.W, side=tk.LEFT
        )
        tk.Button(
            rename_frame,
            text="Rename",
            font=self.ui_shared_font,
            command=self.rename_note,
        ).pack(side=tk.RIGHT)
        self.rename_entry = tk.Entry(rename_frame, font=self.ui_shared_font)
        self.rename_entry.pack(side=tk.RIGHT)
        self.rename_entry.insert(0, self.parent.note_name)

        # color settings ------------------------------------------------------
        # Background color with display
        color_frame = tk.Frame(right_frame, pady=10)
        color_frame.pack(fill=tk.X)
        bg_frame = tk.Frame(color_frame)
        bg_frame.pack(fill=tk.X)
        tk.Label(bg_frame, text="Background Color:", font=self.ui_shared_font).pack(
            anchor="w", side=tk.LEFT
        )
        tk.Button(
            bg_frame,
            text="Choose...",
            font=self.ui_shared_font,
            command=self.choose_bg_color,
        ).pack(side=tk.RIGHT)
        self.bg_color_display = tk.Label(
            bg_frame, width=3, bg=self.parent.bg_color, relief="sunken"
        )
        self.bg_color_display.pack(side=tk.RIGHT, padx=5)

        # Font color with display
        fg_frame = tk.Frame(color_frame)
        fg_frame.pack(fill=tk.X)
        tk.Label(fg_frame, text="Foreground Color:", font=self.ui_shared_font).pack(
            anchor="w", side=tk.LEFT
        )
        tk.Button(
            fg_frame,
            text="Choose...",
            font=self.ui_shared_font,
            command=self.choose_fg_color,
        ).pack(side=tk.RIGHT)
        self.fg_color_display = tk.Label(
            fg_frame, width=3, bg=self.parent.fg_color, relief="sunken"
        )
        self.fg_color_display.pack(side=tk.RIGHT, padx=5)

        # Frame: Font settings ------------------------------------------------------------
        font_frame = tk.Frame(right_frame)
        font_frame.pack(fill=tk.X, pady=10)
        # Frame: Text font
        t_font_frame = tk.Frame(font_frame)
        t_font_frame.pack(fill=tk.X)
        # label
        tk.Label(
            t_font_frame, text="Text Font:", font=self.ui_shared_font, anchor=tk.W
        ).pack(side=tk.LEFT)

        ## Font chooser
        tk.Button(
            t_font_frame,
            text="Choose...",
            font=self.ui_shared_font,
            command=lambda: self.choose_font("text"),
        ).pack(side=tk.RIGHT)

        ## Font label
        self.text_font_info_label = tk.Label(
            t_font_frame,
            text="",
            font=self.ui_shared_font,
        )
        self.text_font_info_label.pack(side=tk.RIGHT, padx=5)
        self.update_font_info(
            "text", self.parent.text_font_family, self.parent.text_font_size
        )

        # Frame: UI Font
        ui_font_frame = tk.Frame(font_frame)
        ui_font_frame.pack(fill=tk.X)
        # label
        tk.Label(
            ui_font_frame,
            text="UI Font:",
            font=self.ui_shared_font,
        ).pack(side=tk.LEFT)

        ## Font chooser
        tk.Button(
            ui_font_frame,
            text="Choose...",
            font=self.ui_shared_font,
            command=lambda: self.choose_font("ui"),
        ).pack(
            side=tk.RIGHT,
        )

        ## Font name
        self.ui_font_info_label = tk.Label(
            ui_font_frame,
            text="",
            font=self.ui_shared_font,
        )
        self.ui_font_info_label.pack(side=tk.RIGHT, padx=5)
        # Update label
        self.update_font_info(
            "ui", self.parent.ui_font_family, self.parent.ui_font_size
        )

        # Dropdown menu, to move to another workspace ------------------------------------
        workspace_switcher_container = tk.Frame(right_frame)
        workspace_switcher_container.pack(fill=tk.X, pady=10)
        tk.Label(
            workspace_switcher_container,
            text="Select workspace:",
            font=self.ui_shared_font,
        ).pack(side=tk.LEFT)
        self.workspace_var = tk.StringVar()
        self.option_menu = ttk.Combobox(
            workspace_switcher_container,
            width=8,
            font=self.ui_shared_font,
            state="readonly",
        )
        self.option_menu.pack(side=tk.RIGHT, fill=tk.X)
        update_workspace_options(self, self.parent.workspace)

        # Bind selection event
        self.option_menu.bind("<<ComboboxSelected>>", self.on_workspace_selected)

        # Backup management section (only show if backups are enabled) ------------------------
        if MAX_BACKUPS > 0:
            tk.Label(
                right_frame,
                text="Backup Management:",
                font=self.ui_shared_font,
            ).pack(anchor="w", pady=(20, 5))

            backup_frame = tk.Frame(right_frame)
            backup_frame.pack(fill="x")

            tk.Button(
                backup_frame,
                text="Create Backup Now",
                command=self.create_manual_backup,
            ).pack(side="left", padx=(0, 5))
            tk.Button(
                backup_frame,
                text="View Backups",
                command=self.view_backups,
                font=self.ui_shared_font,
            ).pack(side="left")
        else:
            tk.Label(
                right_frame,
                text="Backups: Disabled",
                font=self.ui_shared_font,
            ).pack(anchor="w", pady=(20, 5))

        # Close button ------------------------------------------------------------
        tk.Button(
            right_frame, text="Close", font=self.ui_shared_font, command=self.on_close
        ).pack(side=tk.BOTTOM, anchor=tk.SE)

    #  SECTION:=============================================================
    #            Functions
    #  =====================================================================

    def on_workspace_selected(self, event):
        self.parent.on_workspace_selected(event)
        logger.debug(f"self.parent.workspace: {self.parent.workspace}")
        update_workspace_options(self, self.parent.workspace)

    def update_font_info(self, text_or_ui, font_family, font_size):
        display_text = f"{shorten_text(font_family)}, {font_size}"
        if text_or_ui == "text":
            self.text_font_info_label.config(text=display_text)
        elif text_or_ui == "ui":
            self.ui_font_info_label.config(text=display_text)

    def on_note_select(self, event):
        selection = event.widget.curselection()
        if selection:
            note_name = self.note_list.get(selection[0])
            note_data = self.app.app_state["notes"].get(note_name)
            if note_data:
                self.rename_entry.delete(0, "end")
                self.rename_entry.insert(0, note_name)
                self.bg_color_display.config(
                    bg=note_data.get("bg_color", TEXT_BG_COLOR)
                )
                self.fg_color_display.config(bg=note_data.get("fg_color", TEXT_COLOR))
                font_family = note_data.get("text_font_family", UI_FONT[0])
                font_size = note_data.get("text_font_size", UI_FONT[1])
                self.update_font_info("text", font_family, font_size)

    def rename_note(self):
        old_name = self.parent.note_name
        new_name = self.rename_entry.get().strip()
        if new_name and new_name != old_name:
            if new_name in self.app.app_state["notes"]:
                messagebox.showerror("Error", "Note name already exists.")
                return

            # Update app state
            self.app.app_state["notes"][new_name] = self.app.app_state["notes"].pop(
                old_name
            )

            # Update window references
            if old_name in NoteWindow.open_windows:
                NoteWindow.open_windows[new_name] = NoteWindow.open_windows.pop(
                    old_name
                )

            # Update parent window
            self.parent.note_name = new_name
            self.parent.title(f"myStickyNote - {new_name}")
            self.parent.note_name_label.config(text=new_name)

            # Mark as critical change and schedule save
            self.parent.critical_save_pending = True
            self.app.schedule_save(fast=True)

            # Update list display
            idx = self.note_list.get(0, "end").index(old_name)
            self.note_list.delete(idx)
            self.note_list.insert(idx, new_name)
            self.note_list.selection_clear(0, "end")
            self.note_list.selection_set(idx)

    def choose_bg_color(self):
        color = colorchooser.askcolor(parent=self, title="Background Color")[1]
        if color:
            self.bg_color_display.config(bg=color)
            self.parent.bg_color = color
            self.parent.text_box.config(bg=color)
            self.app.app_state["notes"][self.parent.note_name]["bg_color"] = color
            self.parent.critical_save_pending = True
            self.app.schedule_save(fast=True)

    def choose_fg_color(self):
        color = colorchooser.askcolor(parent=self, title="Foreground Color")[1]
        if color:
            self.fg_color_display.config(bg=color)
            self.parent.fg_color = color
            self.parent.text_box.config(fg=color)
            self.app.app_state["notes"][self.parent.note_name]["fg_color"] = color
            self.parent.critical_save_pending = True
            self.app.schedule_save(fast=True)

    def choose_font(self, text_or_ui):
        title: str = "Text Font" if text_or_ui == "text" else "UI Font"
        font_dict = ask_font(self, title=title)
        if font_dict:
            family = font_dict.get("family", TEXT_FONT[0])
            size = font_dict.get("size", TEXT_FONT[1])
            weight = font_dict.get("weight", "normal")
            slant = font_dict.get("slant", "roman")
            style = ""
            if weight == "bold":
                style += "bold "
            if slant == "italic":
                style += "italic"

            if text_or_ui == "text":
                font_family_key = "text_font_family"
                font_size_key = "text_font_size"
                self.parent.text_font_family = family
                self.parent.text_font_size = size
            elif text_or_ui == "ui":
                font_family_key = "ui_font_family"
                font_size_key = "ui_font_size"
                self.parent.ui_font_family = family
                self.parent.ui_font_size = size
            else:
                logging.error(f"text_or_ui: {text_or_ui}. Use 'text' or 'ui'.")
                raise ValueError

            self.parent.update_font(text_or_ui)
            self.update_font_info(text_or_ui, family, size)
            self.app.app_state["notes"][self.parent.note_name][font_family_key] = family
            self.app.app_state["notes"][self.parent.note_name][font_size_key] = size
            self.parent.critical_save_pending = True
            self.app.schedule_save(fast=True)

    def on_close(self):
        self.destroy()
        if self.parent:
            # Force focus back to parent after destroying child
            self.parent.focus_force()
            self.parent.lift()

    def create_manual_backup(self):
        """Create a manual backup immediately"""
        if MAX_BACKUPS <= 0:
            messagebox.showinfo(
                "Backups Disabled", "Backup feature is disabled (MAX_BACKUPS = 0)"
            )
            return

        try:
            # Force save current state first
            self.app.save_state_now()

            # Create backup
            SafeSaver.create_backup(STATE_FILE)
            messagebox.showinfo(
                "Backup Created", f"Backup created successfully in {BACKUP_DIR}/"
            )
        except Exception as e:
            logger.error(f"Error creating manual backup: {e}")
            messagebox.showerror("Backup Error", f"Could not create backup: {e}")

    def view_backups(self):
        """Show backup management window"""
        if MAX_BACKUPS <= 0:
            messagebox.showinfo(
                "Backups Disabled", "Backup feature is disabled (MAX_BACKUPS = 0)"
            )
            return
        BackupManagerWindow(self, self.app)


#  SECTION:=============================================================
#            Backup Manager Window
#  =====================================================================


class BackupManagerWindow(tk.Toplevel):
    def __init__(self, parent: SettingsWindow, app: StickyNotesApp):
        super().__init__(parent)
        self.title("Backup Manager")
        self.parent = parent
        self.app = app
        self.geometry("600x400")

        # Main frame
        main_frame = tk.Frame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Title
        tk.Label(
            main_frame, text="Available Backups", font=("TkDefaultFont", 12, "bold")
        ).pack(anchor="w")

        # Listbox with scrollbar for backups
        list_frame = tk.Frame(main_frame)
        list_frame.pack(fill="both", expand=True, pady=10)

        self.backup_listbox = tk.Listbox(list_frame)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical")
        self.backup_listbox.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.backup_listbox.yview)

        self.backup_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Button frame
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill="x", pady=10)

        tk.Button(
            button_frame, text="Refresh List", command=self.refresh_backup_list
        ).pack(side="left", padx=(0, 5))
        tk.Button(
            button_frame, text="Restore Selected", command=self.restore_backup
        ).pack(side="left", padx=(0, 5))
        tk.Button(
            button_frame, text="Delete Selected", command=self.delete_backup
        ).pack(side="left", padx=(0, 5))
        tk.Button(
            button_frame, text="Open Backup Folder", command=self.open_backup_folder
        ).pack(side="left", padx=(0, 5))

        # Info label
        self.info_label = tk.Label(main_frame, text="", justify="left")
        self.info_label.pack(anchor="w", pady=5)

        # Close button
        tk.Button(main_frame, text="Close", command=self.destroy).pack(pady=10)

        # Populate the list
        self.refresh_backup_list()

        # Bind selection event
        self.backup_listbox.bind("<<ListboxSelect>>", self.on_backup_select)

    def refresh_backup_list(self):
        """Refresh the list of available backups"""
        self.backup_listbox.delete(0, tk.END)
        self.backup_files = []

        if not os.path.exists(BACKUP_DIR):
            self.info_label.config(text="No backup directory found.")
            return

        try:
            # Get all backup files
            backup_files = []
            for filename in os.listdir(BACKUP_DIR):
                if filename.endswith(".json"):
                    file_path = os.path.join(BACKUP_DIR, filename)
                    mtime = os.path.getmtime(file_path)
                    size = os.path.getsize(file_path)
                    backup_files.append((mtime, filename, file_path, size))

            # Sort by modification time (newest first)
            backup_files.sort(reverse=True)

            for mtime, filename, file_path, size in backup_files:
                # Format the display string
                mod_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                size_kb = size / 1024
                display_text = f"{filename} - {mod_time} ({size_kb:.1f} KB)"

                self.backup_listbox.insert(tk.END, display_text)
                self.backup_files.append(file_path)

            self.info_label.config(text=f"Found {len(backup_files)} backup files.")

        except Exception as e:
            logger.error(f"Error refreshing backup list: {e}")
            self.info_label.config(text=f"Error reading backups: {e}")

    def on_backup_select(self, event):
        """Handle backup selection"""
        selection = self.backup_listbox.curselection()
        if selection:
            file_path = self.backup_files[selection[0]]
            try:
                # Show some info about the selected backup
                stat = os.stat(file_path)
                mod_time = datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                size_kb = stat.st_size / 1024

                # Try to load and show note count
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                note_count = len(data.get("notes", {}))

                info_text = f"Selected: {os.path.basename(file_path)}\n"
                info_text += f"Modified: {mod_time}\n"
                info_text += f"Size: {size_kb:.1f} KB\n"
                info_text += f"Notes: {note_count}"

                self.info_label.config(text=info_text)

            except Exception as e:
                self.info_label.config(text=f"Error reading backup info: {e}")

    def restore_backup(self):
        """Restore the selected backup"""
        selection = self.backup_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a backup to restore.")
            return

        file_path = self.backup_files[selection[0]]
        filename = os.path.basename(file_path)

        # Confirm restoration
        if not messagebox.askyesno(
            "Confirm Restore",
            f"Restore from backup '{filename}'?\n\n"
            "This will replace all current notes. "
            "Current state will be backed up first.",
        ):
            return

        try:
            # Create backup of current state first
            self.app.save_state_now()
            SafeSaver.create_backup(STATE_FILE)

            # Close all current windows
            for window in list(NoteWindow.open_windows.values()):
                window.destroy()
            NoteWindow.open_windows.clear()

            # Load the backup
            with open(file_path, "r", encoding="utf-8") as f:
                backup_data = json.load(f)

            # Replace app state
            self.app.app_state = backup_data

            # Save the restored state
            self.app.save_state_now()

            # Reopen windows
            if self.app.app_state["notes"]:
                for note_name, state in self.app.app_state["notes"].items():
                    self.app.open_note_window(note_name, state)
            else:
                self.app.open_note_window("New Note")

            messagebox.showinfo(
                "Restore Complete", f"Successfully restored from '{filename}'"
            )
            self.destroy()

        except Exception as e:
            logger.error(f"Error restoring backup: {e}")
            messagebox.showerror("Restore Error", f"Could not restore backup: {e}")

    def delete_backup(self):
        """Delete the selected backup"""
        selection = self.backup_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a backup to delete.")
            return

        file_path = self.backup_files[selection[0]]
        filename = os.path.basename(file_path)

        # Confirm deletion
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Delete backup '{filename}'?\n\nThis action cannot be undone.",
        ):
            return

        try:
            os.unlink(file_path)
            messagebox.showinfo("Delete Complete", f"Backup '{filename}' deleted.")
            self.refresh_backup_list()

        except Exception as e:
            logger.error(f"Error deleting backup: {e}")
            messagebox.showerror("Delete Error", f"Could not delete backup: {e}")

    def open_backup_folder(self):
        """Open the backup folder in file manager"""
        try:
            if os.path.exists(BACKUP_DIR):
                # Try different commands based on the system
                import platform

                system = platform.system()

                if system == "Linux":
                    subprocess.run(["xdg-open", BACKUP_DIR])
                elif system == "Darwin":  # macOS
                    subprocess.run(["open", BACKUP_DIR])
                elif system == "Windows":
                    subprocess.run(["explorer", BACKUP_DIR])
                else:
                    messagebox.showinfo(
                        "Backup Folder", f"Backup folder: {os.path.abspath(BACKUP_DIR)}"
                    )
            else:
                messagebox.showwarning(
                    "Folder Not Found", "Backup folder does not exist yet."
                )

        except Exception as e:
            logger.error(f"Error opening backup folder: {e}")
            messagebox.showerror("Error", f"Could not open backup folder: {e}")


#  SECTION:=============================================================
#            Functions, helper 2
#  =====================================================================


def generate_workspace_options(current_ws_num) -> tuple[str, list[str]]:
    """Generate label and list of workspace options used for moving betwee nworkspace.

    label: "{current workspace number}:{current workspace name}
    options: dict that contains strings of "{workspace number}:{workspace name}"
        from all the current workspace without the label string.
    """
    current_workspaces = get_all_current_workspaces()
    current_workspaces.append({"number": "*", "name": "*", "is_current": False})
    wss_num_name_without_new_current: list[str] = []
    ws_num_name_new_current: str = ""

    for ws in current_workspaces:
        ws_num_name = f"{str(ws['number'])}:{ws['name']}"
        if str(ws["number"]) != current_ws_num:
            wss_num_name_without_new_current.append(ws_num_name)
        else:
            ws_num_name_new_current = ws_num_name

    return (ws_num_name_new_current, wss_num_name_without_new_current)


def update_workspace_options(window: SettingsWindow | NoteWindow, current_ws_num: str):
    # Generate array that contains ---- workspace number:workspace name ---- for options
    label, options = generate_workspace_options(current_ws_num)
    window.workspace_var.set(label)
    logger.debug(f"new_ws_num:{current_ws_num}, options:{options}")
    window.option_menu.config(values=options)
    window.option_menu.config(textvariable=window.workspace_var)
    window.workspace = current_ws_num


if __name__ == "__main__":
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
    #            Main Loop
    #  =====================================================================

    try:
        app = StickyNotesApp()
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
