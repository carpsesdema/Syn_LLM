
import sys
import os
import traceback
import logging
import asyncio # Needed for async ChatManager methods

# --- PyQt6 Imports ---
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QTimer # Added QTimer
from PyQt6.QtGui import QFontDatabase

# --- qasync Import ---
try:
    import qasync
except ImportError:
    print("[CRITICAL] qasync library not found. Please install it: pip install qasync", file=sys.stderr)
    try:
        _dummy_app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Missing Dependency", "Required library 'qasync' is not installed.\nPlease run: pip install qasync")
    except Exception as e:
        print(f"Failed to show missing dependency message: {e}", file=sys.stderr)
    sys.exit(1)


# --- Local Imports ---
try:
    # config is less relevant if not using Gemini API Key directly
    # from config import get_api_key
    from ui.main_window import MainWindow
    from core.chat_manager import ChatManager
    from services.session_service import SessionService
    from services.upload_service import UploadService
    # --- Import OllamaAdapter ---
    from backend.ollama_adapter import OllamaAdapter # USE OLLAMA
    # from backend.gemini_adapter import GeminiAdapter # Keep import if fallback is desired
    # --------------------------
    from utils.constants import CHAT_FONT_FAMILY, CHAT_FONT_FILENAME, LOG_LEVEL, LOG_FORMAT, APP_VERSION, APP_NAME
except ImportError as e:
    print(f"[CRITICAL] Failed to import core components: {e}", file=sys.stderr)
    print(f"PYTHONPATH: {sys.path}", file=sys.stderr)
    try:
         _dummy_app = QApplication.instance() or QApplication(sys.argv)
         QMessageBox.critical(None, "Import Error", f"Failed to import core components:\n{e}\nCheck PYTHONPATH.")
    except Exception as e_qm: print(f"Failed to show import error message: {e_qm}", file=sys.stderr)
    sys.exit(1)

# --- Setup Logging ---
log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(level=log_level, format=LOG_FORMAT, handlers=[logging.StreamHandler()]) # Log to console only
logger = logging.getLogger(__name__)

# --- Async Main Function ---
async def async_main():
    logger.info(f"--- Starting {APP_NAME} v{APP_VERSION} (Async) ---")

    app = QApplication.instance()
    if app is None:
        if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
        app = QApplication(sys.argv)

    # Determine application path
    if getattr(sys, 'frozen', False): application_path = os.path.dirname(sys.executable)
    else: application_path = os.path.dirname(os.path.abspath(__file__))
    logger.info(f"Application base path: {application_path}")

    # Load Font
    logger.info("--- Font Setup ---")
    font_path = os.path.join(application_path, "assets", CHAT_FONT_FILENAME)
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1: logger.info(f"Font '{CHAT_FONT_FILENAME}' loaded.")
        else: logger.error(f"Failed to load font: {font_path}")
    else: logger.error(f"Font file not found: {font_path}")
    logger.info("--- Font Setup Done ---")

    # App Metadata & Style
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    # --- Instantiate Components ---
    logger.info("--- Instantiating Application Components ---")
    main_window = None
    try:
        session_service = SessionService()
        upload_service = UploadService() # Upload service handles RAG aspects now

        # --- Choose Backend ---
        backend_adapter = OllamaAdapter() # SWITCH TO OLLAMA
        # backend_adapter = GeminiAdapter() # Original
        # --------------------

        chat_manager = ChatManager(
            backend=backend_adapter,
            session_service=session_service,
            upload_service=upload_service # Pass upload service to ChatManager
        )
        main_window = MainWindow(chat_manager=chat_manager, app_base_path=application_path)
        logger.info("--- Components Instantiated ---")
    except Exception as e:
         logger.exception(" ***** FATAL ERROR DURING COMPONENT INSTANTIATION ***** ")
         try: QMessageBox.critical(None, "Fatal Init Error", f"Failed during component setup:\n{e}\n\nCheck logs.")
         except Exception: print(f"[CRITICAL] Component Init Failed: {e}\nTraceback:\n{traceback.format_exc()}", file=sys.stderr)
         await app.quit()
         return 1

    # --- Initialize ChatManager after UI is created ---
    # This will now attempt Ollama configuration
    QTimer.singleShot(100, chat_manager.initialize)
    logger.info("Scheduled ChatManager initialization.")

    # --- Show Window ---
    if main_window:
        main_window.setGeometry(100, 100, 1100, 850)
        main_window.show()
        logger.info("--- Main Window Shown ---")
    else:
         logger.error("MainWindow instance not created, cannot show window.")
         await app.quit()
         return 1

    # --- Start Event Loop ---
    logger.info("--- Starting Application Event Loop (via qasync) ---")
    await asyncio.Future() # Keep running until loop stops or app quits
    logger.info(f"--- Application Event Loop Finished ---")
    return 0


# --- Main Execution Block ---
if __name__ == "__main__":
    try:
        exit_code = qasync.run(async_main())
        sys.exit(exit_code)
    except RuntimeError as e:
        logger.critical(f"RuntimeError during qasync execution: {e}", exc_info=True)
        try:
            _dummy_app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Runtime Error", f"Application failed to run:\n{e}\n\nCheck logs.")
        except Exception: pass
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Unhandled exception during application startup/run: {e}", exc_info=True)
        try:
            _dummy_app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Unhandled Exception", f"An unexpected error occurred:\n{e}\n\nCheck logs.")
        except Exception: pass
        sys.exit(1)