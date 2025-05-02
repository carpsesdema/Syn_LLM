import logging
from typing import List, Optional, Any, Union

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt, QObject
from core.models import ChatMessage, USER_ROLE, MODEL_ROLE, SYSTEM_ROLE, ERROR_ROLE

logger = logging.getLogger(__name__)

# Define a custom role to retrieve the full ChatMessage object
ChatMessageRole = Qt.ItemDataRole.UserRole + 1

class ChatListModel(QAbstractListModel):
    """
    A QAbstractListModel to manage the list of ChatMessage objects
    for display in a QListView.
    """

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._messages: List[ChatMessage] = []
        logger.info("ChatListModel initialized.")

    # --- QAbstractListModel Interface ---

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        """Returns the number of messages in the model."""
        # In a plain list model, the parent is always invalid
        return 0 if parent.isValid() else len(self._messages)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Returns the data for a given index and role."""
        if not index.isValid() or not (0 <= index.row() < len(self._messages)):
            return None

        message = self._messages[index.row()]

        if role == ChatMessageRole:
            return message # Return the full ChatMessage object
        elif role == Qt.ItemDataRole.DisplayRole:
            # Optionally return a simple text representation for debugging/default views
            return f"[{message.role}] {message.text[:50]}..."
        # Add other roles if needed (e.g., ToolTipRole)

        return None

    # --- Custom Methods for Data Manipulation ---

    def addMessage(self, message: ChatMessage):
        """Adds a single message to the end of the model."""
        if not isinstance(message, ChatMessage):
            logger.error(f"Attempted to add invalid type to ChatListModel: {type(message)}")
            return

        logger.debug(f"Model: Adding message (Role: {message.role})")
        row_to_insert = len(self._messages)
        self.beginInsertRows(QModelIndex(), row_to_insert, row_to_insert)
        self._messages.append(message)
        self.endInsertRows()
        logger.debug(f"Model: Message added. New count: {len(self._messages)}")

    def appendChunkToLastMessage(self, chunk: str):
        """Appends a text chunk to the last message in the model (for streaming)."""
        if not self._messages:
            logger.warning("Model: Cannot append chunk, message list is empty.")
            return
        if not isinstance(chunk, str):
            logger.warning(f"Model: Invalid chunk type: {type(chunk)}")
            return

        last_message_index = len(self._messages) - 1
        last_message = self._messages[last_message_index]

        # Update the internal message representation
        current_text = ""
        text_part_index = -1

        # Find existing text part or determine insertion point
        for i, part in enumerate(last_message.parts):
            if isinstance(part, str):
                current_text = part
                text_part_index = i
                break

        updated_text = current_text + chunk

        if text_part_index != -1:
            last_message.parts[text_part_index] = updated_text
        else:
            # Insert text part at the beginning if none existed
            last_message.parts.insert(0, updated_text)

        # Mark as streaming (if not already)
        if last_message.metadata is None: last_message.metadata = {}
        last_message.metadata["is_streaming"] = True # Ensure flag is set

        # Notify the view that the data for the last row has changed
        model_index = self.index(last_message_index, 0)
        self.dataChanged.emit(model_index, model_index, [ChatMessageRole, Qt.ItemDataRole.DisplayRole])
        # logger.debug(f"Model: Appended chunk. Last msg text len: {len(updated_text)}") # Too noisy

    def finalizeLastMessage(self):
        """Marks the last message as no longer streaming."""
        if not self._messages:
            logger.warning("Model: Cannot finalize, message list is empty.")
            return

        last_message_index = len(self._messages) - 1
        last_message = self._messages[last_message_index]

        if last_message.metadata and last_message.metadata.get("is_streaming"):
            logger.debug(f"Model: Finalizing last message (Role: {last_message.role})")
            last_message.metadata["is_streaming"] = False
            # Notify view to potentially re-render with final styling/markdown
            model_index = self.index(last_message_index, 0)
            self.dataChanged.emit(model_index, model_index, [ChatMessageRole])
        else:
            logger.debug("Model: Finalize called but last message wasn't marked as streaming.")

    def loadHistory(self, history: List[ChatMessage]):
        """Replaces the entire model content with a new history list."""
        logger.info(f"Model: Loading history (count: {len(history)})")
        self.beginResetModel()
        self._messages = list(history) # Replace internal list
        self.endResetModel()
        logger.info("Model: History loaded.")

    def clearMessages(self):
        """Removes all messages from the model."""
        logger.info("Model: Clearing all messages.")
        self.beginResetModel()
        self._messages = []
        self.endResetModel()
        logger.info("Model: Messages cleared.")

    def getMessage(self, row: int) -> Optional[ChatMessage]:
        """Safely retrieves a message by row index."""
        if 0 <= row < len(self._messages):
            return self._messages[row]
        return None

    def getAllMessages(self) -> List[ChatMessage]:
        """Returns a copy of the internal message list."""
        return list(self._messages)