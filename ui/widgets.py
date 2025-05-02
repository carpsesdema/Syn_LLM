# SynChat/ui/widgets.py
# UPDATED FILE - Display images in ChatBubbleWidget

import sys
import os
import re
import logging
import base64 # Added for image decoding
from typing import Optional, List, Dict, Any # Added Dict, Any
import html # For escaping code content

# --- Dependency for Markdown ---
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False
    logging.warning("ChatBubbleWidget: 'Markdown' library not found. Install: pip install Markdown")

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, # Changed QLabel to QTextEdit
    QSizePolicy, QApplication, QLabel # Added QLabel for image display
)
from PyQt6.QtGui import (
    QFont, QIcon, QPalette, QFontDatabase, QClipboard, QTextOption, # Added QTextOption
    QPixmap, QImage # Added QPixmap, QImage
)
# --- MODIFIED: Import QSvgRenderer if needed for complex SVG handling, or rely on QIcon ---
from PyQt6.QtSvg import QSvgRenderer # Keep if direct SVG rendering is needed
from PyQt6.QtCore import Qt, pyqtSignal, QRegularExpression, QTimer, QSize, QByteArray

# --- Local Imports ---
from utils.constants import CHAT_FONT_FAMILY, CHAT_FONT_SIZE, ASSETS_PATH # Use constants for font/paths
from core.models import ChatMessage, USER_ROLE, MODEL_ROLE, SYSTEM_ROLE, ERROR_ROLE

logger = logging.getLogger(__name__)

# --- Helper to load icons ---
def load_icon(filename: str) -> QIcon:
    """Loads an icon from the assets directory."""
    path = os.path.join(ASSETS_PATH, filename)
    if not os.path.exists(path):
        logger.warning(f"Icon not found: {path}")
        return QIcon() # Return empty icon
    icon = QIcon(path)
    if icon.isNull():
         logger.warning(f"Icon loaded but is null: {path}")
    return icon

# --- Icons restored for external import (e.g., by dialogs.py) ---
COPY_ICON = load_icon("copy_icon.svg")
CHECK_ICON = load_icon("checkmark_icon.svg")
# --------------------------------------------------------------


