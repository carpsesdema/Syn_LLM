# Syn_LLM/ui/dialogs.py
# UPDATED FILE - Ensured Code Viewer uses monospace font explicitly

import logging
import os
from datetime import datetime
from collections import defaultdict
from typing import Optional, List, Tuple, Dict, Any

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QApplication, QMessageBox, QDialogButtonBox, QLabel, QWidget,
    QAbstractItemView, QFileDialog, QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QClipboard, QIcon, QFontDatabase, QTextOption

# --- Local Imports ---
# CHAT_FONT_SIZE is still used for base size calculation
from utils.constants import CHAT_FONT_FAMILY, CHAT_FONT_SIZE, CONVERSATIONS_DIR
from utils.syntax_highlighter import PythonSyntaxHighlighter
from core.chat_manager import ChatManager
from services.session_service import SessionService

# Import icons from widgets module
from .widgets import COPY_ICON, CHECK_ICON

logger = logging.getLogger(__name__)

# --- Code Viewer Window ---
class CodeViewerWindow(QDialog):
    """A non-modal dialog to display code blocks from the chat."""
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Code Blocks Viewer")
        self.setObjectName("CodeViewerWindow")
        self.setMinimumSize(700, 500) # Slightly larger
        self.setModal(False) # Non-modal

        # Store code blocks as (label, language, content)
        self._code_blocks: List[Tuple[str, str, str]] = []
        self._block_counter = 0 # Simple counter for labels

        # --- Font Setup ---
        # Explicitly get a fixed-width font for the code editor
        code_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        # Use the CHAT_FONT_SIZE as the base size for consistency
        code_font.setPointSize(CHAT_FONT_SIZE)
        logger.info(f"CodeViewerWindow using Monospace Font: {code_font.family()} {code_font.pointSize()}pt")

        # Main layout
        layout = QVBoxLayout(self)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.splitter, 1) # Give stretch factor

        # Left: List of blocks
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("CodeBlockList")
         # Use default font for list (will be SansSerif now)
        self.list_widget.setMinimumWidth(200)
        self.splitter.addWidget(self.list_widget)

        # Right: Code display
        self.code_edit = QTextEdit()
        self.code_edit.setObjectName("CodeViewerEdit")
        self.code_edit.setReadOnly(True)
        self.code_edit.setFont(code_font) # Apply the monospace font
        self.code_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap) # No wrap for code

        # Apply syntax highlighting (passing the document)
        self.highlighter = None
        try:
            # Pass the document which now has the monospace font set
            self.highlighter = PythonSyntaxHighlighter(self.code_edit.document())
            logger.info("CodeViewerWindow: PythonSyntaxHighlighter attached.")
        except Exception as e_hl:
             logger.error(f"Error attaching PythonSyntaxHighlighter: {e_hl}")

        self.splitter.addWidget(self.code_edit)
        self.splitter.setSizes([220, 480]) # Adjust initial sizes

        # Bottom buttons (use default font)
        button_layout = QHBoxLayout()
        self.copy_button = QPushButton(" Copy Code")
        self.copy_button.setToolTip("Copy the code currently shown in the viewer")
        if not COPY_ICON.isNull(): self.copy_button.setIcon(COPY_ICON)
        self.copy_button.clicked.connect(self._copy_selected_code_with_feedback)
        self.copy_button.setEnabled(False) # Disabled initially
        button_layout.addWidget(self.copy_button)

        button_layout.addStretch()

        self.clear_button = QPushButton("Clear All")
        self.clear_button.setToolTip("Remove all listed code blocks")
        self.clear_button.clicked.connect(self.clear_blocks)
        self.clear_button.setEnabled(False) # Disabled initially
        button_layout.addWidget(self.clear_button)

        self.close_button = QPushButton("Close")
        self.close_button.setToolTip("Hide this window")
        self.close_button.clicked.connect(self.hide) # Hide instead of closing
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

        # Connect signals
        self.list_widget.currentItemChanged.connect(self._display_selected_code)

    def add_code_block(self, language: str, code_content: str):
        """Adds a detected code block to the list."""
        self._block_counter += 1
        lang_display = language.strip().capitalize() if language.strip() else "Code"
        label = f"{lang_display} Block {self._block_counter}"
        self._code_blocks.append((label, language, code_content))

        list_item = QListWidgetItem(label)
        # Store the index in the UserRole for retrieval
        list_item.setData(Qt.ItemDataRole.UserRole, len(self._code_blocks) - 1)
        self.list_widget.addItem(list_item)

        # Auto-select the first item added or if window becomes visible
        if self.list_widget.count() == 1 or self.isVisible():
            self.list_widget.setCurrentRow(self.list_widget.count() - 1)

        self.clear_button.setEnabled(True)
        logger.info(f"Added '{label}' to CodeViewerWindow.")

    def clear_blocks(self):
        """Clears all code blocks from the viewer."""
        if not self._code_blocks: return
        self._code_blocks.clear()
        self.list_widget.clear()
        self.code_edit.clear()
        self.copy_button.setEnabled(False)
        self.clear_button.setEnabled(False)
        self._block_counter = 0
        logger.info("Cleared all blocks from CodeViewerWindow.")

    def _display_selected_code(self, current_item: Optional[QListWidgetItem], previous_item: Optional[QListWidgetItem]):
        """Displays the code corresponding to the selected list item."""
        self._reset_copy_button_icon() # Reset icon when selection changes
        if current_item is None:
            self.code_edit.clear()
            self.copy_button.setEnabled(False)
            return

        stored_index = current_item.data(Qt.ItemDataRole.UserRole)
        if stored_index is not None and 0 <= stored_index < len(self._code_blocks):
            label, language, code_content = self._code_blocks[stored_index]
            self.code_edit.setPlainText(code_content)
            # Rehighlight if highlighter exists (useful if switching languages later)
            if self.highlighter:
                try: self.highlighter.rehighlight()
                except Exception as e_rh: logger.error(f"Error rehighlighting code: {e_rh}")
            self.copy_button.setEnabled(True)
        else:
            logger.warning(f"Invalid index ({stored_index}) selected in CodeViewerWindow list.")
            self.code_edit.clear()
            self.copy_button.setEnabled(False)

    def _copy_selected_code_with_feedback(self):
        """Copies the currently displayed code and provides visual feedback."""
        code_to_copy = self.code_edit.toPlainText()
        if not code_to_copy:
             logger.warning("Attempted to copy empty code from CodeViewerWindow.")
             return
        try:
            clipboard = QApplication.clipboard()
            if not clipboard: raise RuntimeError("Clipboard not accessible.")
            clipboard.setText(code_to_copy)
            logger.info("Copied code from viewer to clipboard.")

            # Change icon to checkmark
            if not CHECK_ICON.isNull(): self.copy_button.setIcon(CHECK_ICON)
            self.copy_button.setEnabled(False) # Briefly disable
            # Reset icon after a delay
            QTimer.singleShot(1500, self._reset_copy_button_icon)

        except Exception as e:
            logger.exception(f"Error copying code from viewer: {e}")
            QMessageBox.warning(self, "Copy Error", f"Could not copy code to clipboard:\n{e}")

    def _reset_copy_button_icon(self):
        """Resets the copy button icon and enables it if code is present."""
        if not COPY_ICON.isNull(): self.copy_button.setIcon(COPY_ICON)
        # Re-enable only if there's code displayed
        self.copy_button.setEnabled(bool(self.code_edit.toPlainText()))

    def showEvent(self, event):
        """Ensure the first item is selected when shown if list is populated."""
        super().showEvent(event)
        if self.list_widget.count() > 0 and self.list_widget.currentItem() is None:
            self.list_widget.setCurrentRow(0)
        elif self.list_widget.currentItem():
             self._display_selected_code(self.list_widget.currentItem(), None)
        self.activateWindow(); self.raise_()

    # Override closeEvent to just hide the window instead of deleting it
    def closeEvent(self, event):
         self.hide()
         event.ignore() # Prevent the dialog from being destroyed

