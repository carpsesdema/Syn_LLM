# Syn_LLM/core/chat_manager.py
# UPDATED FILE - Modified RAG prompt template

import logging
import asyncio
import os
import re # Import re for keyword checking
from typing import List, Optional, Dict, Any

# --- PyQt6 Imports ---
from PyQt6.QtCore import QObject, pyqtSignal, QTimer # Import QObject and pyqtSignal

# --- Local Imports ---
from core.models import ChatMessage, USER_ROLE, MODEL_ROLE, SYSTEM_ROLE, ERROR_ROLE
from backend.interface import BackendInterface
from services.session_service import SessionService
# Ensure UploadService is imported if type hint is needed (it's passed in __init__)
from services.upload_service import UploadService, VECTOR_DB_SERVICE_AVAILABLE
# --- ADDED ---
from services.vector_db_service import VectorDBService
# -----------
from utils import constants # For default model name etc.
# Import might be needed if used, ensure it exists and is necessary
try:
    from config import get_api_key
except ImportError:
    def get_api_key(): # Dummy function if config isn't essential
        return None
    logging.info("config.py not found or get_api_key not defined, using dummy.")


logger = logging.getLogger(__name__)

class ChatManager(QObject):
    """
    Manages the application's core logic, state, and coordinates
    interactions between UI, Backend, Services (including RAG via UploadService).
    Emits signals that MainWindow adapts to update the ChatListModel.
    """

    # --- Signals for UI Communication ---
    # These signals remain the same; MainWindow adapts their handling
    history_changed = pyqtSignal(list) # Carries List[ChatMessage]
    new_message_added = pyqtSignal(object) # Carries ChatMessage
    status_update = pyqtSignal(str, str, bool, int)
    error_occurred = pyqtSignal(str, bool)
    busy_state_changed = pyqtSignal(bool)
    config_state_changed = pyqtSignal(str, bool)
    stream_chunk_received = pyqtSignal(str) # Carries chunk str
    stream_finished = pyqtSignal()
    stream_started = pyqtSignal(str) # Carries role str

    # --- Technical Keywords for RAG Triggering ---
    # Adjusted set - more specific, includes regex patterns needing re.search
    _TECHNICAL_KEYWORDS = {
        'python', 'code', 'error', 'fix', 'implement', 'explain', 'how to',
        'def ', 'class ', 'import ', ' module', ' function', ' method',
        ' attribute', ' bug', ' issue', ' traceback', ' install', ' pip',
        ' library', ' package', ' api', ' request', ' data', ' typeerror',
        ' indexerror', ' keyerror', ' exception', ' syntax', ' logic', ' algorithm',
        ' self.', ' args', ' kwargs', ' return', ' yield', ' async', ' await',
        ' decorator', ' lambda', ' list', ' dict', ' tuple', ' set'
    }
    _GREETING_PATTERNS = re.compile(r"^\s*(hi|hello|hey|yo|sup|good\s+(morning|afternoon|evening)|how\s+are\s+you)\b.*", re.IGNORECASE)
    _CODE_FENCE_PATTERN = re.compile(r"```")

    def __init__(self, backend: BackendInterface, session_service: SessionService, upload_service: UploadService, parent=None):
        super().__init__(parent)
        logger.info("ChatManager initializing...")
        if not backend: raise ValueError("BackendInterface instance is required.")
        if not session_service: raise ValueError("SessionService instance is required.")
        if not upload_service: raise ValueError("UploadService instance is required.")

        self._backend = backend
        self._session_service = session_service
        self._upload_service = upload_service # Handles uploads and RAG DB interactions

        # --- Core State ---
        self._conversation_history: List[ChatMessage] = []
        self._current_model_name: str = constants.DEFAULT_MODEL_NAME # Default might change based on backend
        self._current_personality_prompt: Optional[str] = None
        self._current_session_filepath: Optional[str] = None
        self._is_busy: bool = False
        self._api_configured_successfully: bool = False # Backend configured status
        self._vector_db_initialized: bool = False # RAG DB status

        # Internal task tracking
        self._current_backend_task: Optional[asyncio.Task] = None

        # --- ADDED: Store reference to VectorDBService (from UploadService) ---
        # Ensure VectorDBService is correctly referenced if needed later
        self._vector_db_service: Optional[VectorDBService] = None
        if VECTOR_DB_SERVICE_AVAILABLE and hasattr(upload_service, '_vector_db_service'):
            self._vector_db_service = getattr(upload_service, '_vector_db_service', None)
        if not self._vector_db_service:
             logger.warning("ChatManager could not get VectorDBService reference from UploadService or service unavailable!")
        # ------------------------------------------------------------------

        logger.info("ChatManager initialized.")

    def initialize(self):
        """Initializes the ChatManager, loads last session, configures backend, and checks RAG DB."""
        logger.info("ChatManager: Initializing state...")
        self.status_update.emit("Initializing...", "#e5c07b", False, 0)
        try:
            model, personality, history = self._session_service.get_last_session()
            self._conversation_history = history
            self._current_personality_prompt = personality
            self._current_model_name = model if model else self._get_default_model_for_backend()
            logger.info(f"Loaded last session state. Model: {self._current_model_name}, Pers: {'Set' if personality else 'None'}, Hist: {len(history)}")

            self._configure_backend()

            # Ensure UploadService has the method before calling (remains same)
            if hasattr(self._upload_service, 'is_vector_db_ready') and callable(self._upload_service.is_vector_db_ready):
                self._vector_db_initialized = self._upload_service.is_vector_db_ready()
                if self._vector_db_initialized: logger.info("RAG Vector DB is initialized.")
                else: logger.warning("RAG Vector DB is not initialized (check logs).")
            else:
                 logger.error("UploadService does not have is_vector_db_ready method. Cannot check RAG status.")
                 self._vector_db_initialized = False

            # Emit history_changed for MainWindow to load into the model
            self.history_changed.emit(self._conversation_history[:]) # Send a copy
            self.config_state_changed.emit(self._current_model_name, bool(self._current_personality_prompt))
            self.update_status_based_on_state()

        except Exception as e:
            logger.exception("Error during ChatManager initialization:")
            self.error_occurred.emit(f"Initialization failed: {e}", True)
            self._conversation_history = []
            self.history_changed.emit(self._conversation_history[:]) # Send empty list
            self.update_status_based_on_state()

    def _get_default_model_for_backend(self) -> str:
        """Returns a sensible default model name based on the backend type, prioritizing constants."""
        # (No changes needed here)
        backend_class_name = type(self._backend).__name__
        logger.debug(f"Determining default model for backend: {backend_class_name}")
        if "OllamaAdapter" in backend_class_name:
             ollama_const = getattr(constants, 'DEFAULT_OLLAMA_MODEL', None)
             if ollama_const: logger.debug(f"Using DEFAULT_OLLAMA_MODEL: {ollama_const}"); return ollama_const
             else: adapter_default = getattr(self._backend, 'DEFAULT_MODEL', None); logger.warning(f"DEFAULT_OLLAMA_MODEL not in constants, using adapter default ({adapter_default}) or overall."); return adapter_default or constants.DEFAULT_MODEL_NAME
        elif "GeminiAdapter" in backend_class_name:
             gemini_const = getattr(constants, 'DEFAULT_GEMINI_MODEL_NAME', None)
             if gemini_const: logger.debug(f"Using DEFAULT_GEMINI_MODEL_NAME: {gemini_const}"); return gemini_const
             else: logger.debug(f"Using general DEFAULT_MODEL_NAME for Gemini: {constants.DEFAULT_MODEL_NAME}"); return constants.DEFAULT_MODEL_NAME
        else: logger.debug(f"Using general DEFAULT_MODEL_NAME for unknown backend: {constants.DEFAULT_MODEL_NAME}"); return constants.DEFAULT_MODEL_NAME

    def _configure_backend(self) -> bool:
        """Configures or re-configures the backend adapter."""
        # (No changes needed here)
        api_key = get_api_key() if "Gemini" in type(self._backend).__name__ else None
        logger.info(f"Attempting backend config. Backend: {type(self._backend).__name__}, Model: {self._current_model_name}, Key Needed: {bool(api_key)}")
        self._api_configured_successfully = self._backend.configure(api_key=api_key, model_name=self._current_model_name, system_prompt=self._current_personality_prompt)
        if self._api_configured_successfully: logger.info(f"Backend configured successfully for '{self._current_model_name}'.")
        else: err = self._backend.get_last_error() or "Unknown config error."; logger.error(f"Backend config failed: {err}"); self.error_occurred.emit(f"Backend Config Failed: {err}", False)
        self.update_status_based_on_state()
        return self._api_configured_successfully

    def update_status_based_on_state(self):
        """Emits a status update based on the current configuration and busy state."""
        # (No changes needed here)
        if self._is_busy: self.status_update.emit("AI responding...", "#e5c07b", False, 0)
        elif not self._api_configured_successfully:
            err = self._backend.get_last_error() or "Config failed."
            if "api key" in err.lower(): err = "API Key Missing/Invalid"
            elif "library not installed" in err.lower(): err = "Required Library Missing"
            elif "Connection refused" in err: err = "Connection Refused (Server Down?)"
            elif "model not found" in err.lower(): err = f"Model '{self._current_model_name}' Not Found"
            self.status_update.emit(f"Error: {err}", "#e06c75", False, 0)
        else:
            status = "Ready";
            if self._current_personality_prompt: status += " (P)"
            if hasattr(self, '_vector_db_initialized') and self._vector_db_initialized: status += " (RAG)"
            self.status_update.emit(status, "#98c379", False, 0)

    def set_model(self, model_name: str):
        """Sets a new model and reconfigures the backend."""
        # (No changes needed here)
        logger.info(f"Model selection changed to: {model_name}")
        if model_name == self._current_model_name: return
        self._current_model_name = model_name
        self._configure_backend()
        self.config_state_changed.emit(self._current_model_name, bool(self._current_personality_prompt))
        self._save_current_state_to_last_session()

    def set_personality(self, prompt: Optional[str]):
        """Sets a new personality prompt and reconfigures the backend."""
        # (No changes needed here)
        logger.info(f"Personality update requested. New: {'Set' if prompt else 'None'}")
        new_prompt_norm = prompt.strip() if prompt else None
        if new_prompt_norm == self._current_personality_prompt: return
        self._current_personality_prompt = new_prompt_norm
        self._configure_backend()
        self.config_state_changed.emit(self._current_model_name, bool(self._current_personality_prompt))
        self.status_update.emit("Personality updated.", "#98c379", True, 3000)
        self._save_current_state_to_last_session()

    def start_new_chat(self):
        """Clears the current chat history and state."""
        logger.info("Starting new chat session.")
        self._cancel_backend_task()
        self._conversation_history = []
        self._current_session_filepath = None
        self.history_changed.emit(self._conversation_history[:]) # Emit empty list copy
        self._session_service.clear_last_session_file()
        self.update_status_based_on_state()
        logger.info("New chat session started.")

    def load_chat_session(self, filepath: str):
        """Loads a chat session from a file."""
        logger.info(f"Loading chat session from: {filepath}")
        self._cancel_backend_task()
        try:
            model, personality, history = self._session_service.load_session(filepath)
            if history is None: self.status_update.emit(f"Failed load: {os.path.basename(filepath)}", "#e06c75", True, 5000); return
            self._conversation_history = history; self._current_personality_prompt = personality; self._current_model_name = model if model else self._get_default_model_for_backend(); self._current_session_filepath = filepath
            logger.info(f"Session loaded. M: {self._current_model_name}, P: {'Set' if personality else 'None'}, H: {len(history)}")
            self._configure_backend()
            self.history_changed.emit(self._conversation_history[:]) # Emit loaded history copy
            self.config_state_changed.emit(self._current_model_name, bool(self._current_personality_prompt))
            self.status_update.emit(f"Session '{os.path.basename(filepath)}' loaded.", "#98c379", True, 4000)
            self._save_current_state_to_last_session()
        except Exception as e: logger.exception(f"Error loading session {filepath}:"); self.error_occurred.emit(f"Failed load session {os.path.basename(filepath)}: {e}", False)

    def save_current_chat_session(self, filepath: str) -> bool:
        """Saves the current chat session to a file."""
        # (No changes needed here)
        logger.info(f"Saving current chat session to: {filepath}")
        try:
            history_to_save = [msg for msg in self._conversation_history if msg.role in [USER_ROLE, MODEL_ROLE]] # Save only user/model roles
            success, final_path = self._session_service.save_session(filepath=filepath, history=history_to_save, model_name=self._current_model_name, personality=self._current_personality_prompt)
            if success and final_path:
                self._current_session_filepath = final_path; self.status_update.emit(f"Session saved as '{os.path.basename(final_path)}'.", "#98c379", True, 4000); self._save_current_state_to_last_session(); return True
            else: logger.error(f"Failed save session to {filepath}"); self.error_occurred.emit(f"Failed save: {os.path.basename(filepath)}", False); return False
        except Exception as e: logger.exception(f"Error saving session {filepath}:"); self.error_occurred.emit(f"Error saving: {os.path.basename(filepath)}: {e}", False); return False

    def list_saved_sessions(self) -> List[str]:
         # (No changes needed here)
         return self._session_service.list_sessions()

    def delete_chat_session(self, filepath: str) -> bool:
         # (No changes needed here)
         logger.info(f"Request to delete session: {filepath}")
         success = self._session_service.delete_session(filepath)
         if success:
              self.status_update.emit(f"Session '{os.path.basename(filepath)}' deleted.", "#98c379", True, 3000)
              if self._current_session_filepath == filepath: logger.info("Deleted active session. Starting new."); self.start_new_chat()
              return True
         else: self.error_occurred.emit(f"Failed delete: {os.path.basename(filepath)}.", False); return False

    def handle_file_upload(self, file_paths: List[str]):
        """Processes uploaded files using UploadService (for RAG DB)."""
        # (No changes needed here, emits SYSTEM message)
        logger.info(f"Handling file upload for RAG DB: {len(file_paths)} files.")
        if self._is_busy: self.status_update.emit("Cannot upload while AI busy.", "#e5c07b", True, 3000); return
        if not isinstance(self._upload_service, UploadService) or not hasattr(self._upload_service, 'process_files_for_context'):
            logger.error("UploadService not valid or missing 'process_files_for_context'. Cannot process upload.")
            self.error_occurred.emit("Upload service error. Cannot process files.", False)
            return
        summary_message = self._upload_service.process_files_for_context(file_paths)
        if summary_message:
            self._add_message_to_history(summary_message) # Add to internal history
            self.new_message_added.emit(summary_message)   # Emit for display
            self._save_current_state_to_last_session() # Save state after potential RAG DB update
            if hasattr(self._upload_service, 'is_vector_db_ready') and callable(self._upload_service.is_vector_db_ready):
                 rag_status_after = self._upload_service.is_vector_db_ready()
                 if rag_status_after != self._vector_db_initialized: self._vector_db_initialized = rag_status_after; self.update_status_based_on_state(); self.config_state_changed.emit(self._current_model_name, bool(self._current_personality_prompt))
            else: logger.warning("Cannot check RAG status after upload.")
        elif summary_message is None: self.error_occurred.emit("Failed to process uploaded files or no content found.", False)

    def handle_directory_upload(self, dir_path: str):
        """Processes an uploaded directory using UploadService (for RAG DB)."""
        # (No changes needed here, emits SYSTEM message)
        logger.info(f"Handling directory upload for RAG DB: {dir_path}")
        if self._is_busy: self.status_update.emit("Cannot upload while AI busy.", "#e5c07b", True, 3000); return
        if not isinstance(self._upload_service, UploadService) or not hasattr(self._upload_service, 'process_directory_for_context'):
            logger.error("UploadService not valid or missing 'process_directory_for_context'. Cannot process upload.")
            self.error_occurred.emit("Upload service error. Cannot process directory.", False)
            return
        self.status_update.emit(f"Scanning directory for RAG: {os.path.basename(dir_path)}...", "#e5c07b", False, 0)
        summary_message = self._upload_service.process_directory_for_context(dir_path)
        self.update_status_based_on_state() # Clear scanning message
        if summary_message:
             self._add_message_to_history(summary_message) # Add to internal history
             self.new_message_added.emit(summary_message)   # Emit for display
             self._save_current_state_to_last_session()
             if hasattr(self._upload_service, 'is_vector_db_ready') and callable(self._upload_service.is_vector_db_ready):
                 rag_status_after = self._upload_service.is_vector_db_ready()
                 if rag_status_after != self._vector_db_initialized: self._vector_db_initialized = rag_status_after; self.update_status_based_on_state(); self.config_state_changed.emit(self._current_model_name, bool(self._current_personality_prompt))
             else: logger.warning("Cannot check RAG status after upload.")
        elif summary_message is None: self.error_occurred.emit(f"Failed process directory '{os.path.basename(dir_path)}' or no content.", False)

    # --- Helper to determine if RAG should be performed ---
    def _should_perform_rag(self, query: str) -> bool:
        """Checks if the query likely requires RAG based on keywords and structure."""
        # (No changes needed here)
        if not hasattr(self, '_vector_db_initialized') or not self._vector_db_initialized:
            return False # Cannot perform RAG if DB isn't ready
        query_lower = query.lower().strip()
        if len(query) < 20 and self._GREETING_PATTERNS.match(query_lower):
            logger.debug(f"Query '{query[:30]}...' looks like a short greeting, skipping RAG.")
            return False
        if len(query) < 10: # Very short, less likely technical
             logger.debug(f"Query '{query[:30]}...' too short, likely chat, skipping RAG.")
             return False
        if self._CODE_FENCE_PATTERN.search(query):
             logger.debug(f"Query contains code fences, performing RAG.")
             return True
        if any(keyword in query_lower for keyword in self._TECHNICAL_KEYWORDS):
            logger.debug(f"Query '{query[:30]}...' contains technical keyword, performing RAG.")
            return True
        if re.search(r"[_.(]", query) and len(query) > 15:
             logger.debug(f"Query '{query[:30]}...' contains code-like characters, performing RAG.")
             return True
        logger.debug(f"Query '{query[:30]}...' doesn't strongly suggest technical content, skipping RAG.")
        return False

    # --- process_user_message ---
    def process_user_message(self, text: str, image_data: List[Dict[str, Any]] = None):
        """
        Handles user input (text and optional images), adds to history,
        conditionally retrieves RAG context, triggers backend.
        """
        logger.info("Processing user message...")
        if self._is_busy:
            logger.warning("Attempted send while busy.")
            self.status_update.emit("AI is busy, please wait.", "#e5c07b", True, 2000) # Notify user
            return
        if not self._api_configured_successfully:
            logger.error("Cannot send, API not configured.")
            self.error_occurred.emit("API not configured. Cannot send message.", False) # Notify user
            return

        user_query_text = text.strip()
        image_data_list = image_data or []

        if not user_query_text and not image_data_list: logger.warning("Attempted send empty message (no text or images)."); return

        message_parts = []
        if user_query_text: message_parts.append(user_query_text)
        if image_data_list:
            valid_image_data = [img for img in image_data_list if isinstance(img, dict) and img.get("type") == "image" and img.get("data")]
            if valid_image_data: message_parts.extend(valid_image_data); logger.info(f"Including {len(valid_image_data)} images in user message.")
            else: logger.warning("Image data list provided but contained no valid image dictionaries.")

        # --- Add User Message to History & Emit ---
        try:
            user_message = ChatMessage(role=USER_ROLE, parts=message_parts)
            self._add_message_to_history(user_message) # Add to internal history
            self.new_message_added.emit(user_message) # Emit for display via model
            logger.debug("User message added to history and signaled for display.")
        except Exception as e_add:
            logger.exception("Failed to create or add user message"); self.error_occurred.emit(f"Error processing your message: {e_add}", False); return

        # --- Conditional RAG ---
        rag_context_str = ""; rag_info_msg = None
        perform_rag = self._should_perform_rag(user_query_text) if user_query_text else False

        if perform_rag:
            logger.info("Attempting RAG retrieval...")
            try:
                if not isinstance(self._upload_service, UploadService) or not hasattr(self._upload_service, 'query_vector_db'): raise TypeError("UploadService not valid or missing 'query_vector_db'.")
                relevant_chunks = self._upload_service.query_vector_db(user_query_text, n_results=constants.RAG_NUM_RESULTS)
                if relevant_chunks:
                    context_parts = []; retrieved_chunks_details = []
                    for i, chunk in enumerate(relevant_chunks):
                        metadata = chunk.get("metadata", {}); filename = metadata.get("filename", "unknown_source"); code_content = chunk.get("content", "")
                        context_parts.append(f"--- Snippet {i+1} from `{filename}` ---\n```python\n{code_content}\n```\n")
                        retrieved_chunks_details.append(f"{filename} (dist: {chunk.get('distance', -1):.4f})")
                    rag_context_str = ("--- Relevant Code Context Start ---\n" + "\n".join(context_parts) + "--- Relevant Code Context End ---")
                    logger.info(f"Retrieved {len(relevant_chunks)} chunks for RAG: [{', '.join(retrieved_chunks_details)}]")
                    rag_info_msg = ChatMessage(role=SYSTEM_ROLE, parts=["[RAG context added to prompt (not shown)]"], metadata={"is_internal": True})
                else: logger.info("No relevant RAG context found for technical query.")
            except Exception as e_rag:
                logger.exception("Error retrieving RAG context:")
                rag_info_msg = ChatMessage(role=ERROR_ROLE, parts=["[Error retrieving RAG context]"], metadata={"is_internal": True})
                rag_context_str = ""
        else: logger.info("Skipping RAG based on user query analysis or lack of text.")

        # --- Emit RAG Info Message (if any) ---
        if rag_info_msg:
            self._add_message_to_history(rag_info_msg) # Add to internal history
            self.new_message_added.emit(rag_info_msg)   # Emit for display

        # --- Prepare history and final prompt for backend ---
        history_for_backend = [msg for msg in self._conversation_history if msg.role in [USER_ROLE, MODEL_ROLE] and (not msg.metadata or not msg.metadata.get("is_internal"))]
        final_prompt_message: Optional[ChatMessage] = None

        # ***** MODIFICATION START *****
        if rag_context_str:
            # New prompt template - less directive about using RAG context
            prompt_template = (
                "User Query: '{query}'\n\n"
                "[Reference Code Context (for style/names if relevant)]:\n{context}\n\n"
                "Provide a comprehensive and helpful answer to the user's query, drawing on general programming knowledge and best practices. "
                "Refer to the context only if directly needed for consistency."
            )
            # ***** MODIFICATION END *****

            augmented_text = prompt_template.format(context=rag_context_str, query=user_query_text)
            logger.debug(f"Augmented prompt created. Length: {len(augmented_text)}")
            final_parts = [augmented_text];
            if image_data_list: final_parts.extend(image_data_list)
            final_prompt_message = ChatMessage(role=USER_ROLE, parts=final_parts, metadata={"is_rag_augmented": True})
            if history_for_backend: history_for_backend[-1] = final_prompt_message # Replace last user msg
            else: logger.error("History empty when trying to replace with augmented prompt!"); return
        else:
            if not history_for_backend: logger.error("History is empty after adding user message, cannot proceed."); return
            final_prompt_message = history_for_backend[-1]

        # --- Trigger backend request ---
        if final_prompt_message:
            self._set_busy_state(True)
            logger.info("Creating backend response task...")
            self._current_backend_task = asyncio.create_task(self._get_backend_response(history_for_backend))
        else: logger.error("Could not determine final prompt message. Aborting backend request."); self._set_busy_state(False)


    async def _get_backend_response(self, history_to_send: List[ChatMessage]):
        """Internal async method to handle the backend streaming call."""
        logger.info("Starting backend response task...")
        streaming_started = False
        stream_iterator = None
        response_buffer = ""
        model_message_added = False # Track if placeholder was added

        try:
            if not hasattr(self._backend, 'get_response_stream'): raise AttributeError("Backend has no get_response_stream method")

            logger.info(f"Calling backend stream with {len(history_to_send)} messages.")
            stream_iterator = self._backend.get_response_stream(history_to_send)

            try:
                async for chunk in stream_iterator:
                    if not streaming_started:
                        logger.debug("Stream started, emitting signal.")
                        # Emit stream_started signal - MainWindow will add placeholder to model
                        self.stream_started.emit(MODEL_ROLE)
                        streaming_started = True
                        # Wait briefly to allow placeholder creation? Might not be needed.
                        # await asyncio.sleep(0.01)
                    response_buffer += chunk
                    # Emit chunk - MainWindow will append to model's last message
                    self.stream_chunk_received.emit(chunk)
                logger.info("Stream iterator finished normally.")
            finally:
                 if stream_iterator and hasattr(stream_iterator, 'aclose'):
                     try: await stream_iterator.aclose(); logger.debug("Stream iterator aclosed().")
                     except Exception as e_aclose: logger.warning(f"Error during stream iterator aclose(): {e_aclose}")
                 else: logger.debug("Stream iterator is None or has no aclose() method.")

            # --- Process after successful stream completion ---
            if streaming_started:
                logger.debug("Stream finished, emitting signal.")
                # Emit finished - MainWindow will finalize model's last message
                self.stream_finished.emit()
                # Add final message to internal history AFTER stream signals
                # The actual message data is already updated in the model by MainWindow
                # We just need to add the *final* ChatMessage object to our internal history
                if response_buffer:
                     final_message = ChatMessage(role=MODEL_ROLE, parts=[response_buffer.strip()])
                     # Check if last message in history is the streaming one and update it
                     if self._conversation_history and self._conversation_history[-1].role == MODEL_ROLE and self._conversation_history[-1].metadata.get("is_streaming"):
                          self._conversation_history[-1] = final_message # Replace placeholder
                          logger.debug("Updated internal history with final streamed message.")
                     else: # Fallback: append if placeholder wasn't tracked correctly
                          self._conversation_history.append(final_message)
                          logger.warning("Appended final streamed message, placeholder might not have been tracked.")
                     self._save_current_state_to_last_session()
                     logger.info(f"Streamed AI response finalized in internal history. Length: {len(response_buffer)}")
                else: logger.warning("Stream finished, but response buffer was empty.")
            else:
                # Handle non-streaming response or error before stream start
                if response_buffer:
                    logger.warning("Backend returned content but stream didn't start. Adding as complete message.")
                    model_message = ChatMessage(role=MODEL_ROLE, parts=[response_buffer.strip()])
                    self._add_message_to_history(model_message) # Add to internal history
                    self.new_message_added.emit(model_message)  # Emit for display
                else:
                    logger.warning("Backend returned no response chunks and stream didn't start.")
                    backend_error = self._backend.get_last_error()
                    if backend_error:
                        error_msg_obj = ChatMessage(role=ERROR_ROLE, parts=[f"Error: {backend_error}"], metadata={"is_internal": True})
                        self._add_message_to_history(error_msg_obj)
                        self.new_message_added.emit(error_msg_obj)
                    else:
                        sys_msg_obj = ChatMessage(role=SYSTEM_ROLE, parts=["[AI returned empty response or failed before streaming]"], metadata={"is_internal": True})
                        self._add_message_to_history(sys_msg_obj)
                        self.new_message_added.emit(sys_msg_obj)

        except asyncio.CancelledError:
            logger.info("Backend task explicitly cancelled.")
            if streaming_started: self.stream_finished.emit() # Ensure UI finalizes model message
            cancel_msg = ChatMessage(role=SYSTEM_ROLE, parts=["[AI response cancelled by user]"], metadata={"is_internal": True})
            self._add_message_to_history(cancel_msg)
            self.new_message_added.emit(cancel_msg)

        except Exception as e:
            logger.exception("Error during backend response task:")
            if streaming_started: self.stream_finished.emit() # Ensure UI finalizes model message
            error_msg = self._backend.get_last_error() or f"Task Error: {type(e).__name__}"
            error_msg_obj = ChatMessage(role=ERROR_ROLE, parts=[f"Error: {error_msg}"], metadata={"is_internal": True})
            self._add_message_to_history(error_msg_obj)
            self.new_message_added.emit(error_msg_obj)

        finally:
            logger.info("Backend response task finishing (outer finally block).")
            if self._current_backend_task is asyncio.current_task():
                 self._set_busy_state(False); self._current_backend_task = None; logger.info("Busy state reset by the finishing task.")
            else: logger.warning("Task finished, but it's not the current task. Busy state not reset here.")

    def _add_message_to_history(self, message: ChatMessage):
        """Appends a message to internal history. Saves state if user/model."""
        # Simplified: Just add to internal history. Emitting is handled separately.
        self._conversation_history.append(message)
        logger.debug(f"Added message (Role: {message.role}) to internal history (size: {len(self._conversation_history)})")
        # Save state only after adding user/model messages (or errors/system?)
        if message.role in [USER_ROLE, MODEL_ROLE, SYSTEM_ROLE, ERROR_ROLE]:
             self._save_current_state_to_last_session()

    # Methods below are less critical now as MainWindow handles display via model signals
    # def _add_system_message_to_display(self, text: str): ...
    # def _add_error_message_to_history_and_display(self, text: str): ...

    def _set_busy_state(self, is_busy: bool):
        """Updates the busy state and emits signal."""
        # (No changes needed here)
        if self._is_busy != is_busy:
            self._is_busy = is_busy
            logger.debug(f"Setting busy state: {is_busy}")
            self.busy_state_changed.emit(is_busy)
            self.update_status_based_on_state() # Also update status bar text

    def _save_current_state_to_last_session(self):
        """Helper to save the current state (user/model messages) to the last session file."""
        # Filter history based on role before saving - Keep SYSTEM/ERROR messages in history? Maybe not for save.
        history_to_save = [msg for msg in self._conversation_history if msg.role in [USER_ROLE, MODEL_ROLE]]
        self._session_service.save_last_session(
            model_name=self._current_model_name,
            personality=self._current_personality_prompt,
            history=history_to_save
        )
        logger.debug("Saved current state (User/Model) to last session file.")


    def _cancel_backend_task(self):
        """Cancels the currently running backend task, if any."""
        # (No changes needed here)
        if self._current_backend_task and not self._current_backend_task.done():
            logger.info("Cancelling ongoing backend task...")
            self._current_backend_task.cancel()
            logger.debug("Cancellation requested for backend task.")


    def cleanup(self):
         """Perform cleanup actions before application exit."""
         # (No changes needed here)
         logger.info("ChatManager performing cleanup...");
         self._cancel_backend_task();
         self._save_current_state_to_last_session()
         logger.info("ChatManager cleanup complete.")

    # --- Getters ---
    def get_current_history(self) -> List[ChatMessage]:
        # Return a copy of the internal history
        return self._conversation_history[:]

    def get_current_model(self) -> str:
         # (No changes needed here)
         return self._current_model_name

    def get_current_personality(self) -> Optional[str]:
         # (No changes needed here)
         return self._current_personality_prompt

    def is_api_ready(self) -> bool:
         # (No changes needed here)
         return self._api_configured_successfully

    def is_rag_active(self) -> bool:
        # (No changes needed here)
        return hasattr(self, '_vector_db_initialized') and self._vector_db_initialized

    def get_rag_contents(self) -> List[Dict[str, Any]]:
        """Retrieves all metadata entries from the RAG vector database."""
        # (No changes needed here)
        if not self._vector_db_service or not self._vector_db_service.is_ready():
            logger.warning("Cannot get RAG contents: VectorDBService not available or not ready.")
            return []
        try:
            if hasattr(self._vector_db_service, 'get_all_metadata') and callable(self._vector_db_service.get_all_metadata):
                return self._vector_db_service.get_all_metadata()
            else:
                logger.error("VectorDBService instance is missing 'get_all_metadata' method.")
                return []
        except Exception as e:
            logger.exception("Error retrieving RAG contents from VectorDBService:")
            return []