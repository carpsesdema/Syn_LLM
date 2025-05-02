# SynaChat/ui/chat_display_area.py
# UPDATED FILE - Call delegate cache clear on model reset

import logging
from typing import List, Dict, Any, Optional

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QListView, QAbstractItemView, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QModelIndex

# --- Local Imports ---
from core.models import ChatMessage
# Import the new Model and Delegate
from .chat_list_model import ChatListModel, ChatMessageRole
from .chat_item_delegate import ChatItemDelegate

logger = logging.getLogger(__name__)

class ChatDisplayArea(QWidget):
    """
    Manages the chat message display area using QListView with a custom model and delegate.
    Receives signals to update the ChatListModel.
    """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ChatDisplayAreaWidget")

        # --- Core Components ---
        self.chat_list_view: Optional[QListView] = None
        self.chat_list_model: Optional[ChatListModel] = None
        self.chat_item_delegate: Optional[ChatItemDelegate] = None

        self._init_ui()
        self._connect_model_signals() # Connect signals from the model

    def _init_ui(self):
        """Initialize the UI elements."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.chat_list_view = QListView(self)
        self.chat_list_view.setObjectName("ChatListView") # For QSS styling
        self.chat_list_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chat_list_view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection) # Usually no selection needed
        self.chat_list_view.setResizeMode(QListView.ResizeMode.Adjust) # Adjust items on resize
        self.chat_list_view.setUniformItemSizes(False) # Items have different heights
        self.chat_list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel) # Smoother scrolling
        self.chat_list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_list_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # --- Model Setup ---
        self.chat_list_model = ChatListModel(self)
        self.chat_list_view.setModel(self.chat_list_model)

        # --- Delegate Setup ---
        self.chat_item_delegate = ChatItemDelegate(self)
        self.chat_list_view.setItemDelegate(self.chat_item_delegate)

        outer_layout.addWidget(self.chat_list_view)
        self.setLayout(outer_layout)
        logger.info("ChatDisplayArea UI initialized with QListView, Model, and Delegate.")

    # --- Connect internal model signals ---
    def _connect_model_signals(self):
        if self.chat_list_model:
            # Connect modelReset signal to clear the delegate's cache
            self.chat_list_model.modelReset.connect(self._handle_model_reset)
            # Could connect rowsInserted if specific actions needed after add
            # self.chat_list_model.rowsInserted.connect(self._handle_rows_inserted)

    @pyqtSlot()
    def _handle_model_reset(self):
        """Called when the model emits modelReset."""
        logger.debug("ChatDisplayArea: Handling modelReset signal.")
        if self.chat_item_delegate:
            self.chat_item_delegate.clearCache()
        self._scroll_to_bottom() # Scroll after reset (usually means clear or load history)

    # --- Slots to Interact with the Model (Called by MainWindow) ---

    @pyqtSlot(ChatMessage)
    def add_message_to_model(self, message: ChatMessage):
        """Adds a new, complete message to the model."""
        logger.debug(f"DisplayArea: Received request to add message to model (Role: {message.role})")
        if self.chat_list_model:
            self.chat_list_model.addMessage(message)
            self._scroll_to_bottom() # Scroll after adding
        else:
            logger.error("Cannot add message: chat_list_model is None.")

    @pyqtSlot(ChatMessage)
    def start_streaming_in_model(self, initial_message: ChatMessage):
        """Adds the initial placeholder message for a stream to the model."""
        logger.debug(f"DisplayArea: Received request to start stream in model (Role: {initial_message.role})")
        if self.chat_list_model:
            if initial_message.metadata is None: initial_message.metadata = {}
            initial_message.metadata["is_streaming"] = True
            self.chat_list_model.addMessage(initial_message)
            self._scroll_to_bottom()
        else:
            logger.error("Cannot start stream: chat_list_model is None.")

    @pyqtSlot(str)
    def append_stream_chunk_to_model(self, chunk: str):
        """Appends a text chunk to the last message in the model."""
        if self.chat_list_model:
            self.chat_list_model.appendChunkToLastMessage(chunk)
            v_scrollbar = self.chat_list_view.verticalScrollBar()
            if v_scrollbar and v_scrollbar.maximum() > v_scrollbar.minimum():
                is_at_bottom = v_scrollbar.value() >= (v_scrollbar.maximum() - 30)
                if is_at_bottom:
                    self._scroll_to_bottom()
        else:
            logger.error("Cannot append chunk: chat_list_model is None.")

    @pyqtSlot()
    def finalize_stream_in_model(self):
        """Marks the last message in the model as finalized."""
        logger.debug("DisplayArea: Received request to finalize stream in model.")
        if self.chat_list_model:
            self.chat_list_model.finalizeLastMessage()
            QTimer.singleShot(100, self._scroll_to_bottom)
        else:
            logger.error("Cannot finalize stream: chat_list_model is None.")

    @pyqtSlot(list)
    def load_history_into_model(self, history: List[ChatMessage]):
        """Loads a complete history list into the model."""
        logger.info(f"DisplayArea: Received request to load history (count: {len(history)}) into model.")
        if self.chat_list_model:
            self.chat_list_model.loadHistory(history) # This will trigger modelReset
            # No need to explicitly clear cache here, _handle_model_reset does it
            # No need to scroll here, _handle_model_reset does it
        else:
            logger.error("Cannot load history: chat_list_model is None.")

    @pyqtSlot()
    def clear_model_display(self):
        """Clears all messages from the model."""
        logger.info("DisplayArea: Received request to clear model display.")
        if self.chat_list_model:
            self.chat_list_model.clearMessages() # This triggers modelReset
            # No need to explicitly clear cache here, _handle_model_reset does it
        else:
            logger.error("Cannot clear display: chat_list_model is None.")

    # --- Scrolling ---

    def _scroll_to_bottom(self):
        """Scrolls the list view to the bottom."""
        if self.chat_list_view and self.chat_list_model and self.chat_list_model.rowCount() > 0:
            QTimer.singleShot(0, lambda: self.chat_list_view.scrollToBottom())


    # --- Public Accessor for the Model (if needed by MainWindow/others) ---
    def get_model(self) -> Optional[ChatListModel]:
        return self.chat_list_model