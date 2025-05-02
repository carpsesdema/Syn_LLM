
import logging
import os
import sys
from typing import Optional, List, Dict, Any
import datetime

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QApplication, QMessageBox, QFileDialog, QDialog, QLabel,
    QStyle # Added QStyle back for standard icons
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer, QSize, QEvent
from PyQt6.QtGui import QFont, QIcon, QMovie, QCloseEvent, QShortcut, QKeyEvent, QKeySequence

# --- Local Imports ---
try:
    from core.chat_manager import ChatManager
    from core.models import ChatMessage, SYSTEM_ROLE, ERROR_ROLE, MODEL_ROLE
    from ui.left_panel import LeftControlPanel
    # Updated import for ChatDisplayArea
    from ui.chat_display_area import ChatDisplayArea
    from ui.dialogs import CodeViewerWindow, EditPersonalityDialog, SessionManagerDialog, RAGViewerDialog
    # ChatBubbleWidget is no longer used directly here
    # from ui.widgets import ChatBubbleWidget
    from ui.chat_input_bar import ChatInputBar
    from utils import constants
    # Import the new model if needed directly (though usually accessed via display_area)
    from ui.chat_list_model import ChatListModel
except ImportError as e:
     logging.critical(f"Import error in main_window.py: {e}", exc_info=True)
     try:
         _dummy_app = QApplication.instance() or QApplication(sys.argv)
         QMessageBox.critical(None, "Import Error", f"Failed to import core components:\n{e}\nCheck installation and PYTHONPATH.")
     except Exception: pass
     sys.exit(1)


logger = logging.getLogger(__name__)