# --- Personality Editor Dialog ---
class EditPersonalityDialog(QDialog):
    """Dialog window for editing the AI's personality/system prompt."""
    def __init__(self, current_prompt: Optional[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Edit Personality / System Prompt")
        self.setObjectName("PersonalityDialog")
        self.setMinimumSize(550, 400)
        self.setModal(True) # Make modal to focus user interaction

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Use the default font (now SansSerif)
        dialog_font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE)
        label_font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE - 1)

        info_label = QLabel(
            "Enter the system prompt or personality instructions for the AI below.\n"
            "Leave empty to use the default behavior."
        )
        info_label.setFont(label_font)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #9aabbf; margin-bottom: 5px;")
        layout.addWidget(info_label)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setObjectName("PersonalityPromptEdit")
        self.prompt_edit.setFont(dialog_font) # Apply default font
        self.prompt_edit.setPlaceholderText("e.g., You are a helpful assistant specializing in Python...")
        self.prompt_edit.setPlainText(current_prompt or "")
        self.prompt_edit.setAcceptRichText(False)
        self.prompt_edit.setMinimumHeight(150)
        layout.addWidget(self.prompt_edit)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept) # Connect OK to accept slot
        self.button_box.rejected.connect(self.reject) # Connect Cancel to reject slot
        layout.addWidget(self.button_box)

        self.setLayout(layout)

    def get_prompt_text(self) -> str:
        """Returns the text entered in the prompt editor (called after exec)."""
        # Ensure called only after dialog is accepted
        return self.prompt_edit.toPlainText().strip()

    def showEvent(self, event):
        """Set focus to the text editor when shown."""
        super().showEvent(event)
        self.prompt_edit.setFocus()

