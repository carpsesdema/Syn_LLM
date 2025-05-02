# SynaChat/ui/chat_item_delegate.py
# UPDATED FILE - Increased paragraph spacing, added timestamps

import logging
import base64
import html
import hashlib
from typing import Optional, Dict, Any, Tuple
from datetime import datetime # <<< ADDED import

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QApplication, QStyleOptionViewItem
from PyQt6.QtGui import (
    QPainter, QColor, QFontMetrics, QTextDocument, QPixmap, QImage, QFont,
    QImageReader, QPen
)
from PyQt6.QtCore import QModelIndex, QRect, QPoint, QSize, Qt, QObject, QByteArray, QUrl

from core.models import ChatMessage, USER_ROLE, MODEL_ROLE, SYSTEM_ROLE, ERROR_ROLE
from utils.constants import CHAT_FONT_FAMILY, CHAT_FONT_SIZE
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
BUBBLE_RADIUS = 12
TAIL_WIDTH = 10
TAIL_HEIGHT = 10
IMAGE_PADDING = 5
MAX_IMAGE_WIDTH = 250
MAX_IMAGE_HEIGHT = 250
MIN_BUBBLE_WIDTH = 50
USER_BUBBLE_INDENT = 40
TIMESTAMP_PADDING_TOP = 3 # <<< ADDED: Padding above timestamp
TIMESTAMP_HEIGHT = 15      # <<< ADDED: Estimated height for timestamp text

# --- Colors ---
USER_BUBBLE_COLOR = QColor("#0b93f6")
USER_TEXT_COLOR = QColor(Qt.GlobalColor.white)
AI_BUBBLE_COLOR = QColor("#3c3f41")
AI_TEXT_COLOR = QColor("#dcdcdc")
SYSTEM_BUBBLE_COLOR = QColor("#4a4e51")
SYSTEM_TEXT_COLOR = QColor("#aabbcc")
ERROR_BUBBLE_COLOR = QColor("#6e3b3b")
ERROR_TEXT_COLOR = QColor("#ffcccc")
CODE_BG_COLOR = QColor("#282c34")
BUBBLE_BORDER_COLOR = QColor("#4f5356")
TIMESTAMP_COLOR = QColor("#888888") # <<< ADDED: Color for timestamp

