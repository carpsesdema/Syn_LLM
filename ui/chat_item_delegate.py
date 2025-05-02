# SynaChat/ui/chat_item_delegate.py
# UPDATED FILE - Reinstated and improved caching for QTextDocument

import logging
import base64
import html
import hashlib # <-- ADDED for caching key
from typing import Optional, Dict, Any, Tuple # <-- ADDED Tuple

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle, QApplication, QStyleOptionViewItem
from PyQt6.QtGui import QPainter, QColor, QFontMetrics, QTextDocument, QPixmap, QImage, QPalette, QFont
from PyQt6.QtCore import QModelIndex, QRect, QPoint, QSize, Qt, QObject

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
TAIL_WIDTH = 10
TAIL_HEIGHT = 10
IMAGE_PADDING = 5
MAX_IMAGE_WIDTH = 250 # Smaller max width for delegate rendering
MAX_IMAGE_HEIGHT = 250

# --- Colors (can be moved to constants or theme manager) ---
USER_BUBBLE_COLOR = QColor("#0b93f6")
USER_TEXT_COLOR = QColor(Qt.GlobalColor.white)
AI_BUBBLE_COLOR = QColor("#3c3f41")
AI_TEXT_COLOR = QColor("#dcdcdc")
SYSTEM_BUBBLE_COLOR = QColor("#4a4e51")
SYSTEM_TEXT_COLOR = QColor("#aabbcc")
ERROR_BUBBLE_COLOR = QColor("#6e3b3b")
ERROR_TEXT_COLOR = QColor("#ffcccc")
CODE_BG_COLOR = QColor("#282c34") # Matches QSS 'pre'