class MainWindow(QWidget):
    """
    Main application window (GUI Layer).
    Connects UI elements to the ChatManager and updates display based on its signals.
    Uses Model/View architecture for chat display.
    """

    def __init__(self, chat_manager: ChatManager, app_base_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        logger.info("MainWindow initializing...")
        if not isinstance(chat_manager, ChatManager):
             raise TypeError("MainWindow requires a valid ChatManager instance.")
        self.chat_manager = chat_manager
        self.app_base_path = app_base_path

        # --- Initialize UI Elements ---
        self.left_panel: Optional[LeftControlPanel] = None
        self.chat_display_area: Optional[ChatDisplayArea] = None
        self.status_label: Optional[QLabel] = None
        self.chat_input_bar: Optional[ChatInputBar] = None
        self._status_clear_timer: Optional[QTimer] = None

        # --- Access the Model (convenience reference) ---
        # self.chat_list_model: Optional[ChatListModel] = None # Set after display_area init

        # --- Initialize Dialogs (created on demand) ---
        self.code_viewer_window: Optional[CodeViewerWindow] = None
        self.session_manager_dialog: Optional[SessionManagerDialog] = None
        self.rag_viewer_dialog: Optional[RAGViewerDialog] = None

        # --- UI Setup ---
        self._init_ui()
        # --- Get reference to the model AFTER UI init ---
        # self.chat_list_model = self.chat_display_area.get_model() if self.chat_display_area else None
        # if not self.chat_list_model:
        #      logger.critical("Failed to get ChatListModel reference from ChatDisplayArea!")
             # Handle critical error - maybe quit?
        # -------------------------------------------
        self._apply_styles()
        self._connect_signals()

        # Set Window Icon (same as before)
        try:
            app_icon_path = os.path.join(constants.ASSETS_PATH, "Synchat.ico")
            logger.debug(f"Attempting to load window icon from: {app_icon_path}")
            if os.path.exists(app_icon_path):
                self.setWindowIcon(QIcon(app_icon_path))
                logger.info(f"Window icon set from: {app_icon_path}")
            else:
                logger.warning(f"App icon not found: {app_icon_path}")
                std_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
                if not std_icon.isNull(): self.setWindowIcon(std_icon)
        except Exception as e:
            logger.error(f"Error setting window icon: {e}")
            try: # Nested try for fallback icon
                std_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
                if not std_icon.isNull(): self.setWindowIcon(std_icon)
            except Exception as e_fb: logger.error(f"Error setting fallback icon: {e_fb}")


        self.update_window_title()
        logger.info("MainWindow initialized.")

    def _init_ui(self):
        """Sets up the main UI layout and widgets."""
        # This part remains largely the same structure
        logger.debug("MainWindow: Initializing UI widgets and layout.")
        main_hbox_layout = QHBoxLayout(self)
        main_hbox_layout.setContentsMargins(0, 0, 0, 0)
        main_hbox_layout.setSpacing(0)

        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_splitter.setObjectName("MainSplitter")
        main_splitter.setHandleWidth(1)

        # Left Panel
        self.left_panel = LeftControlPanel(self)
        self.left_panel.setObjectName("LeftPanel")

        # Right Panel Container
        right_panel_widget = QWidget(self)
        right_panel_widget.setObjectName("RightPanelContainer")
        right_panel_layout = QVBoxLayout(right_panel_widget)
        right_panel_layout.setContentsMargins(5, 5, 5, 5)
        right_panel_layout.setSpacing(5) # Spacing between elements

        # Chat Display Area (Now uses QListView internally)
        self.chat_display_area = ChatDisplayArea(self)
        self.chat_display_area.setObjectName("MainChatDisplayArea")

        # ChatInputBar
        self.chat_input_bar = ChatInputBar(self)

        # Status Bar (same as before)
        status_bar_widget = QWidget(self)
        status_bar_widget.setObjectName("StatusBarWidget")
        status_bar_layout = QHBoxLayout(status_bar_widget)
        status_bar_layout.setContentsMargins(5, 2, 5, 2)
        status_bar_layout.setSpacing(5)
        self.status_label = QLabel("Status: Initializing...", self)
        status_label_font = QFont(constants.CHAT_FONT_FAMILY, constants.CHAT_FONT_SIZE - 1)
        self.status_label.setFont(status_label_font)
        self.status_label.setObjectName("StatusLabel")
        status_bar_layout.addWidget(self.status_label)
        status_bar_layout.addStretch(1)

        # Assemble Right Panel
        right_panel_layout.addWidget(self.chat_display_area, 1) # Chat display stretches
        right_panel_layout.addWidget(self.chat_input_bar)
        right_panel_layout.addWidget(status_bar_widget) # Status bar at the bottom

        # Assemble Splitter (same as before)
        main_splitter.addWidget(self.left_panel)
        main_splitter.addWidget(right_panel_widget)
        main_splitter.setSizes([250, 750])
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        self.left_panel.setMinimumWidth(200)
        right_panel_widget.setMinimumWidth(400)

        # Final Layout
        main_hbox_layout.addWidget(main_splitter)
        self.setLayout(main_hbox_layout)
        logger.debug("MainWindow: UI Initialization complete.")

    def _apply_styles(self):
        """Loads and applies the QSS stylesheet."""
        # Logic remains the same, but QSS rules might need changes later
        stylesheet = ""
        applied_main_path = "None"
        applied_bubble_path = "None"
        logger.debug("Applying styles...")
        try:
            main_style_path = None
            for path_to_check in constants.STYLE_PATHS_TO_CHECK:
                if os.path.exists(path_to_check):
                    main_style_path = path_to_check
                    break
            if main_style_path:
                logger.info(f"Loading main stylesheet from: {main_style_path}")
                with open(main_style_path, "r", encoding="utf-8") as f: stylesheet += f.read() + "\n"
                applied_main_path = main_style_path
            else: logger.warning(f"Main stylesheet ({constants.STYLESHEET_FILENAME}) not found in checked paths: {constants.STYLE_PATHS_TO_CHECK}")

            # --- Bubble style is now less relevant for the container, more for HTML content ---
            bubble_style_path = constants.BUBBLE_STYLESHEET_PATH
            if os.path.exists(bubble_style_path):
                logger.info(f"Loading bubble/HTML content stylesheet from: {bubble_style_path}")
                with open(bubble_style_path, "r", encoding="utf-8") as f: stylesheet += f.read()
                applied_bubble_path = bubble_style_path
            else: logger.warning(f"Bubble/HTML stylesheet ({constants.BUBBLE_STYLESHEET_FILENAME}) not found at: {bubble_style_path}")
            # ---

            if stylesheet:
                self.setStyleSheet(stylesheet)
                logger.info(f"Styles applied. Main: '{os.path.basename(applied_main_path)}', Bubble/HTML: '{os.path.basename(applied_bubble_path)}'")
            else:
                 logger.error("No stylesheets found or loaded. UI will lack custom styling.")
                 self.setStyleSheet("QWidget { background-color: #282c34; color: #abb2bf; font-size: 9pt; } QPushButton { background-color: #3e4451; padding: 5px; } QLineEdit, QTextEdit { background-color: #21252b; border: 1px solid #3e4451; }")
        except Exception as e:
            logger.exception(f"Error applying stylesheet(s): {e}")
            self.setStyleSheet("QWidget { background-color: #333; color: #EEE; }") # Minimal fallback

    def _connect_signals(self):
        """Connects UI element signals and ChatManager signals."""
        logger.debug("MainWindow: Connecting signals...")
        if not all([self.chat_manager, self.chat_input_bar, self.left_panel, self.chat_display_area]):
             logger.critical("Cannot connect signals: One or more required UI components are None.")
             QMessageBox.critical(self, "Initialization Error", "Critical UI components failed to initialize. Application cannot continue.")
             QApplication.quit()
             return

        # --- Connect UI actions to ChatManager methods or MainWindow slots ---
        # These generally remain the same
        try:
             self.chat_input_bar.sendMessageRequested.connect(self._handle_send_action)
             self.left_panel.newSessionClicked.connect(self.chat_manager.start_new_chat)
             self.left_panel.manageSessionsClicked.connect(self._show_session_manager)
             self.left_panel.uploadFileClicked.connect(self._trigger_file_upload)
             self.left_panel.uploadDirectoryClicked.connect(self._trigger_dir_upload)
             self.left_panel.editPersonalityClicked.connect(self._show_personality_editor)
             self.left_panel.viewCodeBlocksClicked.connect(self._show_code_viewer)
             self.left_panel.viewRagContentClicked.connect(self._show_rag_viewer)
             self.left_panel.modelSelected.connect(self.chat_manager.set_model)
        except Exception as e: logger.exception(f"Error connecting UI signals to ChatManager/MainWindow: {e}")

        # --- Connect ChatManager signals to MainWindow slots ---
        # These connections remain, but the *slots* will now interact with the model
        try:
            self.chat_manager.history_changed.connect(self._handle_history_changed)
            self.chat_manager.new_message_added.connect(self._handle_new_message) # Slot implementation changes
            self.chat_manager.status_update.connect(self.update_status)
            self.chat_manager.error_occurred.connect(self._handle_error)
            self.chat_manager.busy_state_changed.connect(self._handle_busy_state)
            self.chat_manager.busy_state_changed.connect(self.chat_input_bar.handle_busy_state)
            self.chat_manager.config_state_changed.connect(self._handle_config_state)
            self.chat_manager.stream_started.connect(self._handle_stream_started) # Slot implementation changes
            self.chat_manager.stream_chunk_received.connect(self._handle_stream_chunk) # Slot implementation changes
            self.chat_manager.stream_finished.connect(self._handle_stream_finished) # Slot implementation changes
        except Exception as e: logger.exception(f"Error connecting ChatManager signals to MainWindow: {e}")

        # --- Keyboard Shortcuts ---
        # Remain the same
        try:
            QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self.chat_manager.start_new_chat)
            QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self._show_session_manager)
            QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._trigger_save_session)
            QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(self._trigger_save_as_session)
            QShortcut(QKeySequence("Ctrl+U"), self).activated.connect(self._trigger_file_upload)
            QShortcut(QKeySequence("Ctrl+Shift+U"), self).activated.connect(self._trigger_dir_upload)
            QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._show_personality_editor)
            QShortcut(QKeySequence("Ctrl+B"), self).activated.connect(self._show_code_viewer)
            QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self._show_rag_viewer)
        except Exception as e: logger.error(f"Error setting shortcuts: {e}")

        logger.debug("MainWindow: Signal connections complete.")

    # --- Slots for ChatManager Signals ---

    @pyqtSlot(list)
    def _handle_history_changed(self, history: List[ChatMessage]):
        """Loads history into the chat model."""
        logger.debug(f"Slot: Handling history changed (count: {len(history)})")
        if self.chat_display_area:
            self.chat_display_area.load_history_into_model(history) # Call new method
            self._rescan_history_for_code_blocks(history) # Rescan still needed for viewer
        else:
            logger.error("Cannot handle history change: chat_display_area is None.")
        self.update_window_title()

    @pyqtSlot(object) # ChatMessage object
    def _handle_new_message(self, message: ChatMessage):
        """Adds a single, complete message to the chat model."""
        logger.info(f"SLOT _handle_new_message: Received message for role '{message.role}'. Relaying to display area model...")
        if self.chat_display_area:
            try:
                # Add message to the *model* via the display area's method
                self.chat_display_area.add_message_to_model(message)
                logger.info(f"  add_message_to_model called successfully for role '{message.role}'.")
                # Scan non-streaming model messages for code blocks
                if message.role == MODEL_ROLE and (message.metadata is None or not message.metadata.get("is_streaming", False)):
                     self._scan_message_for_code_blocks(message)
            except Exception as e:
                logger.exception(f"  ERROR occurred within chat_display_area.add_message_to_model for role {message.role}")
                self.update_status(f"Error adding message: {e}", "#e06c75", True, 5000)
        else:
             logger.error("  CRITICAL: chat_display_area is None in _handle_new_message. Cannot add message to model.")
        # Update RAG button if needed (remains same)
        if message.role == SYSTEM_ROLE and "RAG" in message.text:
             self._update_rag_button_state()

    @pyqtSlot(str, bool)
    def _handle_error(self, error_message: str, is_critical: bool):
        """Handles errors reported by ChatManager."""
        logger.error(f"Slot: Handling error signal: '{error_message}', Critical: {is_critical}")
        # Check if the model's last message was streaming and potentially finalize/remove it?
        # This logic might be complex. For now, just display the error.
        # if self.chat_display_area and self.chat_display_area.get_model():
        #    model = self.chat_display_area.get_model()
        #    # Check model's internal state if needed...
        self.update_status(f"Error: {error_message}", "#e06c75", True, 8000)
        if is_critical or any(kw in error_message for kw in ["API", "Config", "Connection", "Fatal", "Critical"]):
            QMessageBox.warning(self, "Application Error" if is_critical else "Warning", error_message)

    @pyqtSlot(bool)
    def _handle_busy_state(self, is_busy: bool):
        """Updates UI elements based on busy state."""
        # This remains the same
        logger.debug(f"Slot: Handling busy state changed (MainWindow general UI): {is_busy}")
        api_ready = self.chat_manager.is_api_ready()
        if self.left_panel:
            self.left_panel.set_enabled_state(enabled=api_ready, is_busy=is_busy)

    @pyqtSlot(str, bool)
    def _handle_config_state(self, model_name: str, personality_active: bool):
        """Updates UI based on configuration changes."""
        # This remains the same
        logger.debug(f"Slot: Handling config state change. Model: {model_name}, Pers Active: {personality_active}")
        if self.left_panel:
             self.left_panel.update_model_selection(model_name)
             self.left_panel.update_personality_tooltip(active=personality_active)
             self._update_rag_button_state()
        self.update_window_title()

    # --- Slots for Streaming Signals ---
    @pyqtSlot(str) # role
    def _handle_stream_started(self, role: str):
        """Starts a streaming message in the model."""
        logger.info(f"SLOT _handle_stream_started: Received for role '{role}'. Relaying to display area model...")
        if self.chat_display_area:
            try:
                # Create initial message (can be empty) and pass to model
                initial_message = ChatMessage(role=role, parts=[""]) # Start with empty text part
                self.chat_display_area.start_streaming_in_model(initial_message)
                logger.info(f"  start_streaming_in_model called successfully for role '{role}'.")
            except Exception as e:
                logger.exception(f"  ERROR occurred within chat_display_area.start_streaming_in_model for role {role}")
                self.update_status(f"Error starting stream: {e}", "#e06c75", True, 5000)
        else:
            logger.error("  CRITICAL: chat_display_area is None in _handle_stream_started. Cannot start streaming.")

    @pyqtSlot(str) # chunk
    def _handle_stream_chunk(self, chunk: str):
        """Appends a stream chunk to the model's last message."""
        # No check/logging here for performance during stream
        if self.chat_display_area:
            self.chat_display_area.append_stream_chunk_to_model(chunk) # Call new method
        # else: # Avoid logging error on every chunk if display area is missing
        #     pass

    @pyqtSlot()
    def _handle_stream_finished(self):
        """Finalizes the streaming message in the model."""
        logger.info("SLOT _handle_stream_finished: Received. Relaying to display area model...")
        if self.chat_display_area:
             try:
                 self.chat_display_area.finalize_stream_in_model() # Call new method
                 logger.info("  finalize_stream_in_model called successfully.")
                 # Scan the finalized message content for code blocks
                 # Need to get the message from the *model* now
                 model = self.chat_display_area.get_model()
                 if model and model.rowCount() > 0:
                     last_msg = model.getMessage(model.rowCount() - 1)
                     if last_msg and last_msg.role == MODEL_ROLE:
                          self._scan_message_for_code_blocks(last_msg)
                          logger.debug("  Scanned final streamed message for code blocks.")
             except Exception as e:
                 logger.exception("  ERROR occurred within chat_display_area.finalize_stream_in_model")
                 self.update_status(f"Error finalizing stream: {e}", "#e06c75", True, 5000)
        else:
             logger.error("  CRITICAL: chat_display_area is None in _handle_stream_finished. Cannot finalize stream.")

    # --- Send Action ---
    @pyqtSlot(str, list)
    def _handle_send_action(self, text_to_send: str, image_data: List[Dict[str, Any]]):
        """Handles the send action from the input bar."""
        # This remains the same
        if not text_to_send.strip() and not image_data:
            logger.warning("Send action triggered with no text or images.")
            return
        if self.chat_input_bar:
             QTimer.singleShot(10, self.chat_input_bar.set_focus)
        logger.info(f"Slot: Handling send action (Text: {bool(text_to_send)}, Images: {len(image_data)}).")
        try:
            logger.debug("  Calling chat_manager.process_user_message")
            self.chat_manager.process_user_message(text_to_send, image_data)
            logger.debug("  chat_manager.process_user_message call initiated.")
        except Exception as e:
             logger.exception("  ERROR calling chat_manager.process_user_message")
             self.update_status(f"Error sending message: {e}", "#e06c75", True, 5000)

    # --- Other Slots (_show_*, _trigger_*) ---
    # These remain the same, as they interact with ChatManager or show dialogs
    @pyqtSlot()
    def _show_session_manager(self):
        logger.debug("Manage sessions action triggered.")
        if getattr(self.chat_manager, '_is_busy', False):
             self.update_status("Cannot manage sessions while AI is busy.", "#e5c07b", True, 3000); return
        try:
            if self.session_manager_dialog is None: self.session_manager_dialog = SessionManagerDialog(self.chat_manager, self)
            self.session_manager_dialog.refresh_list()
            result = self.session_manager_dialog.exec()
            logger.debug(f"SessionManagerDialog closed with result: {result}")
            self.update_window_title()
        except Exception as e:
            logger.exception("Error creating or showing SessionManagerDialog:")
            QMessageBox.critical(self, "Dialog Error", f"Could not open Session Manager:\n{e}")

    @pyqtSlot()
    def _trigger_save_session(self):
        current_path = getattr(self.chat_manager, '_current_session_filepath', None)
        if current_path:
             logger.info(f"Saving current session to existing path: {current_path}")
             self.chat_manager.save_current_chat_session(current_path)
        else:
             logger.info("No current session path, triggering Save As instead.")
             self._trigger_save_as_session()

    @pyqtSlot()
    def _trigger_save_as_session(self):
        logger.info("Triggering Save Session As dialog...")
        suggested_name = f"session_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            conv_dir = constants.CONVERSATIONS_DIR
            if not os.path.isdir(conv_dir):
                 try:
                     os.makedirs(conv_dir, exist_ok=True)
                     logger.info(f"Created conversations directory: {conv_dir}")
                 except OSError as e:
                     logger.error(f"Failed to create conversations directory '{conv_dir}'. Falling back. Error: {e}")
                     conv_dir = constants.USER_DATA_DIR
            suggested_path = os.path.join(conv_dir, suggested_name)
            filepath, _ = QFileDialog.getSaveFileName(self, "Save Current Session As", suggested_path, "JSON Session Files (*.json);;All Files (*)")
            if filepath:
                 if not filepath.lower().endswith(".json"): filepath += ".json"
                 if self.chat_manager.save_current_chat_session(filepath): self.update_window_title()
            else: logger.info("Save As dialog cancelled by user.")
        except Exception as e:
             logger.exception("Error during direct Save As operation:")
             QMessageBox.critical(self, "Save Error", f"An error occurred during Save As:\n{e}")

    @pyqtSlot()
    def _trigger_file_upload(self):
        if getattr(self.chat_manager, '_is_busy', True):
             self.update_status("Cannot upload while AI is busy.", "#e5c07b", True, 3000); return
        filter_parts = ["All Files (*)"]
        text_ext = sorted([ext for ext in constants.ALLOWED_TEXT_EXTENSIONS if ext not in ['.pdf', '.docx']])
        pdf_ext = ".pdf" if '.pdf' in constants.ALLOWED_TEXT_EXTENSIONS else None
        docx_ext = ".docx" if '.docx' in constants.ALLOWED_TEXT_EXTENSIONS else None
        if text_ext: filter_parts.append(f"Text Files ({' '.join(['*'+e for e in text_ext])})")
        if pdf_ext: filter_parts.append(f"PDF Files (*{pdf_ext})")
        if docx_ext: filter_parts.append(f"Word Documents (*{docx_ext})")
        filter_str = ";;".join(filter_parts)
        file_paths, _ = QFileDialog.getOpenFileNames(self, "Upload File(s) for Context", constants.USER_DATA_DIR, filter_str)
        if file_paths: self.chat_manager.handle_file_upload(file_paths)

    @pyqtSlot()
    def _trigger_dir_upload(self):
        if getattr(self.chat_manager, '_is_busy', True):
             self.update_status("Cannot upload while AI is busy.", "#e5c07b", True, 3000); return
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory for Context", constants.USER_DATA_DIR, QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
        if dir_path: self.chat_manager.handle_directory_upload(dir_path)

    @pyqtSlot()
    def _show_personality_editor(self):
        if getattr(self.chat_manager, '_is_busy', True):
             self.update_status("Cannot edit personality while AI is busy.", "#e5c07b", True, 3000); return
        current_prompt = self.chat_manager.get_current_personality()
        dialog = EditPersonalityDialog(current_prompt, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
             new_prompt = dialog.get_prompt_text()
             self.chat_manager.set_personality(new_prompt)
             self.update_window_title()
        else: self.update_status("Personality edit cancelled.", "#6a737d", True, 2000)

    @pyqtSlot()
    def _show_code_viewer(self):
        if self.code_viewer_window is None:
            try:
                self.code_viewer_window = CodeViewerWindow(self)
                # Rescan needs to get history from model now
                model = self.chat_display_area.get_model() if self.chat_display_area else None
                history = model.getAllMessages() if model else []
                self._rescan_history_for_code_blocks(history)
            except Exception as e:
                 logger.exception("Failed to create CodeViewerWindow")
                 QMessageBox.critical(self, "Error", f"Could not create Code Viewer:\n{e}")
                 return
        self.code_viewer_window.show()
        self.code_viewer_window.activateWindow()
        self.code_viewer_window.raise_()

    @pyqtSlot()
    def _show_rag_viewer(self):
        logger.debug("Show RAG Viewer action triggered.")
        rag_active = getattr(self.chat_manager, 'is_rag_active', lambda: False)()
        if not rag_active:
            self.update_status("RAG database is not initialized or empty.", "#e5c07b", True, 3000); return
        try:
            rag_data = self.chat_manager.get_rag_contents()
            if not rag_data:
                self.update_status("RAG database is empty.", "#e5c07b", True, 3000)
                # return # Optionally return if empty
            if self.rag_viewer_dialog is None:
                 logger.info("Creating RAGViewerDialog instance.")
                 self.rag_viewer_dialog = RAGViewerDialog(self)
            logger.info(f"Loading {len(rag_data)} items into RAGViewerDialog.")
            self.rag_viewer_dialog.load_data(rag_data)
            self.rag_viewer_dialog.exec()
        except Exception as e:
            logger.exception("Error creating or showing RAGViewerDialog:")
            QMessageBox.critical(self, "Dialog Error", f"Could not open RAG Viewer:\n{e}")


    # --- Code Block Handling ---
    # These methods remain largely the same but operate on ChatMessage data
    def _scan_message_for_code_blocks(self, message: ChatMessage):
        if not self.code_viewer_window or message.role != MODEL_ROLE or not message.text: return
        try:
            import re
            code_pattern = re.compile(r"```(\w*?) *\n?(.*?)```", re.DOTALL)
            matches = code_pattern.finditer(message.text)
            for match in matches:
                lang = match.group(1).strip().lower() if match.group(1) else "code"
                code_content = match.group(2).strip()
                if code_content: self.code_viewer_window.add_code_block(lang, code_content)
        except Exception as e_code: logger.error(f"Error processing code blocks in message: {e_code}")

    def _rescan_history_for_code_blocks(self, history: List[ChatMessage]):
        if not self.code_viewer_window: return
        try:
             self.code_viewer_window.clear_blocks()
             logger.info("Rescanning history for code blocks...")
             scan_count = 0
             for message in history:
                 if message.role == MODEL_ROLE and message.text:
                      self._scan_message_for_code_blocks(message)
                      scan_count += 1
             logger.info(f"History rescan complete. Processed {scan_count} model messages.")
        except Exception as e_rescan: logger.error(f"Error during history rescan for code blocks: {e_rescan}")

    # --- Utility Methods ---
    # update_status, update_window_title, keyPressEvent, closeEvent, showEvent, _update_rag_button_state
    # remain the same as the previous corrected version.
    @pyqtSlot(str, str, bool, int)
    def update_status(self, message: str, color: str = "#abb2bf", is_temporary: bool = False, duration_ms: int = 0):
        # (Same as previous version)
        if not self.status_label: return
        try:
            self.status_label.setStyleSheet(f"QLabel#StatusLabel {{ color: {color}; }}")
        except Exception as e_style: logger.error(f"Error setting status label style: {e_style}")
        self.status_label.setText(message)
        if self._status_clear_timer and self._status_clear_timer.isActive():
            self._status_clear_timer.stop()
        if is_temporary and duration_ms > 0:
            if not self._status_clear_timer:
                 self._status_clear_timer = QTimer(self)
                 self._status_clear_timer.setSingleShot(True)
                 # Use a lambda to call the manager's update method, ensuring it exists
                 update_method = getattr(self.chat_manager, 'update_status_based_on_state', None)
                 if callable(update_method):
                     self._status_clear_timer.timeout.connect(lambda: update_method())
                 else:
                     logger.warning("Cannot connect status timer: ChatManager missing 'update_status_based_on_state'")

            self._status_clear_timer.start(duration_ms)

    def update_window_title(self):
        # (Same as previous version)
        try:
            base_title = constants.APP_NAME; details = []; session_name_display = None
            current_path = getattr(self.chat_manager, '_current_session_filepath', None)
            model_name = self.chat_manager.get_current_model()
            personality_active = bool(self.chat_manager.get_current_personality())
            rag_active = getattr(self.chat_manager, 'is_rag_active', lambda: False)()
            if current_path:
                try: session_name_display = os.path.splitext(os.path.basename(current_path))[0]
                except Exception: session_name_display = "Saved Session"
                if session_name_display: details.append(f"{session_name_display}")
            if model_name:
                try:
                     model_short = model_name.split(':')[-1]
                     if '/' in model_short: model_short = model_short.split('/')[-1]
                     model_short = model_short.replace("-latest", "").replace("-preview", "").replace("models/", "").replace("gemini-", "")
                except Exception: model_short = model_name
                details.append(f"M:{model_short}")
            if personality_active: details.append("P")
            if rag_active: details.append("RAG")
            final_title = base_title + (" - [" + " | ".join(details) + "]" if details else "")
            self.setWindowTitle(final_title)
        except Exception as e:
             logger.error(f"Error updating window title: {e}")
             self.setWindowTitle(constants.APP_NAME)

    def keyPressEvent(self, event: QKeyEvent):
        # (Same as previous version)
        if event.key() == Qt.Key.Key_Escape and getattr(self.chat_manager, '_is_busy', False):
            logger.info("ESC pressed during busy state. Requesting backend task cancellation.")
            cancel_method = getattr(self.chat_manager, '_cancel_backend_task', None)
            if callable(cancel_method):
                try:
                    cancel_method()
                    self.update_status("Attempting to cancel...", "#e5c07b", True, 2000)
                except Exception as e_cancel: logger.error(f"Error calling cancel method: {e_cancel}")
            else: logger.warning("Cannot cancel: _cancel_backend_task method not found on ChatManager.")
            event.accept()
        else: super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent):
        # (Same as previous version)
        logger.info("MainWindow close event triggered. Performing cleanup...")
        if self.code_viewer_window:
             try: self.code_viewer_window.close()
             except Exception as e_diag: logger.error(f"Error closing CodeViewerWindow: {e_diag}")
        if self.session_manager_dialog:
             try: self.session_manager_dialog.close()
             except Exception as e_diag: logger.error(f"Error closing SessionManagerDialog: {e_diag}")
        if self.rag_viewer_dialog:
             try: self.rag_viewer_dialog.close()
             except Exception as e_diag: logger.error(f"Error closing RAGViewerDialog: {e_diag}")
        if self.chat_manager:
             try: self.chat_manager.cleanup()
             except Exception as e_cleanup: logger.error(f"Error during ChatManager cleanup: {e_cleanup}")
        logger.info("Cleanup complete. Accepting close event.")
        event.accept()

    def showEvent(self, event):
        # (Same as previous version - includes fix for RAG button state)
        super().showEvent(event)
        QTimer.singleShot(100, lambda: self.chat_input_bar.set_focus() if self.chat_input_bar else None)
        self._update_rag_button_state()

    def _update_rag_button_state(self):
        # (Same as previous version - includes fix for RAG button state)
        if self.left_panel and hasattr(self.left_panel, 'view_rag_button'):
            try:
                rag_active = getattr(self.chat_manager, 'is_rag_active', lambda: False)()
                logger.debug(f"Updating RAG button state. RAG Active: {rag_active}")
                self.left_panel.view_rag_button.setEnabled(rag_active)
            except Exception as e: logger.error(f"Error updating RAG button state: {e}")
        elif not self.left_panel: logger.warning("Cannot update RAG button state: left_panel is None.")
        else: logger.warning("Cannot update RAG button state: left_panel.view_rag_button not found.")