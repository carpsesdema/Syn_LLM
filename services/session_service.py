# SynChat/services/session_service.py
# NEW FILE
import os
import json
import re
import datetime
import logging
from typing import Dict, Any, Optional, Tuple, List

# Use constants for paths and filenames
from utils import constants
from core.models import ChatMessage # Use the ChatMessage model

logger = logging.getLogger(__name__)

class SessionService:
    """Handles loading, saving, listing, and deleting chat sessions."""

    def __init__(self):
        # Ensure base data directory exists
        try:
            os.makedirs(constants.USER_DATA_DIR, exist_ok=True)
            logger.info(f"User data directory ensured: {constants.USER_DATA_DIR}")
        except OSError as e:
            logger.critical(f"CRITICAL: Could not create base data directory {constants.USER_DATA_DIR}: {e}")
            # Decide how to handle - maybe raise? For now, log critical.

        # Ensure conversations subdirectory exists
        try:
            os.makedirs(constants.CONVERSATIONS_DIR, exist_ok=True)
            logger.info(f"Conversations directory ensured: {constants.CONVERSATIONS_DIR}")
        except OSError as e:
             logger.error(f"Could not create conversations directory {constants.CONVERSATIONS_DIR}: {e}")
             # Service might still function for last_session, don't raise yet.

        logger.info("SessionService initialized.")
        logger.info(f"  Conversations Path: {constants.CONVERSATIONS_DIR}")
        logger.info(f"  Last Session Path: {constants.LAST_SESSION_FILEPATH}")

    # --- Last Session State ---

    def get_last_session(self) -> Tuple[Optional[str], Optional[str], List[ChatMessage]]:
        """Loads the state from the last session file."""
        logger.info(f"Attempting to load last session state from: {constants.LAST_SESSION_FILEPATH}")
        if not os.path.exists(constants.LAST_SESSION_FILEPATH):
             logger.info("Last session file not found. Starting fresh.")
             return None, None, []
        return self._load_from_file(constants.LAST_SESSION_FILEPATH)

    def save_last_session(self, model_name: Optional[str], personality: Optional[str], history: List[ChatMessage]) -> bool:
        """Saves the current state to the last session file."""
        logger.info(f"Attempting to save last session state to: {constants.LAST_SESSION_FILEPATH}")
        if not isinstance(history, list):
            logger.error(f"History provided for saving last session is not a list ({type(history)}). Aborting save.")
            return False

        # Convert ChatMessage objects to dictionaries for JSON serialization
        history_dicts = [self._chatmessage_to_dict(msg) for msg in history]

        data_to_save = {
            "model_name": model_name,
            "personality_prompt": personality,
            "history": history_dicts, # Save list of dictionaries
            "metadata": {
                "save_timestamp": datetime.datetime.now().isoformat(),
                "source": "last_session"
            }
        }
        # Ensure the base data directory exists before saving
        try:
             os.makedirs(os.path.dirname(constants.LAST_SESSION_FILEPATH), exist_ok=True)
        except OSError as e:
             logger.error(f"Cannot save last session: Failed to create directory {os.path.dirname(constants.LAST_SESSION_FILEPATH)}: {e}")
             return False

        return self._save_to_file(constants.LAST_SESSION_FILEPATH, data_to_save)

    def clear_last_session_file(self) -> bool:
        """Clears the last session state file."""
        logger.info(f"Attempting to clear last session state file: {constants.LAST_SESSION_FILEPATH}")
        try:
            if os.path.exists(constants.LAST_SESSION_FILEPATH):
                os.remove(constants.LAST_SESSION_FILEPATH)
                logger.info("Last session state file deleted.")
                return True
            else:
                logger.info("Last session state file did not exist.")
                return True # Considered success if it's already gone
        except OSError as e:
            logger.error(f"Error deleting last session state file {constants.LAST_SESSION_FILEPATH}: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error clearing last session state file: {e}")
            return False

    # --- Named Conversation Management ---

    def list_sessions(self) -> List[str]:
        """Returns a sorted list of full paths to saved conversation files."""
        logger.info(f"Listing conversations in: {constants.CONVERSATIONS_DIR}")
        full_paths = []
        try:
            if not os.path.isdir(constants.CONVERSATIONS_DIR):
                 logger.warning(f"Conversations directory not found: {constants.CONVERSATIONS_DIR}")
                 return []

            filenames = [
                f for f in os.listdir(constants.CONVERSATIONS_DIR)
                if os.path.isfile(os.path.join(constants.CONVERSATIONS_DIR, f)) and f.lower().endswith(".json")
            ]
            full_paths = [os.path.join(constants.CONVERSATIONS_DIR, f) for f in filenames]
            # Sort by modification time (newest first)
            try:
                 full_paths.sort(key=os.path.getmtime, reverse=True)
            except Exception as sort_e:
                 logger.warning(f"Could not sort conversations by mtime, falling back to filename sort: {sort_e}")
                 full_paths.sort(key=os.path.basename, reverse=True)

            logger.info(f"Found {len(full_paths)} conversation files.")
        except OSError as e:
            logger.error(f"Error listing conversations in {constants.CONVERSATIONS_DIR}: {e}")
        return full_paths

    def load_session(self, filepath: str) -> Tuple[Optional[str], Optional[str], List[ChatMessage]]:
        """Loads session data from a specific conversation file path."""
        if not filepath or not isinstance(filepath, str) or not os.path.isabs(filepath):
             logger.error(f"Invalid or non-absolute filepath provided for loading: {filepath}")
             return None, None, []
        if not filepath.lower().endswith(".json"):
            logger.error(f"Filepath provided for loading is not a .json file: {filepath}")
            return None, None, []
        if not os.path.exists(filepath):
            logger.error(f"Conversation file not found at specified path: {filepath}")
            return None, None, []

        # Security check: Ensure file is within the conversations directory
        if not self._is_path_safe(filepath):
            logger.error(f"Attempt to load file outside designated conversations directory blocked: {filepath}")
            return None, None, []

        logger.info(f"Attempting to load conversation from: {filepath}")
        return self._load_from_file(filepath)

    def save_session(self, filepath: str, history: List[ChatMessage], model_name: Optional[str], personality: Optional[str]) -> Tuple[bool, Optional[str]]:
        """
        Saves session data to a specific conversation file path.
        Assumes filepath is absolute and overwrite is handled by caller if needed.
        """
        if not filepath or not isinstance(filepath, str) or not os.path.isabs(filepath):
             logger.error(f"Invalid or non-absolute filepath provided for saving: {filepath}")
             return False, None
        if not filepath.lower().endswith(".json"):
             logger.warning(f"Filepath for saving does not end with .json: {filepath}. Appending.")
             filepath += ".json"

        # Security check: Ensure file path is within the conversations directory
        if not self._is_path_safe(filepath):
             logger.error(f"Attempt to save file outside designated conversations directory blocked: {filepath}")
             return False, None

        logger.info(f"Saving conversation to: {filepath}")
        if not isinstance(history, list):
            logger.error(f"History provided for saving conversation is not a list ({type(history)}). Aborting save.")
            return False, None

        # Convert ChatMessage objects to dictionaries
        history_dicts = [self._chatmessage_to_dict(msg) for msg in history]

        data_to_save = {
            "model_name": model_name,
            "personality_prompt": personality,
            "history": history_dicts, # Save list of dictionaries
            "metadata": {
                "save_timestamp": datetime.datetime.now().isoformat(),
                "source": "named_conversation",
                "saved_filename": os.path.basename(filepath)
            }
        }

        # Ensure the conversations directory exists
        try:
             os.makedirs(os.path.dirname(filepath), exist_ok=True)
        except OSError as e:
             logger.error(f"Cannot save conversation: Failed to create directory {os.path.dirname(filepath)}: {e}")
             return False, None

        success = self._save_to_file(filepath, data_to_save)
        return success, filepath if success else None

    def delete_session(self, filepath: str) -> bool:
        """Deletes a specific conversation file using its full path."""
        if not filepath or not os.path.isabs(filepath):
             logger.error(f"Invalid or non-absolute filepath provided for deletion: {filepath}")
             return False

        # Security check: Ensure file is within the conversations directory
        if not self._is_path_safe(filepath):
            logger.error(f"Attempt to delete file outside conversations directory blocked: {filepath}")
            return False

        logger.info(f"Attempting to delete conversation file: {filepath}")
        if not os.path.exists(filepath):
            logger.error("File not found for deletion.")
            return False
        try:
            os.remove(filepath)
            logger.info("Conversation file deleted successfully.")
            return True
        except OSError as e:
            logger.error(f"Error deleting file {filepath}: {e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error deleting file {filepath}: {e}")
            return False

    # --- Filename Sanitization ---

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitizes a filename for safe use, ensuring it ends with .json.
        (Moved from original SessionManager)
        """
        if not filename or not isinstance(filename, str): return ""
        name = filename.strip()
        if not name: return ""

        # Ensure .json extension
        base, ext = os.path.splitext(name)
        if not ext: name += ".json"
        elif ext.lower() != ".json": name = base + ".json" # Force .json

        # Basic sanitization (replace common invalid chars)
        invalid_chars = r'[<>:"/\\|?*\x00-\x1F]'
        sanitized = re.sub(invalid_chars, '_', name)
        sanitized = re.sub(r'_+', '_', sanitized) # Collapse multiple underscores
        sanitized = sanitized.strip('_') # Remove leading/trailing underscores

        # Prevent problematic names (dots, reserved names - simplified check)
        if not sanitized or sanitized in ['.', '..'] or sanitized.upper() in [
            'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'LPT1', 'COM2', 'LPT2', 'COM3', 'LPT3', 'COM4', 'LPT4'
        ]:
             logger.warning(f"Filename '{filename}' sanitizes to an invalid/reserved name ('{sanitized}'). Using fallback.")
             # Generate a fallback name if sanitization fails badly
             fallback_base = f"session_invalid_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
             return fallback_base + ".json"

        # Limit length (optional, depends on filesystem)
        max_len = 200 # Example max length
        if len(sanitized) > max_len:
            base, ext = os.path.splitext(sanitized)
            sanitized = base[:max_len - len(ext)] + ext
            logger.warning(f"Sanitized filename truncated due to length: {sanitized}")

        return sanitized

    # --- Internal Helpers ---

    def _load_from_file(self, filepath: str) -> Tuple[Optional[str], Optional[str], List[ChatMessage]]:
        """Internal helper to load and parse session data."""
        logger.debug(f"  Internal load: Reading file {filepath}")
        try:
            with open(filepath, "r", encoding="utf-8") as f: file_content = f.read()
            if not file_content.strip(): logger.warning(f"Session file is empty: {filepath}"); return None, None, []

            data = json.loads(file_content)
            if not isinstance(data, dict): logger.error(f"Invalid format: Session data not dict in {filepath}"); return None, None, []

            model_name = data.get("model_name")
            personality_prompt = data.get("personality_prompt")
            history_data = data.get("history", [])

            # --- Validate and Convert History ---
            history: List[ChatMessage] = []
            if isinstance(history_data, list):
                for i, item in enumerate(history_data):
                    try:
                        if isinstance(item, dict) and 'role' in item and 'parts' in item:
                             # Basic type checks
                             role = str(item['role'])
                             parts_raw = item['parts']
                             timestamp = item.get('timestamp')

                             if not isinstance(parts_raw, list): # Handle single part case
                                 parts_raw = [parts_raw]

                             parts = [str(p) for p in parts_raw if p is not None] # Ensure parts are strings

                             # Validate timestamp format if present
                             if timestamp and isinstance(timestamp, str):
                                 try: datetime.datetime.fromisoformat(timestamp)
                                 except ValueError: timestamp = None # Nullify invalid format

                             # Create ChatMessage object
                             history.append(ChatMessage(role=role, parts=parts, timestamp=timestamp))
                        else:
                             logger.warning(f"Invalid history item format at index {i} in {filepath}. Skipping.")
                    except Exception as e_hist:
                         logger.warning(f"Error processing history item {i} in {filepath}: {e_hist}. Skipping.")
            else:
                logger.warning(f"Loaded history is not a list ({type(history_data)}) in {filepath}. Using empty list.")

            logger.info(f"Session loaded from {os.path.basename(filepath)}. Model: {model_name}, Pers: {'Set' if personality_prompt else 'None'}, Hist: {len(history)}")
            return model_name, personality_prompt, history

        except json.JSONDecodeError as e: logger.error(f"JSON decode error in {filepath}: {e}"); return None, None, []
        except OSError as e: logger.error(f"OS error reading {filepath}: {e}"); return None, None, []
        except Exception as e: logger.exception(f"Unexpected error loading {filepath}: {e}"); return None, None, []

    def _save_to_file(self, filepath: str, data_to_save: Dict[str, Any]) -> bool:
        """Internal helper to save session data to a file."""
        logger.debug(f"  Internal save: Writing to file {filepath}")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            logger.info(f"Session data saved to {os.path.basename(filepath)}.")
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.exception(f"Error saving session file {filepath}: {e}")
            return False

    def _chatmessage_to_dict(self, msg: ChatMessage) -> Dict[str, Any]:
        """Converts a ChatMessage object to a dictionary for JSON."""
        return {
            "role": msg.role,
            "parts": msg.parts,
            "timestamp": msg.timestamp,
            "metadata": msg.metadata # Include metadata if present
        }

    def _is_path_safe(self, filepath: str) -> bool:
        """Checks if the filepath is within the designated conversations directory."""
        try:
            # Normalize both paths for reliable comparison
            safe_dir = os.path.abspath(constants.CONVERSATIONS_DIR)
            target_file = os.path.abspath(filepath)
            # Check if the target file path starts with the safe directory path
            # Append os.sep to ensure it's checking directory containment, not just prefix
            return os.path.commonpath([safe_dir]) == os.path.commonpath([safe_dir, target_file])
            # Alternative stricter check: return target_file.startswith(safe_dir + os.sep)
        except Exception as e:
            logger.error(f"Error during path safety check for '{filepath}': {e}")
            return False