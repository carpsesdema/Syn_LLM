# SynaChat/utils/constants.py
# UPDATED FILE - Changed RAG_NUM_RESULTS to 2

import os
import sys
import logging

logger = logging.getLogger(__name__) # Get logger for this module

# --- Core Application Settings ---
APP_NAME = "SynapseChat"
APP_VERSION = "3.3-ChromaDB" # Updated version

# --- API & Model Configuration ---
DEFAULT_OLLAMA_MODEL = "codellama:13b" # Keep the 13b model from previous step
# AVAILABLE_GEMINI_MODELS = [ ... ] # Kept for reference if needed
# DEFAULT_GEMINI_MODEL_NAME = "gemini-1.5-pro-preview-0416"
DEFAULT_MODEL_NAME = DEFAULT_OLLAMA_MODEL # Keep this linked to the Ollama default

# --- UI Appearance ---
CHAT_FONT_FILENAME = "JetBrainsMono-Regular.ttf"
CHAT_FONT_FAMILY = "JetBrains Mono"
CHAT_FONT_SIZE = 10
MAX_CHAT_AREA_WIDTH = 900
LOADING_GIF_FILENAME = "loading.gif"

# --- File Paths & Storage ---
# Determine the base path (works for frozen and non-frozen)
if getattr(sys, 'frozen', False):
    # If frozen, the executable is usually in the root.
    APP_BASE_DIR = os.path.dirname(sys.executable)
    logger.info(f"[Constants] Running frozen. APP_BASE_DIR: {APP_BASE_DIR}")
else:
    # If not frozen, constants.py is in Llama_Syn/utils/.
    # Go up two levels to get the project root (Llama_Syn).
    APP_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logger.info(f"[Constants] Running as script. APP_BASE_DIR: {APP_BASE_DIR}")

# --- User Specific Data ---
USER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".synapse_chat_data")
CONVERSATIONS_DIR_NAME = "conversations"
CONVERSATIONS_DIR = os.path.join(USER_DATA_DIR, CONVERSATIONS_DIR_NAME)
LAST_SESSION_FILENAME = ".last_session_state.json"
LAST_SESSION_FILEPATH = os.path.join(USER_DATA_DIR, LAST_SESSION_FILENAME)
logger.info(f"[Constants] USER_DATA_DIR: {USER_DATA_DIR}")

# --- Application Assets ---
ASSETS_DIR_NAME = "assets"
# Assets path is directly under the calculated APP_BASE_DIR
ASSETS_PATH = os.path.join(APP_BASE_DIR, ASSETS_DIR_NAME)
logger.info(f"[Constants] ASSETS_PATH: {ASSETS_PATH}")

# --- UI Stylesheets ---
STYLESHEET_FILENAME = "style.qss"
BUBBLE_STYLESHEET_FILENAME = "bubble_style.qss"
# UI directory is directly under the calculated APP_BASE_DIR
UI_DIR_NAME = "ui"
UI_DIR_PATH = os.path.join(APP_BASE_DIR, UI_DIR_NAME)
logger.info(f"[Constants] UI_DIR_PATH: {UI_DIR_PATH}")

# Construct full paths for stylesheets based on UI_DIR_PATH
MAIN_STYLESHEET_PATH = os.path.join(UI_DIR_PATH, STYLESHEET_FILENAME)
STYLE_PATHS_TO_CHECK = [ MAIN_STYLESHEET_PATH ] # List containing the path to check
BUBBLE_STYLESHEET_PATH = os.path.join(UI_DIR_PATH, BUBBLE_STYLESHEET_FILENAME)
logger.info(f"[Constants] Main style path: {MAIN_STYLESHEET_PATH}")
logger.info(f"[Constants] Bubble style path: {BUBBLE_STYLESHEET_PATH}")


# --- Upload Handling (General) ---
MAX_SCAN_DEPTH = 5
ALLOWED_TEXT_EXTENSIONS = {
    '.txt', '.py', '.md', '.json', '.js', '.html', '.css', '.c', '.cpp', '.h',
    '.java', '.cs', '.xml', '.yaml', '.yml', '.sh', '.bat', '.ps1', '.log',
    '.csv', '.tsv', '.ini', '.cfg', '.sql', '.rb', '.php', '.go', '.rs', '.swift',
    '.kt', '.kts', '.scala', '.lua', '.pl', '.pm', '.r', '.dart', '.tex', '.toml',
    '.pdf', '.docx' # Add PDF and DOCX support
}
DEFAULT_IGNORED_DIRS = {
    '.git', '__pycache__', '.venv', 'venv', '.env', 'env',
    'node_modules', 'build', 'dist', '.vscode', '.idea', '.pytest_cache',
    '*.pyc', '*.log', '*.tmp', '*.bak', '*.swp', # Note: Patterns need explicit handling in scan
    'site-packages', '.mypy_cache', 'lib', 'include', 'bin', 'Scripts'
}

# --- RAG Specific Configuration (Using ChromaDB or FAISS) ---
# Determine which vector DB is actively used (you might need to check vector_db_service.py)
# Assuming Chroma for now based on previous context:
VECTOR_DB_DIR_NAME = "chroma_store" # Directory name for Chroma persistent storage
VECTOR_DB_PATH = os.path.join(USER_DATA_DIR, VECTOR_DB_DIR_NAME) # Path to the DB directory
VECTOR_DB_COLLECTION_NAME = "synachat_context" # Name for the ChromaDB collection

RAG_CHUNK_SIZE = 1000 # Characters per chunk
RAG_CHUNK_OVERLAP = 150 # Overlap between chunks
RAG_NUM_RESULTS = 2 # CHANGED HERE: Number of chunks to retrieve for context (was 3)
RAG_MAX_FILE_SIZE_MB = 50 # Max file size (in MB) to process for RAG DB
# RAG_RELEVANCE_THRESHOLD = 0.7 # Chroma uses distance, lower is better

logger.info(f"[Constants] VECTOR_DB_PATH (Check vector_db_service): {VECTOR_DB_PATH}")
logger.info(f"[Constants] VECTOR_DB_COLLECTION_NAME: {VECTOR_DB_COLLECTION_NAME}")


# --- Logging Configuration ---
LOG_LEVEL = "DEBUG"
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s [%(module)s.%(funcName)s:%(lineno)d] - %(message)s'