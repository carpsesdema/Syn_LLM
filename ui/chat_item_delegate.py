# SynaChat/ui/chat_item_delegate.py
# UPDATED FILE - Removed incorrect PaintContext usage causing crash

import logging
import base64
import html
import hashlib
from typing import Optional, Dict, Any, Tuple

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QApplication, QStyleOptionViewItem
# Removed QPalette import as PaintContext is removed
from PyQt6.QtGui import QPainter, QColor, QFontMetrics, QTextDocument, QPixmap, QImage, QFont, QImageReader
from PyQt6.QtCore import QModelIndex, QRect, QPoint, QSize, Qt, QObject, QByteArray # Added QByteArray, QImageReader

from core.models import ChatMessage, USER_ROLE, MODEL_ROLE, SYSTEM_ROLE, ERROR_ROLE
from utils.constants import CHAT_FONT_FAMILY, CHAT_FONT_SIZE
# Assuming ChatListModel is in the same directory or accessible
from .chat_list_model import ChatListModel, ChatMessageRole

# --- Dependency for Markdown ---
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    MARKDOWN_AVAILABLE = False

logger = logging.getLogger(__name__)

# --- Constants for Delegate ---
BUBBLE_PADDING_V = 8
BUBBLE_PADDING_H = 12
BUBBLE_MARGIN_V = 4
BUBBLE_MARGIN_H = 10 # Margin from list view edge
BUBBLE_RADIUS = 15
TAIL_WIDTH = 10      # Currently unused, but kept for potential future bubble tails
TAIL_HEIGHT = 10     # Currently unused
IMAGE_PADDING = 5
MAX_IMAGE_WIDTH = 250 # Smaller max width for delegate rendering
MAX_IMAGE_HEIGHT = 250
MIN_BUBBLE_WIDTH = 50 # Minimum width for a bubble

# --- Colors (can be moved to constants or theme manager) ---
USER_BUBBLE_COLOR = QColor("#0b93f6") # Blue
USER_TEXT_COLOR = QColor(Qt.GlobalColor.white)
AI_BUBBLE_COLOR = QColor("#3c3f41")   # Dark Grey
AI_TEXT_COLOR = QColor("#dcdcdc")     # Light Grey
SYSTEM_BUBBLE_COLOR = QColor("#4a4e51") # Medium Grey
SYSTEM_TEXT_COLOR = QColor("#aabbcc")  # Lighter Grey/Blue
ERROR_BUBBLE_COLOR = QColor("#6e3b3b")  # Dark Red
ERROR_TEXT_COLOR = QColor("#ffcccc")   # Light Red
CODE_BG_COLOR = QColor("#282c34")      # Matches QSS 'pre'