# --- Session Manager Dialog ---
class SessionManagerDialog(QDialog):
    """Dialog for managing saved chat sessions."""
    # No external signals needed, interacts directly with ChatManager

    def __init__(self, chat_manager: ChatManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        if not chat_manager:
            raise ValueError("SessionManagerDialog requires a valid ChatManager instance.")
        self.chat_manager = chat_manager
        # Access session_service via chat_manager
        self.session_service = getattr(chat_manager, '_session_service', None)
        if not self.session_service or not isinstance(self.session_service, SessionService):
             raise TypeError("ChatManager instance does not have a valid SessionService.")

        self.setWindowTitle("Manage Sessions")
        self.setObjectName("SessionManagerDialog")
        self.setMinimumSize(500, 400) # Adjusted size
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Use default font
        dialog_font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE)
        label_font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE - 1)

        list_label = QLabel("Saved Sessions:")
        list_label.setFont(label_font)
        layout.addWidget(list_label)

        self.session_list_widget = QListWidget()
        self.session_list_widget.setFont(dialog_font) # Apply default font
        self.session_list_widget.setObjectName("SessionList")
        self.session_list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.session_list_widget.itemSelectionChanged.connect(self._update_button_states)
        self.session_list_widget.itemDoubleClicked.connect(self._handle_load) # Double-click to load
        layout.addWidget(self.session_list_widget, 1) # Stretchable list

        # Buttons Layout
        button_layout = QHBoxLayout()

        self.load_button = QPushButton("Load")
        self.load_button.setToolTip("Load the selected session")
        self.load_button.clicked.connect(self._handle_load)
        button_layout.addWidget(self.load_button)

        self.save_as_button = QPushButton("Save Current As...")
        self.save_as_button.setToolTip("Save the current chat with a new name")
        self.save_as_button.clicked.connect(self._handle_save_as)
        # Enable Save As always, as it applies to the *current* chat, not selected list item
        self.save_as_button.setEnabled(True)
        button_layout.addWidget(self.save_as_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setToolTip("Delete the selected session")
        self.delete_button.clicked.connect(self._handle_delete)
        button_layout.addWidget(self.delete_button)

        button_layout.addStretch() # Push buttons left

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject) # Close the dialog
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        self.refresh_list() # Load initial list
        self._update_button_states() # Set initial button states

    def _get_selected_filepath(self) -> Optional[str]:
        """Gets the full filepath stored in the selected list item."""
        selected_items = self.session_list_widget.selectedItems()
        if not selected_items:
            return None
        item = selected_items[0]
        filepath = item.data(Qt.ItemDataRole.UserRole)
        return filepath if isinstance(filepath, str) else None

    def refresh_list(self):
        """Refreshes the list of sessions from the service."""
        current_selection_path = self._get_selected_filepath()
        self.session_list_widget.clear()
        logger.info("Refreshing session list in dialog...")
        try:
            # Get full paths, but display only filenames
            session_filepaths = self.session_service.list_sessions()
            if not session_filepaths:
                no_sessions_item = QListWidgetItem("No saved sessions found.")
                no_sessions_item.setFlags(no_sessions_item.flags() & ~Qt.ItemFlag.ItemIsSelectable) # Make unselectable
                self.session_list_widget.addItem(no_sessions_item)
                self.session_list_widget.setEnabled(False)
            else:
                self.session_list_widget.setEnabled(True)
                new_index_to_select = -1
                for index, filepath in enumerate(session_filepaths):
                    filename = os.path.basename(filepath)
                    item = QListWidgetItem(filename)
                    item.setData(Qt.ItemDataRole.UserRole, filepath) # Store full path
                    item.setToolTip(filepath) # Show full path on hover
                    self.session_list_widget.addItem(item)
                    if filepath == current_selection_path:
                        new_index_to_select = index

                # Reselect previously selected item if it still exists
                if new_index_to_select != -1:
                     self.session_list_widget.setCurrentRow(new_index_to_select)

        except Exception as e:
            logger.exception("Error refreshing session list:")
            self.session_list_widget.clear()
            error_item = QListWidgetItem("Error loading sessions.")
            error_item.setFlags(error_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.session_list_widget.addItem(error_item)
            self.session_list_widget.setEnabled(False)
        finally:
            self._update_button_states()


    def _update_button_states(self):
        """Enable/disable Load and Delete based on list selection."""
        selected_path = self._get_selected_filepath()
        has_valid_selection = selected_path is not None
        self.load_button.setEnabled(has_valid_selection)
        self.delete_button.setEnabled(has_valid_selection)
        # Save As is always enabled (applies to current chat)

    def _handle_load(self):
        """Handles the Load button click."""
        filepath = self._get_selected_filepath()
        if filepath:
            logger.info(f"SessionManagerDialog: Requesting load of '{filepath}'")
            try:
                # Directly call ChatManager method
                self.chat_manager.load_chat_session(filepath)
                self.accept() # Close dialog on successful action trigger
            except Exception as e:
                 logger.exception(f"Error during load request for {filepath}")
                 QMessageBox.warning(self, "Load Error", f"Could not initiate session load:\n{e}")
        else:
            logger.warning("Load clicked with no session selected.")

    def _handle_save_as(self):
        """Handles the Save Current As... button click."""
        logger.info("SessionManagerDialog: Requesting Save As...")
        suggested_name = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Save Current Session As",
                os.path.join(CONVERSATIONS_DIR, suggested_name),
                "JSON Session Files (*.json);;All Files (*)"
            )
            if filepath:
                 if not filepath.lower().endswith(".json"): filepath += ".json"
                 logger.info(f"Attempting to save current session as: {filepath}")
                 # Directly call ChatManager method
                 success = self.chat_manager.save_current_chat_session(filepath)
                 if success:
                     self.refresh_list() # Refresh list to show the new file
                     QMessageBox.information(self, "Save Successful", f"Session saved as:\n{os.path.basename(filepath)}")
                     # Keep dialog open after Save As? Or close? Keep open for now.
                     # self.accept()
                 else:
                      # Error message likely shown by ChatManager signal, but add fallback
                      QMessageBox.warning(self, "Save Failed", "Failed to save the current session.")
            else:
                 logger.info("Save As dialog cancelled.")

        except Exception as e:
            logger.exception("Error during Save As process:")
            QMessageBox.critical(self, "Save Error", f"An error occurred during Save As:\n{e}")


    def _handle_delete(self):
        """Handles the Delete button click."""
        filepath = self._get_selected_filepath()
        if filepath:
            filename = os.path.basename(filepath)
            confirm = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Are you sure you want to permanently delete this session?\n\n'{filename}'",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if confirm == QMessageBox.StandardButton.Yes:
                logger.info(f"SessionManagerDialog: Requesting deletion of '{filepath}'")
                try:
                    # Directly call ChatManager method
                    success = self.chat_manager.delete_chat_session(filepath)
                    if success:
                        self.refresh_list() # Refresh the list after deletion
                    else:
                        # Error message likely shown by ChatManager signal, but add fallback
                        QMessageBox.warning(self, "Delete Failed", f"Failed to delete session:\n'{filename}'")
                except Exception as e:
                    logger.exception(f"Error during delete request for {filepath}")
                    QMessageBox.warning(self, "Delete Error", f"Could not initiate session deletion:\n{e}")
        else:
            logger.warning("Delete clicked with no session selected.")

    def showEvent(self, event):
        """Refresh list when dialog is shown."""
        super().showEvent(event)
        self.refresh_list()