class ChatItemDelegate(QStyledItemDelegate):
    """
    Custom delegate for rendering ChatMessage objects in a QListView.
    Draws chat bubbles with text (including basic Markdown/HTML) and images,
    aligned based on user/agent role. Includes timestamps.
    """
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE)
        self._font_metrics = QFontMetrics(self._font)
        # <<< ADDED: Timestamp font >>>
        self._timestamp_font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE - 2) # Smaller font
        self._timestamp_font_metrics = QFontMetrics(self._timestamp_font)
        # <<< Cache keys remain the same >>>
        self._text_doc_cache: Dict[Tuple[str, int, bool, str], QTextDocument] = {}
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
            super().paint(painter, option, index)
            painter.restore()
            return

        is_user = (message.role == USER_ROLE)
        bubble_color, _ = self._get_colors(message.role)

        available_content_width = option.rect.width() - 2 * BUBBLE_MARGIN_H
        if available_content_width <= 0: available_content_width = 1

        # <<< Pass is_user to content size calculation >>>
        required_content_size = self._calculate_content_size(message, available_content_width, is_user)

        # <<< Get bubble rect (accounts for content height only, not timestamp yet) >>>
        bubble_rect = self._get_bubble_rect(option.rect, required_content_size, is_user)

        # --- Draw Bubble ---
        painter.setPen(QPen(BUBBLE_BORDER_COLOR, 1))
        painter.setBrush(bubble_color)
        painter.drawRoundedRect(bubble_rect, BUBBLE_RADIUS, BUBBLE_RADIUS)

        # --- Draw Content (Text and Images) ---
        content_placement_rect = bubble_rect.adjusted(BUBBLE_PADDING_H, BUBBLE_PADDING_V,
                                                      -BUBBLE_PADDING_H, -BUBBLE_PADDING_V)
        if content_placement_rect.width() > 0:
            current_y = content_placement_rect.top()
            content_width_constraint = content_placement_rect.width()

            # 1. Draw Text
            text_height = 0 # Keep track of text height
            if message.text:
                text_doc = self._get_prepared_text_document(message, content_width_constraint)
                text_doc.setTextWidth(content_width_constraint)
                text_height = int(text_doc.size().height())

                if text_height > 0 and current_y + text_height <= content_placement_rect.bottom() + 1:
                    painter.save()
                    painter.translate(content_placement_rect.left(), current_y)
                    text_doc.drawContents(painter)
                    painter.restore()
                    current_y += text_height

            # 2. Draw Images
            if message.has_images:
                if message.text and text_height > 0:
                    current_y += IMAGE_PADDING
                image_count = 0 # Track if any images were drawn
                for img_part in message.image_parts:
                    pixmap = self._get_image_pixmap(img_part)
                    if pixmap and not pixmap.isNull():
                        target_width = min(pixmap.width(), content_width_constraint, MAX_IMAGE_WIDTH)
                        scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
                        if scaled_pixmap.height() > MAX_IMAGE_HEIGHT:
                            scaled_pixmap = scaled_pixmap.scaledToHeight(MAX_IMAGE_HEIGHT, Qt.TransformationMode.SmoothTransformation)

                        if current_y + scaled_pixmap.height() <= content_placement_rect.bottom() + 1:
                             if image_count > 0: current_y += IMAGE_PADDING # Padding between images
                             img_x = content_placement_rect.left() + (content_width_constraint - scaled_pixmap.width()) // 2
                             img_rect = QRect(QPoint(img_x, current_y), scaled_pixmap.size())
                             painter.drawPixmap(img_rect.topLeft(), scaled_pixmap)
                             current_y += scaled_pixmap.height()
                             image_count += 1
                        else:
                            logger.warning("Next image too tall to fit in remaining bubble rect.")
                            break
                    # Placeholder for failed image can be added here if desired
        else:
             logger.warning("Content placement rect has zero or negative width. Skipping content draw.")


        # --- Draw Timestamp ---
        formatted_timestamp = self._format_timestamp(message.timestamp)
        if formatted_timestamp:
            timestamp_width = self._timestamp_font_metrics.horizontalAdvance(formatted_timestamp)
            # Position below the bubble, aligned to the bubble's right edge
            timestamp_x = bubble_rect.right() - timestamp_width
            # Ensure timestamp doesn't go left of the bubble's left edge if bubble is narrow
            timestamp_x = max(timestamp_x, bubble_rect.left())
            timestamp_y = bubble_rect.bottom() + TIMESTAMP_PADDING_TOP + self._timestamp_font_metrics.ascent()

            # Ensure timestamp fits within the overall item rect vertically
            if timestamp_y < option.rect.bottom() - BUBBLE_MARGIN_V:
                painter.setFont(self._timestamp_font)
                painter.setPen(TIMESTAMP_COLOR)
                painter.drawText(QPoint(timestamp_x, timestamp_y), formatted_timestamp)
        # --- End Timestamp ---


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

        is_user = (message.role == USER_ROLE)

        available_view_width = option.rect.width()
        available_content_width = available_view_width - 2 * BUBBLE_MARGIN_H
        if available_content_width <= 0: available_content_width = 1

        # Get the size required by the bubble content itself
        content_size = self._calculate_content_size(message, available_content_width, is_user)

        # Start with content height
        total_required_height = content_size.height()

        # --- Add space for timestamp ---
        formatted_timestamp = self._format_timestamp(message.timestamp)
        if formatted_timestamp:
            total_required_height += TIMESTAMP_PADDING_TOP + TIMESTAMP_HEIGHT
        # --- End Timestamp ---

        # Add vertical margins for the final item height
        final_height = total_required_height + 2 * BUBBLE_MARGIN_V

        # The item width should take the full available width
        final_width = available_view_width

        # Ensure minimum height
        min_row_height = self._font_metrics.height() + 2 * BUBBLE_MARGIN_V + 2 * BUBBLE_PADDING_V
        final_height = max(final_height, min_row_height)

        return QSize(final_width, final_height)

    # --- Helper Methods ---

    def _get_colors(self, role: str) -> tuple[QColor, QColor]:
        """Returns bubble and text color based on role."""
        if role == USER_ROLE: return USER_BUBBLE_COLOR, USER_TEXT_COLOR
        if role == SYSTEM_ROLE: return SYSTEM_BUBBLE_COLOR, SYSTEM_TEXT_COLOR
        if role == ERROR_ROLE: return ERROR_BUBBLE_COLOR, ERROR_TEXT_COLOR
        return AI_BUBBLE_COLOR, AI_TEXT_COLOR # Default AI

    def _get_bubble_rect(self, item_rect: QRect, content_size: QSize, is_user: bool) -> QRect:
        """Calculates the actual bubble rectangle (excluding timestamp space)."""
        bubble_width = content_size.width()
        bubble_height = content_size.height()

        if bubble_width <= 0: bubble_width = MIN_BUBBLE_WIDTH
        if bubble_height <= 0: bubble_height = self._font_metrics.height() + 2 * BUBBLE_PADDING_V

        base_x = item_rect.left() + BUBBLE_MARGIN_H
        if is_user:
            bubble_x = base_x + USER_BUBBLE_INDENT
        else:
            bubble_x = base_x

        bubble_y = item_rect.top() + BUBBLE_MARGIN_V

        max_right = item_rect.right() - BUBBLE_MARGIN_H
        if bubble_x + bubble_width > max_right:
            bubble_width = max(max_right - bubble_x, MIN_BUBBLE_WIDTH)

        return QRect(bubble_x, bubble_y, bubble_width, bubble_height)

    def _calculate_content_size(self, message: ChatMessage, available_width: int, is_user: bool) -> QSize:
        """Calculates size for bubble content (text+images), including padding."""
        total_height = 0
        actual_content_width = 0

        effective_available_width = available_width
        if is_user:
             effective_available_width -= USER_BUBBLE_INDENT
        effective_available_width = max(1, effective_available_width)

        inner_width_constraint = max(1, effective_available_width - 2 * BUBBLE_PADDING_H)

        # 1. Calculate Text Size
        text_render_height = 0
        actual_text_width = 0
        if message.text:
            text_doc = self._get_prepared_text_document(message, inner_width_constraint)
            # Temporarily unset width to get ideal size, then constrain
            text_doc.setTextWidth(-1) # Unset width
            ideal_size = text_doc.size()
            render_text_width = min(int(ideal_size.width()), inner_width_constraint)
            actual_text_width = render_text_width

            text_doc.setTextWidth(max(1, render_text_width)) # Set constrained width for height calc
            text_render_height = max(0, int(text_doc.size().height())) # Use constrained height

            total_height += text_render_height
            actual_content_width = max(actual_content_width, actual_text_width)

        # 2. Calculate Image Sizes
        if message.has_images:
            if message.text and text_render_height > 0: total_height += IMAGE_PADDING
            image_count = 0
            for img_part in message.image_parts:
                pixmap = self._get_image_pixmap(img_part)
                if pixmap and not pixmap.isNull():
                    if image_count > 0: total_height += IMAGE_PADDING

                    target_width = min(pixmap.width(), inner_width_constraint, MAX_IMAGE_WIDTH)
                    scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
                    if scaled_pixmap.height() > MAX_IMAGE_HEIGHT:
                         scaled_pixmap = scaled_pixmap.scaledToHeight(MAX_IMAGE_HEIGHT, Qt.TransformationMode.SmoothTransformation)

                    img_render_height = max(0, scaled_pixmap.height())
                    img_render_width = max(0, scaled_pixmap.width())

                    total_height += img_render_height
                    actual_content_width = max(actual_content_width, img_render_width)
                    image_count += 1
                else:
                    if image_count > 0: total_height += IMAGE_PADDING
                    total_height += self._font_metrics.height()
                    actual_content_width = max(actual_content_width, self._font_metrics.horizontalAdvance("[X]"))
                    image_count += 1

        # Add bubble padding
        final_height = total_height + 2 * BUBBLE_PADDING_V
        final_width = actual_content_width + 2 * BUBBLE_PADDING_H

        # Enforce minimums
        final_width = max(final_width, MIN_BUBBLE_WIDTH)
        min_bubble_height = self._font_metrics.height() + 2 * BUBBLE_PADDING_V
        final_height = max(final_height, min_bubble_height)

        final_width = max(1, final_width)
        final_height = max(1, final_height)

        # Ensure final width doesn't exceed effective available space
        final_width = min(final_width, effective_available_width)

        return QSize(final_width, final_height)


    def _get_prepared_text_document(self, message: ChatMessage, width_constraint: int) -> QTextDocument:
        """Creates or retrieves a cached QTextDocument for the message text."""
        is_streaming = (message.metadata is not None) and message.metadata.get("is_streaming", False)
        text_content = message.text if message.text else ""
        # Use simple hash for cache key, collision unlikely for typical chat messages
        content_hash = hashlib.sha1(text_content.encode('utf-8')).hexdigest()[:16]
        cache_key = (content_hash, width_constraint, is_streaming, message.role)

        cached_doc = self._text_doc_cache.get(cache_key)
        if cached_doc:
            # Re-apply width constraint if it changed significantly
            constrained_width = max(width_constraint, 1)
            if abs(cached_doc.textWidth() - constrained_width) > 1:
                 cached_doc.setTextWidth(constrained_width)
            return cached_doc

        doc = QTextDocument()
        doc.setDefaultFont(self._font)
        doc.setDocumentMargin(0)

        _, text_color = self._get_colors(message.role)
        html_content = self._prepare_html(text_content, text_color, is_streaming)

        doc.setDefaultStyleSheet(f"""
            p {{
                margin: 0 0 8px 0; /* <<< INCREASED bottom margin */
                padding: 0;
                line-height: 130%;
            }}
            ul, ol {{ margin: 3px 0 8px 20px; padding: 0; }} /* Increased bottom margin */
            li {{ margin-bottom: 4px; }} /* Increased bottom margin */
            pre {{
                background-color: {CODE_BG_COLOR.name()};
                border: 1px solid {BUBBLE_BORDER_COLOR.name()};
                padding: 8px;
                margin: 6px 0; /* Increased vertical margin */
                border-radius: 4px;
                overflow-x: auto;
                white-space: pre-wrap;
                word-wrap: break-word;
                font-family: '{self._font.family()}', monospace;
                font-size: {self._font.pointSize()}pt;
                color: {AI_TEXT_COLOR.name()};
                line-height: 120%;
            }}
            code {{
                 background-color: {CODE_BG_COLOR.lighter(110).name()};
                 padding: 1px 3px;
                 border-radius: 3px;
                 font-family: '{self._font.family()}', monospace;
                 font-size: {int(self._font.pointSize() * 0.95)}pt;
                 color: {AI_TEXT_COLOR.lighter(120).name()};
            }}
            table {{ border-collapse: collapse; margin: 8px 0; color: {text_color.name()}; background-color: {CODE_BG_COLOR.lighter(105).name()}; }} /* Increased margin */
            th, td {{ border: 1px solid {BUBBLE_BORDER_COLOR.name()}; padding: 4px 6px; }}
            th {{ background-color: {CODE_BG_COLOR.lighter(120).name()}; font-weight: bold; }}
            a {{ color: #61afef; text-decoration: underline; }}
            a:hover {{ color: #82c0ff; }}
            blockquote {{
                border-left: 3px solid {text_color.darker(120).name()};
                margin: 8px 0px 8px 5px; /* Increased vertical margin */
                padding-left: 10px;
                color: {text_color.darker(110).name()};
                font-style: italic;
            }}
             h1, h2, h3, h4, h5, h6 {{ margin-top: 10px; margin-bottom: 5px; font-weight: bold; color: {text_color.lighter(110).name()}; }} /* Adjusted margins */
             h1 {{ font-size: 1.4em; border-bottom: 1px solid {BUBBLE_BORDER_COLOR.name()}; }}
             h2 {{ font-size: 1.2em; border-bottom: 1px solid {BUBBLE_BORDER_COLOR.name()}; }}
             h3 {{ font-size: 1.1em; }}
             h4 {{ font-size: 1.0em; }}
             h5 {{ font-size: 0.9em; }}
             h6 {{ font-size: 0.9em; font-style: italic; color: {text_color.darker(110).name()}; }}
             hr {{ border: 0; height: 1px; background-color: {BUBBLE_BORDER_COLOR.name()}; margin: 12px 0; }} /* Increased margin */
        """)

        doc.setHtml(html_content)
        doc.setTextWidth(max(width_constraint, 1))
        self._text_doc_cache[cache_key] = doc
        return doc

    def _prepare_html(self, text: str, text_color: QColor, is_streaming: bool) -> str:
        """Converts message text to basic HTML for QTextDocument."""
        if not text: return ""
        # Escape initial text to prevent accidental HTML injection before markdown
        escaped_text = html.escape(text)
        html_content = escaped_text.replace('\n', '<br/>') # Basic newline handling

        if not is_streaming and MARKDOWN_AVAILABLE:
            try:
                # Convert potentially escaped text using Markdown
                md_content = markdown.markdown(text, extensions=['fenced_code', 'nl2br', 'tables', 'sane_lists', 'extra'])
                # We assume markdown output is safe HTML subset
                html_content = md_content
            except Exception as e:
                logger.error(f"Markdown conversion failed: {e}. Using escaped text.")
                # Fallback to already escaped text with <br> tags
                html_content = escaped_text.replace('\n', '<br/>')

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
            return None

        # Use simple hash for cache key, collision unlikely for image data
        data_hash = hashlib.sha1(base64_data.encode()).hexdigest()[:16]
        cached_pixmap = self._image_pixmap_cache.get(data_hash)
        if cached_pixmap:
            return cached_pixmap

        try:
            # Basic padding check/fix
            missing_padding = len(base64_data) % 4
            if missing_padding:
                base64_data += '=' * (4 - missing_padding)

            image_bytes = base64.b64decode(base64_data)
            qimage = QImage()
            if qimage.loadFromData(image_bytes):
                 pixmap = QPixmap.fromImage(qimage)
                 if not pixmap.isNull():
                     self._image_pixmap_cache[data_hash] = pixmap
                     return pixmap
        except Exception as e:
            logger.error(f"Error decoding/loading image in delegate: {e}")
        return None

    # <<< ADDED: Timestamp formatting helper >>>
    def _format_timestamp(self, iso_timestamp: Optional[str]) -> Optional[str]:
        """Formats an ISO timestamp string into HH:MM."""
        if not iso_timestamp:
            return None
        try:
            dt_object = datetime.fromisoformat(iso_timestamp)
            return dt_object.strftime("%H:%M")
        except (ValueError, TypeError):
            logger.warning(f"Could not parse timestamp: {iso_timestamp}")
            return None