class ChatBubbleWidget(QWidget):
    """
    A widget representing a single chat message bubble.
    Displays text using QTextEdit (for Markdown/code) and images using QLabels.
    """
    # Configuration for image display
    MAX_IMAGE_DISPLAY_WIDTH = 400 # Max width for displayed images in bubble
    MAX_IMAGE_DISPLAY_HEIGHT = 400 # Max height for displayed images

    def __init__(self, message: ChatMessage, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.message = message # Store the ChatMessage object
        self.is_user = (message.role == USER_ROLE)
        self._init_ui()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self) # Vertical layout for text and images
        self.main_layout.setContentsMargins(0, 0, 0, 0) # Let QSS handle bubble margins/padding
        self.main_layout.setSpacing(5) # Spacing between text and image(s)

        self.hbox = QHBoxLayout()
        self.hbox.setContentsMargins(0, 0, 0, 0)
        self.hbox.setSpacing(0)

        # --- Container widget for text and images within the horizontal alignment ---
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(5)
        # Set Object Name for QSS styling based on role
        if self.message.role == USER_ROLE: self.content_widget.setObjectName("UserBubbleContent")
        elif self.message.role == MODEL_ROLE: self.content_widget.setObjectName("AiBubbleContent")
        elif self.message.role == SYSTEM_ROLE: self.content_widget.setObjectName("SystemBubbleContent")
        elif self.message.role == ERROR_ROLE: self.content_widget.setObjectName("ErrorBubbleContent")
        else: self.content_widget.setObjectName("GenericBubbleContent")
        # ------------------------------------------------------------------------

        # --- Text Display (using QTextEdit) ---
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text_edit.document().setDocumentMargin(0)
        self.text_edit.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        # Add text_edit to the vertical content layout
        # Hide it initially if there's no text
        if self.message.text:
            self.content_layout.addWidget(self.text_edit)
        else:
            self.text_edit.setVisible(False)
        # --------------------------------------

        # --- Image Display (using QLabels) ---
        self.image_labels: List[QLabel] = []
        if self.message.has_images:
            for img_part in self.message.image_parts:
                img_label = self._create_image_label(img_part)
                if img_label:
                    self.image_labels.append(img_label)
                    self.content_layout.addWidget(img_label) # Add image below text
        # -----------------------------------

        # Size policy for the main bubble widget
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # Alignment based on role
        if self.is_user:
            self.hbox.addStretch(1)
            self.hbox.addWidget(self.content_widget, 0) # Don't stretch content widget horizontally
        else:
            self.hbox.addWidget(self.content_widget, 0) # Don't stretch content widget horizontally
            self.hbox.addStretch(1)

        self.main_layout.addLayout(self.hbox)
        self.setLayout(self.main_layout)

        # Render text content if it exists
        if self.message.text:
            self._render_text_content()
        # Adjust height after rendering (might need slight delay)
        QTimer.singleShot(10, self._adjust_height_to_content)


    def _create_image_label(self, image_part: Dict[str, Any]) -> Optional[QLabel]:
        """Creates a QLabel to display an image from base64 data."""
        base64_data = image_part.get("data")
        mime_type = image_part.get("mime_type", "image/jpeg") # Assume jpeg if missing
        if not base64_data: return None

        try:
            image_bytes = base64.b64decode(base64_data)
            qimage = QImage()
            loaded = qimage.loadFromData(image_bytes)

            if not loaded or qimage.isNull():
                logger.error("Failed to load image data into QImage.")
                return None

            pixmap = QPixmap.fromImage(qimage)
            if pixmap.isNull():
                 logger.error("Failed to create QPixmap from QImage.")
                 return None

            img_label = QLabel()
            img_label.setPixmap(pixmap.scaled(
                self.MAX_IMAGE_DISPLAY_WIDTH,
                self.MAX_IMAGE_DISPLAY_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
            img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Optional: Add tooltip with original size or filename if available
            # img_label.setToolTip(f"Image ({pixmap.width()}x{pixmap.height()})")
            return img_label

        except Exception as e:
            logger.exception(f"Error creating image label: {e}")
            error_label = QLabel("[Error displaying image]")
            error_label.setStyleSheet("color: red;")
            return error_label

    def _render_text_content(self):
        """Renders the message text content with Markdown and code blocks."""
        if not self.message.text:
            self.text_edit.setVisible(False)
            return

        self.text_edit.setVisible(True)
        raw_text = self.message.text
        processed_text = re.sub(r"^(?=```)", "\n", raw_text, flags=re.MULTILINE)
        processed_text = re.sub(r"(?<=```)$", "\n", processed_text, flags=re.MULTILINE)

        # (Markdown and code block processing logic remains the same)
        final_html_parts = []
        last_original_end = 0
        code_pattern = re.compile(r"```(\w*?)\s*\n?(.*?)```", re.DOTALL)

        for match in code_pattern.finditer(processed_text):
            segment_before_code = processed_text[last_original_end:match.start()]
            if segment_before_code.strip():
                if not segment_before_code.endswith('\n'): segment_before_code += '\n'
                html_segment = self._markdown_to_html(segment_before_code)
                final_html_parts.append(html_segment)

            lang = match.group(1).strip().lower() if match.group(1) else ''
            code_content = match.group(2).strip()
            escaped_code = html.escape(code_content)
            lang_class = f'language-{lang}' if lang else 'language-plaintext'
            code_block_html = f'<pre><code class="{lang_class}">{escaped_code}</code></pre>'
            final_html_parts.append(code_block_html)
            last_original_end = match.end()

        final_segment = processed_text[last_original_end:]
        if final_segment.strip():
            html_final_segment = self._markdown_to_html(final_segment)
            final_html_parts.append(html_final_segment)

        final_html = "".join(final_html_parts)
        final_html = re.sub(r'\s*(<br\s*/?>\s*){2,}', '<br><br>', final_html)
        final_html = final_html.strip()

        self.text_edit.setHtml(final_html)
        # Adjust height after setting HTML - use timer
        QTimer.singleShot(10, self._adjust_height_to_content)

    def _markdown_to_html(self, text: str) -> str:
        """Converts a plain text segment to HTML using Markdown."""
        # (This function remains the same)
        if not MARKDOWN_AVAILABLE:
            escaped_text = html.escape(text)
            return escaped_text.replace('\n', '<br>') # Simple fallback
        try:
            html_content = markdown.markdown(
                text,
                extensions=['nl2br', 'fenced_code', 'tables', 'sane_lists', 'extra']
            )
            return html_content
        except Exception as e:
            logger.error(f"Markdown conversion failed: {e}")
            escaped_text = html.escape(text)
            return escaped_text.replace('\n', '<br>') # Fallback

    def _adjust_height_to_content(self):
        """Adjusts the bubble's overall height to fit text and images."""
        total_height = 0
        spacing = self.content_layout.spacing()

        # --- Calculate Text Height ---
        text_height = 0
        if self.text_edit and self.text_edit.isVisible():
            try:
                self.text_edit.document().setTextWidth(self.text_edit.viewport().width())
                doc_height = self.text_edit.document().size().height()
                estimated_padding = 15 # Buffer for text edit
                target_text_height = int(doc_height + estimated_padding)
                min_text_h = 35
                text_height = max(min_text_h, target_text_height)
                self.text_edit.setFixedHeight(text_height) # Set fixed height for text edit
                total_height += text_height
            except Exception as e:
                logger.error(f"Error calculating text edit height: {e}")
                total_height += 35 # Fallback height

        # --- Calculate Image Height ---
        image_section_height = 0
        num_images = len(self.image_labels)
        if num_images > 0:
            for img_label in self.image_labels:
                # Use sizeHint as pixmap might be scaled
                image_section_height += img_label.sizeHint().height()
            # Add spacing between images/text
            image_section_height += (num_images - 1) * spacing
            if self.text_edit and self.text_edit.isVisible():
                image_section_height += spacing # Add spacing between text and first image

            total_height += image_section_height

        # --- Set Final Height for Content Widget ---
        # Add content layout margins if any (should be 0 based on init)
        margins = self.content_layout.contentsMargins()
        total_height += margins.top() + margins.bottom()

        # Set the height of the container widget that holds text/images
        self.content_widget.setFixedHeight(int(total_height))
        logger.debug(f"Adjust Height: TextH={text_height}, ImgH={image_section_height}, TotalH={total_height}")

        self.updateGeometry() # Update the main bubble widget geometry

    def update_text(self, new_text: str):
        """Updates the text content of the bubble (for streaming)."""
        # This only updates the text part. Images are static once added.
        text_parts = [part for part in self.message.parts if isinstance(part, str)]
        image_parts = [part for part in self.message.parts if isinstance(part, dict)]
        text_parts = [new_text] # Replace existing text with streamed text
        self.message.parts = text_parts + image_parts # Recombine
        self._render_text_content() # Re-render only text

    def update_width(self, max_width):
        """Sets the maximum width for the content container."""
        if max_width <= 0:
             logger.warning(f"Attempted to set invalid max_width: {max_width}")
             return

        # Set max width on the content_widget which contains text/images
        self.content_widget.setMaximumWidth(max_width)
        # Also set on text_edit to ensure text wraps correctly
        self.text_edit.setMaximumWidth(max_width)

        # Setting max width requires re-adjusting height
        QTimer.singleShot(10, self._adjust_height_to_content)