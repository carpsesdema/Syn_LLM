# SynaChat/ui/left_panel.py
# UPDATED FILE - Added RAG Viewer Button
import logging
from typing import List, Optional

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QLabel, QStyle, QSizePolicy
)
from PyQt6.QtGui import QFont, QIcon, QPixmap
from PyQt6.QtCore import pyqtSignal, Qt, QSize

# --- Local Imports ---
from utils.constants import (
    CHAT_FONT_FAMILY, CHAT_FONT_SIZE
)

logger = logging.getLogger(__name__)

class LeftControlPanel(QWidget):
    """
    Left sidebar widget containing controls like session management,
    model selection, uploads, etc. Emits signals for actions.
    """
    # --- Signals for actions (interact with ChatManager via MainWindow) ---
    newSessionClicked = pyqtSignal()
    manageSessionsClicked = pyqtSignal()
    uploadFileClicked = pyqtSignal()
    uploadDirectoryClicked = pyqtSignal()
    editPersonalityClicked = pyqtSignal()
    viewCodeBlocksClicked = pyqtSignal()
    # --- ADDED ---
    viewRagContentClicked = pyqtSignal()
    # -----------
    modelSelected = pyqtSignal(str) # Emits selected model name

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("LeftControlPanel")
        self._init_widgets()
        self._init_layout()
        self._connect_signals() # Connect internal widgets to this panel's signals

    def _init_widgets(self):
        """Initialize the widgets."""
        self.button_font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE - 1) # Slightly smaller font

        # --- Session Buttons ---
        self.new_session_button = self._create_button(" New Session", "SP_FileIcon", "Start a new chat session (Ctrl+N)", "newSessionButton")
        self.manage_sessions_button = self._create_button(" Manage Sessions", "SP_DriveHDIcon", "Load, save, or manage chat sessions", "manageSessionsButton")

        # --- Upload Buttons ---
        self.upload_button = self._create_button(" Upload File(s)", "SP_DialogOpenButton", "Upload files for context (Ctrl+U)", "uploadFileButton")
        self.upload_dir_button = self._create_button(" Upload Directory", "SP_DirIcon", "Upload a directory for context (Ctrl+Shift+U)", "uploadDirButton")

        # --- Tools/View Buttons ---
        self.view_code_button = self._create_button(" View Code Blocks", "SP_FileDialogDetailedView", "View code blocks from the chat (Ctrl+B)", "viewCodeButton")
        # --- ADDED ---
        self.view_rag_button = self._create_button(" View RAG Content", "SP_FileDialogInfoView", "View indexed documents and chunks", "viewRagButton") # Using SP_FileDialogInfoView icon
        # -----------
        self.edit_personality_button = self._create_button(" Edit Personality", "SP_ToolBarHorizontalExtensionButton", "Edit AI system prompt/personality (Ctrl+P)", "editPersonalityButton")


        # --- Model Selector ---
        self.model_label = QLabel("Model:")
        self.model_label.setFont(self.button_font)
        self.model_selector = QComboBox()
        self.model_selector.setFont(self.button_font)
        self.model_selector.setObjectName("ModelSelector")
        self.model_selector.setToolTip("Select the AI model to use")

    def _create_button(self, text: str, std_icon_name: str, tooltip: str, obj_name: str) -> QPushButton:
        """Helper to create and configure a QPushButton."""
        button = QPushButton(text)
        button.setFont(self.button_font)
        button.setToolTip(tooltip)
        button.setObjectName(obj_name)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setStyleSheet("QPushButton { text-align: left; padding: 6px 8px; }") # Adjusted padding
        button.setIconSize(QSize(16, 16))
        # Set standard icon
        try:
             icon_enum = getattr(QStyle.StandardPixmap, std_icon_name, None)
             if icon_enum:
                 icon = self.style().standardIcon(icon_enum)
                 if not icon.isNull():
                     button.setIcon(icon)
             else: logger.warning(f"Standard icon '{std_icon_name}' not found.")
        except Exception as e: logger.error(f"Error setting icon {std_icon_name}: {e}")
        return button

    def _init_layout(self):
        """Set up the layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10) # Adjusted margins
        layout.setSpacing(8) # Adjusted spacing

        layout.addWidget(self.new_session_button)
        layout.addWidget(self.manage_sessions_button)
        layout.addSpacing(15)
        layout.addWidget(self.upload_button)
        layout.addWidget(self.upload_dir_button)
        # --- ADDED ---
        layout.addWidget(self.view_rag_button)
        # -----------
        layout.addSpacing(15)
        layout.addWidget(self.view_code_button)
        layout.addWidget(self.edit_personality_button)
        layout.addSpacing(15)
        layout.addWidget(self.model_label)
        layout.addWidget(self.model_selector)
        layout.addStretch(1) # Push controls to the top

    def _connect_signals(self):
        """Connect internal widget signals to the panel's signals."""
        self.new_session_button.clicked.connect(self.newSessionClicked)
        self.manage_sessions_button.clicked.connect(self.manageSessionsClicked)
        self.upload_button.clicked.connect(self.uploadFileClicked)
        self.upload_dir_button.clicked.connect(self.uploadDirectoryClicked)
        self.view_code_button.clicked.connect(self.viewCodeBlocksClicked)
        self.edit_personality_button.clicked.connect(self.editPersonalityClicked)
        self.model_selector.currentTextChanged.connect(self.modelSelected)
        # --- ADDED ---
        self.view_rag_button.clicked.connect(self.viewRagContentClicked)
        # -----------

    # --- Public Methods for External Control (called by MainWindow) ---
    def set_enabled_state(self, enabled: bool, is_busy: bool):
        """Enable/disable controls based on application state."""
        # Disable everything if busy
        effective_enabled = enabled and not is_busy

        self.new_session_button.setEnabled(effective_enabled)
        self.manage_sessions_button.setEnabled(effective_enabled)
        self.upload_button.setEnabled(effective_enabled)
        self.upload_dir_button.setEnabled(effective_enabled) # Assumes handler exists
        self.view_code_button.setEnabled(True) # Can view code even if API not ready/busy
        self.edit_personality_button.setEnabled(effective_enabled)
        self.model_selector.setEnabled(effective_enabled) # Enable selector, but it won't have options initially

        # --- MODIFIED ---
        # Enable RAG button if the RAG system is initialized (even if busy/API not ready)
        rag_active = getattr(self.parent().chat_manager, 'is_rag_active', lambda: False)() if self.parent() and hasattr(self.parent(), 'chat_manager') else False
        self.view_rag_button.setEnabled(rag_active)
        # ---------------

        # Style label based on overall API readiness (enabled)
        label_color = "#CCCCCC" if enabled else "#777777" # Grey out if API fundamentally not ready
        self.model_label.setStyleSheet(f"QLabel {{ color: {label_color}; }}")

    def update_model_selection(self, model_name: str):
        """Programmatically set the selected model in the combo box."""
        # Since list is empty, just set the text temporarily.
        # A better approach later would be to add the item if missing or select if present.
        self.model_selector.blockSignals(True)
        # Check if the model_name is already an item (it won't be initially)
        idx = self.model_selector.findText(model_name)
        if idx == -1:
             # If not found, add it as the first item and select it
             self.model_selector.clear() # Clear any potential placeholder text
             self.model_selector.addItem(model_name)
             self.model_selector.setCurrentIndex(0)
             logger.debug(f"Set model selector to initial model: {model_name}")
        elif self.model_selector.currentText() != model_name:
             self.model_selector.setCurrentIndex(idx)

        self.model_selector.blockSignals(False)


    def update_personality_tooltip(self, active: bool):
        """Update the tooltip for the personality button."""
        tooltip_base = "Edit AI system prompt/personality (Ctrl+P)" # Added shortcut back
        status = "(Active)" if active else "(Default)"
        self.edit_personality_button.setToolTip(f"{tooltip_base}\nStatus: {status}")