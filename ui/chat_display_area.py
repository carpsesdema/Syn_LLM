# SynChat/ui/chat_display_area.py
# UPDATED FILE (Added streaming methods)
import logging
from typing import List, Dict, Any, Optional

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QSizePolicy, QLabel
)
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QMargins

# --- Local Imports ---
from ui.widgets import ChatBubbleWidget # Import from sibling ui package
from core.models import ChatMessage # Use the ChatMessage model

logger = logging.getLogger(__name__)

class ChatDisplayArea(QWidget):
    """
    Manages the chat message display area using ChatBubbleWidgets.
    Receives ChatMessage objects to display.
    Handles scrolling and bubble width updates.
    Supports streaming message display.
    """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ChatDisplayAreaWidget")

        self.chat_scroll_area: Optional[QScrollArea] = None
        self.chat_widget: Optional[QWidget] = None
        self.chat_layout: Optional[QVBoxLayout] = None

        # Store bubble widgets for width updates
        self._bubble_widgets: List[ChatBubbleWidget] = []
        # Store reference to the bubble currently being streamed into (if any)
        self._streaming_bubble: Optional[ChatBubbleWidget] = None

        self._init_ui()

    def _init_ui(self):
        """Initialize the UI elements."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.chat_scroll_area = QScrollArea()
        self.chat_scroll_area.setObjectName("ChatScrollArea")
        self.chat_scroll_area.setWidgetResizable(True)
        self.chat_scroll_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chat_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container for centering chat_widget
        scroll_content_container = QWidget()
        scroll_content_container.setObjectName("ScrollContentContainer")
        scroll_container_layout = QHBoxLayout(scroll_content_container)
        scroll_container_layout.setContentsMargins(0, 0, 0, 0)
        scroll_container_layout.setSpacing(0)

        # Widget holding the bubble layout
        self.chat_widget = QWidget()
        self.chat_widget.setObjectName("ChatWidgetContainer")
        self.chat_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setContentsMargins(10, 10, 10, 10)
        self.chat_layout.setSpacing(8)
        self.chat_layout.addStretch(1) # Push bubbles upwards

        scroll_container_layout.addStretch(0)
        scroll_container_layout.addWidget(self.chat_widget, 0)
        scroll_container_layout.addStretch(0)

        self.chat_scroll_area.setWidget(scroll_content_container)
        outer_layout.addWidget(self.chat_scroll_area)
        logger.info("ChatDisplayArea UI initialized.")

    @pyqtSlot(ChatMessage)
    def add_message(self, message: ChatMessage):
        """Adds a new, complete message bubble from a ChatMessage object."""
        if not self.chat_layout or not self.chat_widget:
            logger.critical("Cannot add message: chat_layout or chat_widget is None!")
            return
        # --- Ensure any previous stream is ended before adding a complete message ---
        if self._streaming_bubble:
             logger.warning("Finalizing previous stream before adding new complete message.")
             self.finalize_streaming_message()
        # --- End change ---

        logger.debug(f"Adding message bubble for role: {message.role}")
        bubble = ChatBubbleWidget(message, parent=self.chat_widget)

        # Update width after insertion using timer
        QTimer.singleShot(0, lambda b=bubble: self._update_single_bubble_width(b))

        # Insert bubble into layout
        insert_index = self.chat_layout.count() - 1 # Above stretch
        self.chat_layout.insertWidget(max(0, insert_index), bubble)
        self._bubble_widgets.append(bubble) # Track bubble

        QTimer.singleShot(50, self._scroll_to_bottom)


    # --- Methods for Streaming Display (Called by MainWindow/ChatManager via signals) ---

    def start_streaming_message(self, initial_message: ChatMessage):
        """Creates an initial bubble for streaming content."""
        # --- Ensure any previous stream is ended ---
        if self._streaming_bubble:
            logger.warning("Streaming already in progress. Finalizing previous.")
            self.finalize_streaming_message()
        # --- End change ---

        if not self.chat_layout or not self.chat_widget:
            logger.critical("Cannot start streaming: chat_layout or chat_widget is None!")
            return

        logger.debug(f"Starting streaming display for role: {initial_message.role}")
        # Create bubble with potentially empty initial text
        self._streaming_bubble = ChatBubbleWidget(initial_message, parent=self.chat_widget)

        # Update width after insertion
        QTimer.singleShot(0, lambda b=self._streaming_bubble: self._update_single_bubble_width(b))

        # Insert into layout
        insert_index = self.chat_layout.count() - 1
        self.chat_layout.insertWidget(max(0, insert_index), self._streaming_bubble)
        self._bubble_widgets.append(self._streaming_bubble) # Track bubble
        QTimer.singleShot(10, self._scroll_to_bottom) # Initial scroll

    def append_stream_chunk(self, chunk: str):
        """Appends text chunk to the currently streaming bubble."""
        if not self._streaming_bubble:
            # This might happen if stream_finished arrives slightly before the last chunk signal
            # logger.warning("Received stream chunk but no streaming bubble active.")
            return
        if not chunk: return

        # Append chunk to the bubble's internal message object parts
        # The update_text method now handles combining parts internally
        current_text = self._streaming_bubble.message.text + chunk
        self._streaming_bubble.update_text(current_text) # Update display

        # Smart scrolling (optional)
        v_scrollbar = self.chat_scroll_area.verticalScrollBar()
        is_at_bottom = v_scrollbar.value() >= (v_scrollbar.maximum() - 15) # Tolerance
        if is_at_bottom:
            QTimer.singleShot(10, self._scroll_to_bottom)


    def finalize_streaming_message(self):
        """Finalizes the streaming bubble."""
        if not self._streaming_bubble: return

        logger.debug("Finalizing streaming message display.")
        final_bubble = self._streaming_bubble
        self._streaming_bubble = None # Clear reference

        # Trigger a final width update for the completed bubble
        if final_bubble:
             QTimer.singleShot(10, lambda b=final_bubble: self._update_single_bubble_width(b))
             # Optionally trigger code block scanning on the final bubble if needed
             # main_window_ref = self.parent() # Need ref to MainWindow or ChatManager
             # if main_window_ref and hasattr(main_window_ref, '_scan_message_for_code_blocks'):
             #      main_window_ref._scan_message_for_code_blocks(final_bubble.message)

        QTimer.singleShot(50, self._scroll_to_bottom) # Final scroll

    def remove_streaming_bubble(self):
        """Forcefully removes the streaming bubble if an error occurs during streaming."""
        logger.warning("Removing streaming bubble due to external request (e.g., error).")
        if self._streaming_bubble:
             bubble_to_remove = self._streaming_bubble
             if bubble_to_remove in self._bubble_widgets:
                 self._bubble_widgets.remove(bubble_to_remove)
             if self.chat_layout:
                 self.chat_layout.removeWidget(bubble_to_remove)
             bubble_to_remove.deleteLater()
             self._streaming_bubble = None


    # --- History Loading & Clearing ---

    @pyqtSlot(list) # Accept list of ChatMessage objects
    def load_history(self, history: List[ChatMessage]):
        """Clears display and loads bubbles from a history list."""
        self.clear_display() # Clear existing bubbles first
        logger.info(f"Loading {len(history)} messages into display...")

        if not isinstance(history, list):
            logger.error(f"Cannot load history: Invalid type '{type(history)}'.")
            return

        if not history: logger.info("Empty history provided."); return

        bubbles_to_add = []
        for msg in history:
            if isinstance(msg, ChatMessage):
                 bubble = ChatBubbleWidget(msg, parent=self.chat_widget)
                 bubbles_to_add.append(bubble)
            else:
                logger.warning(f"Skipping invalid item in history list: {type(msg)}")

        if bubbles_to_add:
            logger.debug(f"Inserting {len(bubbles_to_add)} bubbles from history.")
            insert_index = self.chat_layout.count() - 1
            for bubble in bubbles_to_add:
                self.chat_layout.insertWidget(max(0, insert_index), bubble)
                self._bubble_widgets.append(bubble) # Track bubbles

            QTimer.singleShot(50, self._update_all_bubble_widths)

        QTimer.singleShot(100, self._scroll_to_bottom) # Scroll after potential layout updates
        logger.info("Finished loading history into display.")

    def clear_display(self):
        """Removes all message bubbles."""
        logger.debug("Clearing chat display area...")
        # --- Finalize any active stream before clearing ---
        self.finalize_streaming_message()
        # --- End change ---
        while self._bubble_widgets:
             bubble = self._bubble_widgets.pop()
             if self.chat_layout: self.chat_layout.removeWidget(bubble)
             bubble.deleteLater()
        logger.debug("Chat display cleared.")


    # --- Scrolling and Width Calculation ---

    def _scroll_to_bottom(self):
        """Scrolls the chat view to the bottom."""
        if self.chat_scroll_area and self.chat_scroll_area.verticalScrollBar():
            v_scrollbar = self.chat_scroll_area.verticalScrollBar()
            QTimer.singleShot(0, lambda: v_scrollbar.setValue(v_scrollbar.maximum()))

    def _update_single_bubble_width(self, bubble_widget: Optional[ChatBubbleWidget]):
        """Calculates and applies max width to a single bubble."""
        if not self.chat_scroll_area or not bubble_widget or not hasattr(bubble_widget, 'update_width'): return
        try:
            viewport = self.chat_scroll_area.viewport()
            if not viewport: return
            viewport_width = viewport.width()
            layout_margins = self.chat_layout.contentsMargins() if self.chat_layout else QMargins(10, 10, 10, 10)
            scrollbar_width_approx = 15
            padding_buffer = 20
            effective_width = viewport_width - layout_margins.left() - layout_margins.right() - scrollbar_width_approx - padding_buffer

            if effective_width <= 0: effective_width = 300 # Fallback

            max_width_factor = 0.68
            max_bubble_width = max(100, int(effective_width * max_width_factor))

            bubble_widget.update_width(max_bubble_width)
        except Exception as e:
            logger.error(f"Error calculating/setting bubble width: {e}", exc_info=False)

    def _update_all_bubble_widths(self):
        """Updates maximum width for all existing bubbles."""
        for bubble in self._bubble_widgets:
            self._update_single_bubble_width(bubble)

    def resizeEvent(self, event: QResizeEvent):
        """Handles resize events for this component."""
        super().resizeEvent(event)
        QTimer.singleShot(100, self._update_all_bubble_widths)