# --- RAG Viewer Dialog ---
class RAGViewerDialog(QDialog):
    """A dialog to view documents and chunks indexed in the RAG database."""

    # Constants for data roles in tree widget
    IS_DOCUMENT_ROLE = Qt.ItemDataRole.UserRole + 1
    FILEPATH_ROLE = Qt.ItemDataRole.UserRole + 2
    CHUNK_INDEX_ROLE = Qt.ItemDataRole.UserRole + 3

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("RAG Content Viewer")
        self.setObjectName("RAGViewerDialog")
        self.setMinimumSize(800, 600)
        self.setModal(True)

        self._all_metadata: List[Dict[str, Any]] = []

        # --- Font Setup ---
        # Use default font (SansSerif)
        content_font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE)
        label_font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE - 1)

        # Main layout
        layout = QVBoxLayout(self)

        # Top Info Label
        self.info_label = QLabel("Indexed Documents and Chunks:")
        self.info_label.setFont(label_font)
        layout.addWidget(self.info_label)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self.splitter, 1) # Give stretch factor

        # --- Left: Tree of Documents and Chunks ---
        self.tree_widget = QTreeWidget()
        self.tree_widget.setObjectName("RAGTreeWidget")
        self.tree_widget.setHeaderLabels(["Indexed Item", "Chunks/Details"])
        self.tree_widget.setColumnWidth(0, 300) # Adjust column width
        self.tree_widget.itemSelectionChanged.connect(self._display_selected_content)
        self.splitter.addWidget(self.tree_widget) # Uses default font

        # --- Right: Chunk Content Display ---
        self.content_edit = QTextEdit()
        self.content_edit.setObjectName("RAGContentViewerEdit")
        self.content_edit.setReadOnly(True)
        self.content_edit.setFont(content_font) # Apply default font
        self.content_edit.setWordWrapMode(QTextOption.WrapMode.WordWrap) # Wrap content

        self.splitter.addWidget(self.content_edit)
        self.splitter.setSizes([350, 450]) # Adjust initial sizes

        # --- Bottom Buttons ---
        button_layout = QHBoxLayout()
        self.copy_chunk_button = QPushButton(" Copy Chunk")
        self.copy_chunk_button.setToolTip("Copy the content of the selected chunk")
        if not COPY_ICON.isNull(): self.copy_chunk_button.setIcon(COPY_ICON)
        self.copy_chunk_button.clicked.connect(self._copy_selected_chunk_with_feedback)
        self.copy_chunk_button.setEnabled(False) # Disabled initially
        button_layout.addWidget(self.copy_chunk_button)

        button_layout.addStretch()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Reload the RAG content list")
        self.refresh_button.clicked.connect(self.accept) # Simplest: close and reopen to refresh
        button_layout.addWidget(self.refresh_button)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

    def load_data(self, metadata_list: List[Dict[str, Any]]):
        """Populates the tree widget with documents and chunks."""
        self.tree_widget.clear()
        self.content_edit.clear()
        self._all_metadata = metadata_list # Store the raw data if needed later
        self.copy_chunk_button.setEnabled(False)

        if not metadata_list:
            self.info_label.setText("RAG Database is empty or could not be loaded.")
            return

        self.info_label.setText(f"Found {len(metadata_list)} total chunks.")

        # Group chunks by source document path
        docs = defaultdict(list)
        for i, meta in enumerate(metadata_list):
            source_path = meta.get("source", "Unknown Source")
            docs[source_path].append(i) # Store index of the metadata in the original list

        # Populate the tree
        for source_path, chunk_indices in sorted(docs.items()):
            filename = os.path.basename(source_path) if source_path != "Unknown Source" else "Unknown Source"
            doc_item = QTreeWidgetItem(self.tree_widget)
            doc_item.setText(0, filename)
            doc_item.setText(1, f"{len(chunk_indices)} chunks")
            doc_item.setToolTip(0, source_path)
            # Mark as a document node and store path
            doc_item.setData(0, self.IS_DOCUMENT_ROLE, True)
            doc_item.setData(0, self.FILEPATH_ROLE, source_path)

            # Add child items for each chunk
            for idx in sorted(chunk_indices):
                meta = metadata_list[idx]
                chunk_idx = meta.get("chunk_index", "?")
                start_idx = meta.get("start_index", "?")
                chunk_label = f"Chunk {chunk_idx}"
                chunk_detail = f"Start: {start_idx}"

                chunk_item = QTreeWidgetItem(doc_item)
                chunk_item.setText(0, chunk_label)
                chunk_item.setText(1, chunk_detail)
                chunk_item.setToolTip(0, f"Chunk {chunk_idx} from {filename}")
                # Mark as not a document and store original list index
                chunk_item.setData(0, self.IS_DOCUMENT_ROLE, False)
                chunk_item.setData(0, self.CHUNK_INDEX_ROLE, idx)

        self.tree_widget.expandAll() # Expand all items initially
        self.tree_widget.resizeColumnToContents(0)
        self.tree_widget.resizeColumnToContents(1)
        logger.info(f"RAGViewerDialog populated with {len(docs)} documents.")

    def _display_selected_content(self):
        """Displays the content of the selected chunk."""
        self._reset_copy_button_icon()
        selected_items = self.tree_widget.selectedItems()
        if not selected_items:
            self.content_edit.clear()
            self.copy_chunk_button.setEnabled(False)
            return

        item = selected_items[0]
        is_document = item.data(0, self.IS_DOCUMENT_ROLE)
        chunk_index = item.data(0, self.CHUNK_INDEX_ROLE)

        if is_document or chunk_index is None:
            # Document node selected, show summary or clear
            filepath = item.data(0, self.FILEPATH_ROLE)
            num_chunks = item.childCount()
            self.content_edit.setPlainText(
                f"Document: {item.text(0)}\n"
                f"Full Path: {filepath}\n"
                f"Number of Chunks: {num_chunks}\n\n"
                "(Select a specific chunk node to view its content)"
            )
            self.copy_chunk_button.setEnabled(False)
        elif 0 <= chunk_index < len(self._all_metadata):
            # Chunk node selected
            metadata = self._all_metadata[chunk_index]
            content = metadata.get("content", "[Content not found in metadata]")
            self.content_edit.setPlainText(content)
            self.copy_chunk_button.setEnabled(True)
        else:
            # Invalid state
            self.content_edit.clear()
            self.copy_chunk_button.setEnabled(False)
            logger.warning(f"Invalid chunk index selected in RAGViewerDialog: {chunk_index}")

    def _copy_selected_chunk_with_feedback(self):
        """Copies the currently displayed chunk content."""
        selected_items = self.tree_widget.selectedItems()
        if not selected_items: return

        item = selected_items[0]
        is_document = item.data(0, self.IS_DOCUMENT_ROLE)
        chunk_index = item.data(0, self.CHUNK_INDEX_ROLE)

        if is_document or chunk_index is None:
            logger.warning("Copy chunk requested but a document node is selected.")
            return

        if 0 <= chunk_index < len(self._all_metadata):
            metadata = self._all_metadata[chunk_index]
            code_to_copy = metadata.get("content", "")
            if not code_to_copy:
                 logger.warning("Attempted to copy empty chunk from RAGViewerDialog.")
                 return
            try:
                clipboard = QApplication.clipboard()
                if not clipboard: raise RuntimeError("Clipboard not accessible.")
                clipboard.setText(code_to_copy)
                logger.info("Copied chunk from RAG viewer to clipboard.")

                # Change icon to checkmark
                if not CHECK_ICON.isNull(): self.copy_chunk_button.setIcon(CHECK_ICON)
                self.copy_chunk_button.setEnabled(False) # Briefly disable
                QTimer.singleShot(1500, self._reset_copy_button_icon)
            except Exception as e:
                logger.exception(f"Error copying chunk from RAG viewer: {e}")
                QMessageBox.warning(self, "Copy Error", f"Could not copy chunk content:\n{e}")
        else:
            logger.error(f"Invalid chunk index ({chunk_index}) during copy operation.")

    def _reset_copy_button_icon(self):
        """Resets the copy button icon and enables it if a chunk is selected."""
        if not COPY_ICON.isNull(): self.copy_chunk_button.setIcon(COPY_ICON)
        # Re-enable only if a chunk is currently selected
        selected_items = self.tree_widget.selectedItems()
        is_chunk_selected = False
        if selected_items:
            item = selected_items[0]
            is_document = item.data(0, self.IS_DOCUMENT_ROLE)
            chunk_index = item.data(0, self.CHUNK_INDEX_ROLE)
            if not is_document and chunk_index is not None:
                is_chunk_selected = True
        self.copy_chunk_button.setEnabled(is_chunk_selected)

    def showEvent(self, event):
        """Select first item if available when dialog is shown."""
        super().showEvent(event)
        if self.tree_widget.topLevelItemCount() > 0:
             first_item = self.tree_widget.topLevelItem(0)
             self.tree_widget.setCurrentItem(first_item)
        self.activateWindow(); self.raise_()