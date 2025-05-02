# SynaChat/ui/chat_item_delegate.py
# UPDATED FILE - Added subtle border to bubbles AND fixed dynamic width calculation

import logging
import base64
import html
import hashlib
from typing import Optional, Dict, Any, Tuple

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QApplication, QStyleOptionViewItem
# Removed QPalette import as PaintContext is removed
from PyQt6.QtGui import (
    QPainter, QColor, QFontMetrics, QTextDocument, QPixmap, QImage, QFont,
    QImageReader, QPen # Added QPen
)
from PyQt6.QtCore import QModelIndex, QRect, QPoint, QSize, Qt, QObject, QByteArray, QUrl # Added QUrl, QImageReader

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
BUBBLE_RADIUS = 12 # Slightly reduced radius for a sleeker look
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
BUBBLE_BORDER_COLOR = QColor("#4f5356") # Consistent subtle border color for all bubbles

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
        # Cache: (content_hash, width_constraint, is_streaming, role) -> QTextDocument # Updated cache key
        self._text_doc_cache: Dict[Tuple[str, int, bool, str], QTextDocument] = {}
        # Cache for images: image_data_hash -> QPixmap
        self._image_pixmap_cache: Dict[str, QPixmap] = {}
        logger.info("ChatItemDelegate initialized.")

    def clearCache(self):
        logger.debug("Clearing ChatItemDelegate cache.")
        self._text_doc_cache.clear()
        self._image_pixmap_cache.clear()

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
        bubble_color, _ = self._get_colors(message.role) # Text color handled by HTML

        # Calculate available width for content within the item rect margins
        available_content_width = option.rect.width() - 2 * BUBBLE_MARGIN_H
        if available_content_width <= 0: available_content_width = 1 # Ensure positive width

        # Calculate the size the bubble content *needs* based on text/images
        required_content_size = self._calculate_content_size(message, available_content_width)

        # Calculate the final bubble rectangle based on required size and alignment
        bubble_rect = self._get_bubble_rect(option.rect, required_content_size, is_user)

        # --- Draw Bubble ---
        # Set pen for the border
        painter.setPen(QPen(BUBBLE_BORDER_COLOR, 1)) # Use defined border color, 1px width
        painter.setBrush(bubble_color)
        painter.drawRoundedRect(bubble_rect, BUBBLE_RADIUS, BUBBLE_RADIUS)
        # --- End Draw Bubble ---


        # --- Draw Content (Text and Images) ---
        # Define the inner rect for content placement, respecting bubble padding
        content_placement_rect = bubble_rect.adjusted(BUBBLE_PADDING_H, BUBBLE_PADDING_V,
                                                      -BUBBLE_PADDING_H, -BUBBLE_PADDING_V)

        # Check for minimum width before proceeding with content drawing
        if content_placement_rect.width() <= 0:
            logger.warning("Content placement rect has zero or negative width. Skipping content draw.")
            painter.restore()
            return

        current_y = content_placement_rect.top()
        # Use the width of the placement rect for content drawing constraints
        content_width_constraint = content_placement_rect.width()

        # 1. Draw Text
        if message.text:
             # Pass the content_width_constraint to get the correctly sized document
            text_doc = self._get_prepared_text_document(message, content_width_constraint)
            # Ensure the document uses the correct width before measuring/drawing
            text_doc.setTextWidth(content_width_constraint)
            text_height = int(text_doc.size().height()) # Use document's calculated height

            if text_height > 0 and current_y + text_height <= content_placement_rect.bottom() + 1:
                painter.save()
                painter.translate(content_placement_rect.left(), current_y)
                # Draw directly, color is handled by HTML/CSS
                text_doc.drawContents(painter)
                painter.restore()
                current_y += text_height # Move down for next element
            elif text_height > 0:
                 logger.warning("Calculated text height exceeds available bubble space.")


        # 2. Draw Images
        if message.has_images:
            if message.text and text_height > 0 : # Add padding if text was present and had height
                current_y += IMAGE_PADDING

            for img_part in message.image_parts:
                pixmap = self._get_image_pixmap(img_part)
                if pixmap and not pixmap.isNull():
                    # Scale pixmap to fit content width constraint and max dimensions
                    target_width = min(pixmap.width(), content_width_constraint, MAX_IMAGE_WIDTH)
                    scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
                    if scaled_pixmap.height() > MAX_IMAGE_HEIGHT:
                        scaled_pixmap = scaled_pixmap.scaledToHeight(MAX_IMAGE_HEIGHT, Qt.TransformationMode.SmoothTransformation)

                    # Center image horizontally within the content area
                    img_x = content_placement_rect.left() + (content_width_constraint - scaled_pixmap.width()) // 2

                    # Check if image fits vertically
                    if current_y + scaled_pixmap.height() <= content_placement_rect.bottom() + 1:
                        img_rect = QRect(QPoint(img_x, current_y), scaled_pixmap.size())
                        painter.drawPixmap(img_rect.topLeft(), scaled_pixmap)
                        current_y += scaled_pixmap.height() + IMAGE_PADDING # Move Y down
                    else:
                        logger.warning("Next image too tall to fit in remaining bubble rect.")
                        break # Stop drawing images if one doesn't fit
                else:
                     # Handle image load error within loop if needed
                     # e.g., draw a placeholder
                     pass


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
        # Use the width from the option provided by the view, which should be accurate
        available_view_width = option.rect.width()
        available_content_width = available_view_width - 2 * BUBBLE_MARGIN_H
        if available_content_width <= 0: available_content_width = 1

        # Get the size required by the content itself
        content_size = self._calculate_content_size(message, available_content_width)

        # Add vertical margins to the content height for the final item height
        final_height = content_size.height() + 2 * BUBBLE_MARGIN_V

        # The item width should take the full available width of the view column
        final_width = available_view_width

        # Ensure minimum height for very small content
        min_row_height = self._font_metrics.height() + 2 * BUBBLE_MARGIN_V + 2 * BUBBLE_PADDING_V
        final_height = max(final_height, min_row_height)

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

        # Ensure bubble doesn't have zero or negative width/height before placement
        if bubble_width <= 0: bubble_width = MIN_BUBBLE_WIDTH
        if bubble_height <= 0: bubble_height = self._font_metrics.height() + 2 * BUBBLE_PADDING_V


        if is_user:
            # Align right: Start bubble at (right edge - margin - bubble width)
            bubble_x = item_rect.right() - BUBBLE_MARGIN_H - bubble_width
        else:
            # Align left: Start bubble at left edge + margin
            bubble_x = item_rect.left() + BUBBLE_MARGIN_H

        # Vertical position starts after top margin
        bubble_y = item_rect.top() + BUBBLE_MARGIN_V

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
        text_render_height = 0
        actual_text_width = 0 # <<< Reset here
        if message.text:
            # Get the document, potentially from cache (passing constraint is okay for cache key)
            text_doc = self._get_prepared_text_document(message, inner_width_constraint)

            # --- MODIFICATION START ---
            # Calculate ideal width *without* the constraint first
            # Set text width to -1 to let QTextDocument calculate the ideal width
            text_doc.setTextWidth(-1)
            ideal_text_width = int(text_doc.size().width())

            # Determine the width to actually use for rendering and size calculation
            # It's the smaller of the ideal width and the constraint
            render_text_width = min(ideal_text_width, inner_width_constraint)
            actual_text_width = render_text_width # Track the width needed *by the text*

            # Set the document width for correct height calculation *at the render width*
            text_doc.setTextWidth(max(1, render_text_width)) # Use max(1, ...) to avoid zero width
            text_render_height = max(0, int(text_doc.size().height())) # Get height based on render width
            # --- MODIFICATION END ---

            total_height += text_render_height
            # Use the calculated actual_text_width for the overall content width calculation
            actual_content_width = max(actual_content_width, actual_text_width)

        # 2. Calculate Image Sizes
        if message.has_images:
            if message.text and total_height > 0: total_height += IMAGE_PADDING # Padding between text and first image
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

                    # Ensure non-negative dimensions
                    img_render_height = max(0, scaled_pixmap.height())
                    img_render_width = max(0, scaled_pixmap.width())

                    total_height += img_render_height
                    actual_content_width = max(actual_content_width, img_render_width)
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

        # IMPORTANT: Make sure the final width doesn't exceed the available space
        final_width = min(final_width, available_width)

        return QSize(final_width, final_height)

    def _get_prepared_text_document(self, message: ChatMessage, width_constraint: int) -> QTextDocument:
        """Creates or retrieves a cached QTextDocument for the message text."""
        # Ensure metadata exists before accessing it
        is_streaming = (message.metadata is not None) and message.metadata.get("is_streaming", False)
        # Use empty string hash if text is None/empty to avoid errors
        text_content = message.text if message.text else ""
        # Simple hash for caching, consider role?
        content_hash = hashlib.sha256(text_content.encode('utf-8')).hexdigest()
        # Added role to cache key
        cache_key = (content_hash, width_constraint, is_streaming, message.role)

        cached_doc = self._text_doc_cache.get(cache_key)
        if cached_doc:
            # Ensure width is set correctly on cached doc - this is important if _calculate_content_size changes it
            constrained_width = max(width_constraint, 1)
            if abs(cached_doc.textWidth() - constrained_width) > 1: # Allow minor tolerance
                 logger.debug(f"Updating cached doc width from {cached_doc.textWidth()} to {constrained_width}")
                 cached_doc.setTextWidth(constrained_width)
            return cached_doc

        # --- Create New Document ---
        logger.debug(f"Cache miss for key {cache_key}. Creating new QTextDocument.")
        doc = QTextDocument()
        doc.setDefaultFont(self._font)
        doc.setDocumentMargin(0) # Margin handled by bubble padding

        _, text_color = self._get_colors(message.role)
        # Use text_content which is guaranteed to be a string
        html_content = self._prepare_html(text_content, text_color, is_streaming)

        # --- Set StyleSheet for QTextDocument ---
        doc.setDefaultStyleSheet(f"""
            p {{ margin: 0 0 3px 0; padding: 0; line-height: 130%; }}
            ul, ol {{ margin: 3px 0 3px 20px; padding: 0; }}
            li {{ margin-bottom: 2px; }}
            pre {{
                background-color: {CODE_BG_COLOR.name()};
                border: 1px solid {BUBBLE_BORDER_COLOR.name()};
                padding: 8px;
                margin: 4px 0;
                border-radius: 4px;
                overflow-x: auto;
                white-space: pre-wrap; /* Allow wrapping */
                word-wrap: break-word; /* Break long words */
                font-family: '{self._font.family()}', monospace; /* Use delegate font */
                font-size: {self._font.pointSize()}pt;
                color: {AI_TEXT_COLOR.name()};
                line-height: 120%;
            }}
            code {{ /* Inline code */
                 background-color: {CODE_BG_COLOR.lighter(110).name()};
                 padding: 1px 3px;
                 border-radius: 3px;
                 font-family: '{self._font.family()}', monospace;
                 font-size: {int(self._font.pointSize() * 0.95)}pt;
                 color: {AI_TEXT_COLOR.lighter(120).name()};
            }}
            table {{ border-collapse: collapse; margin: 5px 0; color: {text_color.name()}; background-color: {CODE_BG_COLOR.lighter(105).name()}; }}
            th, td {{ border: 1px solid {BUBBLE_BORDER_COLOR.name()}; padding: 4px 6px; }}
            th {{ background-color: {CODE_BG_COLOR.lighter(120).name()}; font-weight: bold; }}
            a {{ color: #61afef; text-decoration: underline; }}
            a:hover {{ color: #82c0ff; }}
            blockquote {{
                border-left: 3px solid {text_color.darker(120).name()};
                margin: 5px 0px 5px 5px;
                padding-left: 10px;
                color: {text_color.darker(110).name()};
                font-style: italic;
            }}
             h1, h2, h3, h4, h5, h6 {{ margin-top: 8px; margin-bottom: 4px; font-weight: bold; color: {text_color.lighter(110).name()}; }}
             h1 {{ font-size: 1.4em; border-bottom: 1px solid {BUBBLE_BORDER_COLOR.name()}; }}
             h2 {{ font-size: 1.2em; border-bottom: 1px solid {BUBBLE_BORDER_COLOR.name()}; }}
             h3 {{ font-size: 1.1em; }}
             h4 {{ font-size: 1.0em; }}
             h5 {{ font-size: 0.9em; }}
             h6 {{ font-size: 0.9em; font-style: italic; color: {text_color.darker(110).name()}; }}
             hr {{ border: 0; height: 1px; background-color: {BUBBLE_BORDER_COLOR.name()}; margin: 10px 0; }}
        """)
        # --- End StyleSheet Setting ---

        doc.setHtml(html_content)

        # Set the width constraint *before* calculating size or caching
        doc.setTextWidth(max(width_constraint, 1))

        # Store in cache
        self._text_doc_cache[cache_key] = doc
        return doc

    def _prepare_html(self, text: str, text_color: QColor, is_streaming: bool) -> str:
        """Converts message text to basic HTML for QTextDocument."""
        if not text: return ""

        # 1. Escape basic HTML characters first to prevent injection
        escaped_text = html.escape(text)

        # 2. Handle newlines -> <br> (Do this *after* escaping)
        # Store this as a fallback
        html_content_fallback = escaped_text.replace('\n', '<br/>')
        html_content = html_content_fallback # Default to this

        # 3. Apply Markdown conversion only if not streaming and library available
        if not is_streaming and MARKDOWN_AVAILABLE:
            try:
                # Convert markdown.
                md_content = markdown.markdown(text, extensions=['fenced_code', 'nl2br', 'tables', 'sane_lists', 'extra'])
                # Use markdown output only if conversion succeeds
                html_content = md_content
            except Exception as e:
                logger.error(f"Markdown conversion failed: {e}. Using escaped text with <br>.")
                # html_content remains the fallback version
                pass

        # Wrap in basic body tag with color style
        # QTextDocument expects valid HTML structure
        final_html = f"""<!DOCTYPE html>
        <html><head><meta charset="UTF-8"></head>
        <body style="color:{text_color.name()};">
        {html_content}
        </body></html>"""

        return final_html


    def _get_image_pixmap(self, image_part: Dict[str, Any]) -> Optional[QPixmap]:
        """Decodes base64 image data and returns a QPixmap, using caching."""
        base64_data = image_part.get("data")
        if not base64_data or not isinstance(base64_data, str):
            logger.warning("Attempted to decode image, but 'data' key is missing, empty, or not a string.")
            return None

        # Use hash of base64 data as cache key
        data_hash = hashlib.sha256(base64_data.encode()).hexdigest()
        cached_pixmap = self._image_pixmap_cache.get(data_hash)
        if cached_pixmap:
            # logger.debug(f"Image cache hit for hash {data_hash[:8]}")
            return cached_pixmap

        # logger.debug(f"Image cache miss for hash {data_hash[:8]}. Decoding image.")
        try:
            # Ensure padding is correct for base64 decoding
            missing_padding = len(base64_data) % 4
            if missing_padding:
                base64_data += '=' * (4 - missing_padding)

            image_bytes = base64.b64decode(base64_data)
            qimage = QImage()
            if qimage.loadFromData(image_bytes):
                 pixmap = QPixmap.fromImage(qimage)
                 if not pixmap.isNull():
                     self._image_pixmap_cache[data_hash] = pixmap # Store in cache
                     return pixmap
                 else:
                     logger.error("QImage loaded but QPixmap conversion resulted in null.")
                     return None
            else:
                logger.error("QImage.loadFromData failed for image part.")
                return None
        except base64.binascii.Error as e_b64:
             logger.error(f"Base64 decoding error in delegate: {e_b64}")
             return None
        except Exception as e:
            logger.error(f"Error decoding/loading image in delegate: {e}", exc_info=True)
            return None