class ChatItemDelegate(QStyledItemDelegate):
    """
    Custom delegate for rendering ChatMessage objects in a QListView.
    Draws chat bubbles with text (including basic Markdown/HTML) and images,
    aligned based on user/agent role.
    """
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE)
        self._font_metrics = QFontMetrics(self._font)
        # Cache: (content_hash, width_constraint, is_streaming) -> QTextDocument
        self._text_doc_cache: Dict[Tuple[str, int, bool], QTextDocument] = {}
        logger.info("ChatItemDelegate initialized.")

    def clearCache(self):
        logger.debug("Clearing ChatItemDelegate cache.")
        self._text_doc_cache.clear()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        """Paints a single chat message item."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        message = index.data(ChatMessageRole)
        if not isinstance(message, ChatMessage):
            # Fallback for unexpected data
            super().paint(painter, option, index)
            painter.restore()
            return

        is_user = (message.role == USER_ROLE)
        bubble_color, text_color = self._get_colors(message.role) # Text color primarily set via HTML now

        # Calculate available width for content within the item rect margins
        available_content_width = option.rect.width() - 2 * BUBBLE_MARGIN_H
        if available_content_width <= 0: available_content_width = 1 # Ensure positive width

        # Calculate the size the bubble content *needs* based on text/images
        required_content_size = self._calculate_content_size(message, available_content_width)

        # Calculate the final bubble rectangle based on required size and alignment
        bubble_rect = self._get_bubble_rect(option.rect, required_content_size, is_user)

        # --- Draw Bubble ---
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bubble_color)
        painter.drawRoundedRect(bubble_rect, BUBBLE_RADIUS, BUBBLE_RADIUS)

        # --- Draw Content (Text and Images) ---
        # Define the inner rect for content placement, respecting bubble padding
        content_placement_rect = bubble_rect.adjusted(BUBBLE_PADDING_H, BUBBLE_PADDING_V,
                                                      -BUBBLE_PADDING_H, -BUBBLE_PADDING_V)
        current_y = content_placement_rect.top()
        content_width = content_placement_rect.width()

        # 1. Draw Text
        if message.text:
            text_doc = self._get_prepared_text_document(message, content_width)
            text_height = int(text_doc.size().height()) # Use document's calculated height

            # Check if text fits vertically
            if current_y + text_height <= content_placement_rect.bottom() + 1: # Allow slight rounding errors
                painter.save()
                # Translate painter to the top-left corner for text drawing
                painter.translate(content_placement_rect.left(), current_y)
                # Set clip rect to prevent drawing outside the designated area (optional but safer)
                # painter.setClipRect(0, 0, content_width, text_height)

                # REMOVED PaintContext usage
                # ctx = QTextDocument.PaintContext()
                # ctx.palette.setColor(QPalette.ColorRole.Text, text_color) # Ensure text color is set
                # text_doc.drawContents(painter, ctx) # Use context for color

                # Draw directly, color is handled by HTML
                text_doc.drawContents(painter)

                painter.restore()
                current_y += text_height # Move down for next element
            else:
                 logger.warning("Calculated text height exceeds available bubble space.")


        # 2. Draw Images (logic remains same)
        if message.has_images:
            if message.text: # Add padding if text was present
                current_y += IMAGE_PADDING

            for img_part in message.image_parts:
                pixmap = self._get_image_pixmap(img_part)
                if pixmap and not pixmap.isNull():
                    # Scale pixmap to fit content width and max dimensions
                    target_width = min(pixmap.width(), content_width, MAX_IMAGE_WIDTH)
                    scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
                    if scaled_pixmap.height() > MAX_IMAGE_HEIGHT:
                        scaled_pixmap = scaled_pixmap.scaledToHeight(MAX_IMAGE_HEIGHT, Qt.TransformationMode.SmoothTransformation)

                    # Center image horizontally within the content area
                    img_x = content_placement_rect.left() + (content_width - scaled_pixmap.width()) // 2

                    # Check if image fits vertically
                    if current_y + scaled_pixmap.height() <= content_placement_rect.bottom() + 1:
                        img_rect = QRect(QPoint(img_x, current_y), scaled_pixmap.size())
                        painter.drawPixmap(img_rect.topLeft(), scaled_pixmap)
                        current_y += scaled_pixmap.height() + IMAGE_PADDING # Move Y down
                    else:
                        logger.warning("Next image too tall to fit in remaining bubble rect.")
                        # Optionally draw an error placeholder for the image here
                        break # Stop drawing images if one doesn't fit

        # Draw selection highlight if needed
        if option.state & QStyle.StateFlag.State_Selected:
            highlight_color = option.palette.highlight().color()
            highlight_color.setAlpha(80) # Semi-transparent highlight
            painter.fillRect(option.rect, highlight_color)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Provides the total size needed for the item row."""
        message = index.data(ChatMessageRole)
        if not isinstance(message, ChatMessage):
            return super().sizeHint(option, index)

        # Calculate available width for content within the item rect margins
        available_content_width = option.rect.width() - 2 * BUBBLE_MARGIN_H
        if available_content_width <= 0: available_content_width = 1

        # Get the size required by the content itself
        content_size = self._calculate_content_size(message, available_content_width)

        # Add vertical margins to the content height for the final item height
        final_height = content_size.height() + 2 * BUBBLE_MARGIN_V

        # The item width should take the full available width of the view column
        final_width = option.rect.width()

        return QSize(final_width, final_height)

    # --- Helper Methods ---

    def _get_colors(self, role: str) -> tuple[QColor, QColor]:
        """Returns bubble and text color based on role."""
        if role == USER_ROLE: return USER_BUBBLE_COLOR, USER_TEXT_COLOR
        if role == SYSTEM_ROLE: return SYSTEM_BUBBLE_COLOR, SYSTEM_TEXT_COLOR
        if role == ERROR_ROLE: return ERROR_BUBBLE_COLOR, ERROR_TEXT_COLOR
        # Default to AI/Model role
        return AI_BUBBLE_COLOR, AI_TEXT_COLOR

    def _get_bubble_rect(self, item_rect: QRect, content_size: QSize, is_user: bool) -> QRect:
        """Calculates the actual bubble rectangle based on content size and alignment."""
        bubble_width = content_size.width()
        bubble_height = content_size.height()

        # Calculate available horizontal space *after* accounting for margins
        available_width = item_rect.width() - 2 * BUBBLE_MARGIN_H

        if is_user:
            # Align right: Start bubble at (right edge - margin - bubble width)
            bubble_x = item_rect.right() - BUBBLE_MARGIN_H - bubble_width
        else:
            # Align left: Start bubble at left edge + margin
            bubble_x = item_rect.left() + BUBBLE_MARGIN_H

        # Vertical position starts after top margin
        bubble_y = item_rect.top() + BUBBLE_MARGIN_V

        # Ensure bubble doesn't have zero or negative width/height
        if bubble_width <= 0: bubble_width = MIN_BUBBLE_WIDTH
        if bubble_height <= 0: bubble_height = self._font_metrics.height() + 2 * BUBBLE_PADDING_V

        return QRect(bubble_x, bubble_y, bubble_width, bubble_height)

    def _calculate_content_size(self, message: ChatMessage, available_width: int) -> QSize:
        """
        Calculates the size needed for the bubble content (text + images),
        constrained by the available width.
        Returns the required size (width, height) *including* internal bubble padding.
        """
        total_height = 0
        actual_content_width = 0 # Track the widest element needs
        # Constrain the width *inside* the padding
        inner_width_constraint = max(1, available_width - 2 * BUBBLE_PADDING_H)

        # 1. Calculate Text Size
        if message.text:
            text_doc = self._get_prepared_text_document(message, inner_width_constraint)
            text_size = text_doc.size() # Size based on the constrained width
            total_height += int(text_size.height())
            # Actual width used by text is its ideal width, capped by the constraint
            actual_content_width = max(actual_content_width, int(min(text_size.width(), inner_width_constraint)))

        # 2. Calculate Image Sizes
        if message.has_images:
            if message.text: total_height += IMAGE_PADDING # Padding between text and first image
            image_count = 0
            for img_part in message.image_parts:
                pixmap = self._get_image_pixmap(img_part)
                if pixmap and not pixmap.isNull():
                    if image_count > 0: total_height += IMAGE_PADDING # Padding between images

                    # Scale pixmap to fit inner content width and max dimensions
                    target_width = min(pixmap.width(), inner_width_constraint, MAX_IMAGE_WIDTH)
                    scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
                    if scaled_pixmap.height() > MAX_IMAGE_HEIGHT:
                         scaled_pixmap = scaled_pixmap.scaledToHeight(MAX_IMAGE_HEIGHT, Qt.TransformationMode.SmoothTransformation)

                    total_height += scaled_pixmap.height()
                    actual_content_width = max(actual_content_width, scaled_pixmap.width())
                    image_count += 1
                else:
                    # Placeholder for image error? Add height for a line of text.
                    if image_count > 0: total_height += IMAGE_PADDING
                    error_text_height = self._font_metrics.height()
                    total_height += error_text_height
                    actual_content_width = max(actual_content_width, self._font_metrics.horizontalAdvance("[Image Error]"))
                    image_count += 1


        # Add bubble padding to the calculated content dimensions
        final_height = total_height + 2 * BUBBLE_PADDING_V
        final_width = actual_content_width + 2 * BUBBLE_PADDING_H

        # Enforce minimum bubble dimensions
        final_width = max(final_width, MIN_BUBBLE_WIDTH)
        min_bubble_height = self._font_metrics.height() + 2 * BUBBLE_PADDING_V
        final_height = max(final_height, min_bubble_height)

        # Ensure non-negative dimensions before returning
        final_width = max(1, final_width)
        final_height = max(1, final_height)

        return QSize(final_width, final_height)

    def _get_prepared_text_document(self, message: ChatMessage, width_constraint: int) -> QTextDocument:
        """Creates or retrieves a cached QTextDocument for the message text."""
        # Ensure metadata exists before accessing it
        is_streaming = (message.metadata is not None) and message.metadata.get("is_streaming", False)
        # Use empty string hash if text is None/empty to avoid errors
        text_content = message.text if message.text else ""
        content_hash = hashlib.sha256(text_content.encode('utf-8')).hexdigest()
        cache_key = (content_hash, width_constraint, is_streaming)

        cached_doc = self._text_doc_cache.get(cache_key)
        if cached_doc:
            # Ensure width is set correctly on cached doc just in case
            constrained_width = max(width_constraint, 1)
            if cached_doc.textWidth() != constrained_width:
                 cached_doc.setTextWidth(constrained_width)
            return cached_doc

        # --- Create New Document ---
        doc = QTextDocument()
        doc.setDefaultFont(self._font)
        doc.setDocumentMargin(0) # Margin handled by bubble padding

        _, text_color = self._get_colors(message.role)
        html_content = self._prepare_html(text_content, text_color, is_streaming) # Use text_content
        doc.setHtml(html_content)

        # Set the width constraint *before* calculating size
        doc.setTextWidth(max(width_constraint, 1))

        # Store in cache
        self._text_doc_cache[cache_key] = doc
        return doc

    def _prepare_html(self, text: str, text_color: QColor, is_streaming: bool) -> str:
        """Converts message text to styled HTML for QTextDocument."""
        if not text: return ""

        # Basic styling for the body
        body_style = f'color:{text_color.name()}; margin: 0; padding: 0;'

        # For streaming, just escape and handle newlines
        if is_streaming:
            content = html.escape(text).replace('\n', '<br/>')
        # For finalized messages, attempt markdown conversion
        else:
            if MARKDOWN_AVAILABLE:
                try:
                    # Use extensions for common features like code fences and tables
                    # REMOVED 'codehilite' - requires Pygments
                    content = markdown.markdown(text, extensions=['fenced_code', 'nl2br', 'tables', 'sane_lists'])
                except Exception as e:
                    logger.error(f"Markdown conversion failed: {e}. Falling back to plain text.")
                    content = html.escape(text).replace('\n', '<br/>')
            else:
                # Fallback if markdown library isn't available
                content = html.escape(text).replace('\n', '<br/>')

        # Construct final HTML (ensure body tag exists)
        # Added basic table styling
        styled_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <style>
            body {{ {body_style} }}
            p {{ margin: 0 0 5px 0; padding: 0; }}
            ul, ol {{ margin: 0 0 5px 20px; padding: 0; }}
            li {{ margin-bottom: 2px; }}
            pre {{
                background-color: {CODE_BG_COLOR.name()};
                border: 1px solid {CODE_BG_COLOR.darker(120).name()};
                padding: 8px;
                margin: 4px 0;
                border-radius: 4px;
                overflow-x: auto;
                white-space: pre;
                font-family: "Consolas", "Monaco", "Courier New", monospace;
                font-size: {self._font.pointSize()}pt;
                color: {AI_TEXT_COLOR.name()};
            }}
            code {{ /* Inline code */
                 background-color: {CODE_BG_COLOR.darker(110).name()};
                 padding: 1px 3px;
                 border-radius: 3px;
                 font-family: "Consolas", "Monaco", "Courier New", monospace;
                 font-size: {int(self._font.pointSize() * 0.95)}pt;
            }}
            table {{ border-collapse: collapse; margin: 5px 0; color: {text_color.name()}; }}
            th, td {{ border: 1px solid {text_color.darker(150).name()}; padding: 4px 6px; }}
            th {{ background-color: {AI_BUBBLE_COLOR.lighter(110).name()}; }}
        </style>
        </head>
        <body>
            {content}
        </body>
        </html>
        """
        return styled_html


    def _get_image_pixmap(self, image_part: Dict[str, Any]) -> Optional[QPixmap]:
        """Decodes base64 image data and returns a QPixmap."""
        base64_data = image_part.get("data")
        if not base64_data:
            logger.warning("Attempted to decode image, but 'data' key is missing or empty.")
            return None
        try:
            # Ensure padding is correct for base64 decoding
            missing_padding = len(base64_data) % 4
            if missing_padding:
                base64_data += '=' * (4 - missing_padding)

            image_bytes = base64.b64decode(base64_data)
            qimage = QImage()
            if qimage.loadFromData(image_bytes):
                return QPixmap.fromImage(qimage)
            else:
                # Use QByteArray for QImageReader
                byte_array = QByteArray(image_bytes)
                reader = QImageReader(byte_array)
                img_format_bytes = reader.format() # Returns QByteArray
                if img_format_bytes and not img_format_bytes.isEmpty():
                    logger.warning(f"QImage.loadFromData failed, but format detected as: {img_format_bytes.data().decode()}")
                else:
                    logger.error("QImage.loadFromData failed and could not detect image format.")
                return None
        except base64.binascii.Error as e_b64:
             logger.error(f"Base64 decoding error in delegate: {e_b64}")
             return None
        except Exception as e:
            logger.error(f"Error decoding/loading image in delegate: {e}", exc_info=True)
            return None