class ChatItemDelegate(QStyledItemDelegate):
    """
    Custom delegate for rendering ChatMessage objects in a QListView.
    Draws chat bubbles with text (including basic Markdown/HTML) and images.
    """
    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._font = QFont(CHAT_FONT_FAMILY, CHAT_FONT_SIZE)
        self._font_metrics = QFontMetrics(self._font)
        # --- MODIFIED: Use tuple for cache key ---
        self._text_doc_cache: Dict[Tuple[str, int], QTextDocument] = {} # Cache: (content_hash, width) -> QTextDocument
        logger.info("ChatItemDelegate initialized.")

    # --- ADDED: Method to clear cache (call when model resets) ---
    def clearCache(self):
        logger.debug("Clearing ChatItemDelegate cache.")
        self._text_doc_cache.clear()

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
        bubble_color, text_color = self._get_colors(message.role)
        # --- MODIFIED LINE (Fix for 'QStyleOptionViewItem' has no attribute 'adjusted') ---
        content_rect = self._get_content_rect(option.rect) # Pass the rectangle part
        # --- END MODIFICATION ---
        required_size = self._calculate_item_size(message, content_rect.width())
        bubble_rect = self._get_bubble_rect(option.rect, required_size, is_user)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bubble_color)
        painter.drawRoundedRect(bubble_rect, BUBBLE_RADIUS, BUBBLE_RADIUS)

        text_image_rect = bubble_rect.adjusted(BUBBLE_PADDING_H, BUBBLE_PADDING_V,
                                               -BUBBLE_PADDING_H, -BUBBLE_PADDING_V)
        current_y = text_image_rect.top()

        if message.text:
            # --- MODIFIED: Get potentially cached document ---
            text_doc = self._get_prepared_text_document(message, text_image_rect.width())
            # ---
            text_height = int(text_doc.size().height())

            painter.save()
            painter.setClipRect(text_image_rect.x(), current_y, text_image_rect.width(), text_height)
            painter.translate(text_image_rect.x(), current_y)
            text_doc.drawContents(painter)
            painter.restore()
            current_y += text_height + IMAGE_PADDING

        if message.has_images:
            for img_part in message.image_parts:
                pixmap = self._get_image_pixmap(img_part)
                if pixmap and not pixmap.isNull():
                    target_width = min(pixmap.width(), text_image_rect.width(), MAX_IMAGE_WIDTH)
                    scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
                    if scaled_pixmap.height() > MAX_IMAGE_HEIGHT:
                         scaled_pixmap = scaled_pixmap.scaledToHeight(MAX_IMAGE_HEIGHT, Qt.TransformationMode.SmoothTransformation)

                    img_x = text_image_rect.x() + (text_image_rect.width() - scaled_pixmap.width()) // 2
                    img_rect = QRect(QPoint(img_x, current_y), scaled_pixmap.size())

                    if text_image_rect.contains(img_rect):
                        painter.drawPixmap(img_rect.topLeft(), scaled_pixmap)
                        current_y += scaled_pixmap.height() + IMAGE_PADDING
                    else:
                         logger.warning("Image too tall to fit in calculated bubble rect.")


        if option.state & QStyle.StateFlag.State_Selected:
            highlight_color = option.palette.highlight().color()
            highlight_color.setAlpha(80)
            painter.fillRect(option.rect, highlight_color)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        """Provides the size needed for the item."""
        message = index.data(ChatMessageRole)
        if not isinstance(message, ChatMessage):
            return super().sizeHint(option, index)

        available_width = option.rect.width() - 2 * BUBBLE_MARGIN_H
        # --- MODIFIED: Use _calculate_item_size which uses cached doc ---
        calculated_size = self._calculate_item_size(message, available_width)
        # ---
        final_height = calculated_size.height() + 2 * BUBBLE_MARGIN_V
        return QSize(option.rect.width(), final_height)

    # --- Helper Methods ---

    def _get_colors(self, role: str) -> tuple[QColor, QColor]:
        """Returns bubble and text color based on role."""
        if role == USER_ROLE: return USER_BUBBLE_COLOR, USER_TEXT_COLOR
        if role == SYSTEM_ROLE: return SYSTEM_BUBBLE_COLOR, SYSTEM_TEXT_COLOR
        if role == ERROR_ROLE: return ERROR_BUBBLE_COLOR, ERROR_TEXT_COLOR
        return AI_BUBBLE_COLOR, AI_TEXT_COLOR

    # --- MODIFIED: Parameter type hint changed to QRect ---
    def _get_content_rect(self, item_rect: QRect) -> QRect: # Changed parameter name and type hint
    # --- END MODIFICATION ---
        """Calculates the area available for content within the item, considering margins."""
        # Use the passed item_rect directly
        return item_rect.adjusted(BUBBLE_MARGIN_H, BUBBLE_MARGIN_V,
                                  -BUBBLE_MARGIN_H, -BUBBLE_MARGIN_V)

    def _get_bubble_rect(self, option_rect: QRect, content_size: QSize, is_user: bool) -> QRect:
        """Calculates the actual bubble rectangle based on content size and alignment."""
        # Pass the correct rectangle to _get_content_rect
        available_rect = self._get_content_rect(option_rect) # Pass option_rect here
        bubble_width = content_size.width()
        bubble_height = content_size.height()

        if is_user:
            bubble_x = available_rect.right() - bubble_width
        else:
            bubble_x = available_rect.left()

        bubble_y = BUBBLE_MARGIN_V
        return QRect(bubble_x, bubble_y, bubble_width, bubble_height)


    def _calculate_item_size(self, message: ChatMessage, available_width: int) -> QSize:
        """Calculates the size needed for the bubble content (text + images)."""
        total_height = 0
        max_content_width = 0
        constrained_content_width = max(1, available_width - 2 * BUBBLE_PADDING_H)

        if message.text:
            # --- MODIFIED: Use cached doc for size calculation ---
            text_doc = self._get_prepared_text_document(message, constrained_content_width)
            # ---
            text_size = text_doc.size()
            total_height += int(text_size.height())
            max_content_width = max(max_content_width, int(min(text_size.width(), constrained_content_width)))

        if message.has_images:
            if message.text: total_height += IMAGE_PADDING
            for i, img_part in enumerate(message.image_parts):
                pixmap = self._get_image_pixmap(img_part)
                if i > 0: total_height += IMAGE_PADDING
                if pixmap and not pixmap.isNull():
                    target_width = min(pixmap.width(), constrained_content_width, MAX_IMAGE_WIDTH)
                    if pixmap.width() > target_width:
                        scaled_pixmap = pixmap.scaledToWidth(target_width, Qt.TransformationMode.SmoothTransformation)
                    else: scaled_pixmap = pixmap
                    if scaled_pixmap.height() > MAX_IMAGE_HEIGHT:
                         scaled_pixmap = scaled_pixmap.scaledToHeight(MAX_IMAGE_HEIGHT, Qt.TransformationMode.SmoothTransformation)
                    total_height += scaled_pixmap.height()
                    max_content_width = max(max_content_width, scaled_pixmap.width())
                else:
                     error_text_height = self._font_metrics.height()
                     total_height += error_text_height
                     max_content_width = max(max_content_width, self._font_metrics.horizontalAdvance("[Image Error]"))
                     if message.text or i > 0: total_height += IMAGE_PADDING

        final_height = total_height + 2 * BUBBLE_PADDING_V
        final_width = max_content_width + 2 * BUBBLE_PADDING_H
        min_bubble_width = 50
        final_width = max(final_width, min_bubble_width)
        final_height = max(final_height, self._font_metrics.height() + 2 * BUBBLE_PADDING_V)

        return QSize(final_width, final_height)

    def _get_prepared_text_document(self, message: ChatMessage, width_constraint: int) -> QTextDocument:
        """Creates or retrieves a cached QTextDocument for the message text."""
        # --- MODIFIED: Implement caching ---
        content_hash = hashlib.sha256(message.text.encode('utf-8')).hexdigest()
        is_streaming = message.metadata and message.metadata.get("is_streaming", False)
        # Include streaming state in cache key? Maybe not needed if content hash changes anyway.
        cache_key = (content_hash, width_constraint)

        if cache_key in self._text_doc_cache:
            # logger.debug(f"Cache hit for key: {cache_key}")
            # Ensure width is still set correctly on cached doc
            cached_doc = self._text_doc_cache[cache_key]
            if cached_doc.textWidth() != max(width_constraint, 1):
                 # logger.debug(f"Updating width on cached doc: {max(width_constraint, 1)}")
                 cached_doc.setTextWidth(max(width_constraint, 1))
            return cached_doc
        # ---

        # logger.debug(f"Cache miss for key: {cache_key}. Creating new doc.")
        doc = QTextDocument()
        doc.setDefaultFont(self._font)
        doc.setDocumentMargin(0)

        _, text_color = self._get_colors(message.role)

        if is_streaming:
            plain_text = html.escape(message.text).replace('\n', '<br/>')
            html_content = f'<body style="color:{text_color.name()};">{plain_text}</body>'
            doc.setHtml(html_content)
        else:
            html_content = self._prepare_html(message.text, text_color)
            doc.setHtml(html_content)

        doc.setTextWidth(max(width_constraint, 1))

        # --- MODIFIED: Store in cache ---
        self._text_doc_cache[cache_key] = doc
        # ---
        return doc

    def _prepare_html(self, text: str, text_color: QColor) -> str:
        """Converts message text to styled HTML for QTextDocument."""
        # (HTML preparation logic remains the same)
        if not text: return ""
        if MARKDOWN_AVAILABLE:
            try:
                base_html = markdown.markdown(text, extensions=['fenced_code', 'nl2br', 'tables', 'sane_lists', 'extra'])
            except Exception as e:
                logger.error(f"Markdown conversion failed: {e}")
                base_html = html.escape(text).replace('\n', '<br/>')
        else:
            base_html = html.escape(text).replace('\n', '<br/>')

        styled_html = f"""
        <body style="color: {text_color.name()};">
            {base_html}
        </body>
        """
        return styled_html

    def _get_image_pixmap(self, image_part: Dict[str, Any]) -> Optional[QPixmap]:
        """Decodes base64 image data and returns a QPixmap."""
        # (Logic remains the same)
        base64_data = image_part.get("data")
        if not base64_data: return None
        try:
            image_bytes = base64.b64decode(base64_data)
            qimage = QImage()
            if qimage.loadFromData(image_bytes):
                return QPixmap.fromImage(qimage)
            else:
                logger.error("Failed to load image from data in delegate.")
                return None
        except Exception as e:
            logger.error(f"Error decoding/loading image in delegate: {e}")
            return None