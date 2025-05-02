
import logging
import asyncio
import base64 # Added for image data check
from typing import List, Optional, AsyncGenerator, Dict, Any
import time # For potential debug delays

# Attempt import for type hinting and error checking
try:
    # Assuming the user will install the official 'ollama' library
    import ollama
    API_LIBRARY_AVAILABLE = True
except ImportError:
    ollama = None
    API_LIBRARY_AVAILABLE = False
    logging.warning("OllamaAdapter: 'ollama' library not found. Please install it: pip install ollama")

# Import interface and model
from .interface import BackendInterface
from core.models import ChatMessage, MODEL_ROLE, USER_ROLE, SYSTEM_ROLE # Use roles from core.models

logger = logging.getLogger(__name__)

# --- Helper function to handle StopIteration within the thread ---
_SENTINEL = object() # Use a unique object as sentinel

def _run_ollama_stream_sync(client, model_name, messages) -> List[Dict[str, Any]]:
    """Synchronous helper to run the Ollama stream and collect chunks."""
    all_chunks = []
    try:
        logger.debug(f"[Thread {time.time():.2f}] Calling ollama.chat (sync within thread)...")
        # Use the synchronous client or adapt the async call if necessary
        # Assuming ollama library provides a sync interface or we adapt
        # For simplicity, let's assume a synchronous call exists or we block here.
        # If using the async client, we'd need `asyncio.run` inside the thread,
        # which is generally discouraged. A dedicated sync client is better.
        # Let's *assume* the async client's stream can be iterated synchronously
        # *within this thread context* for the sake of the pattern.
        # **This assumption might be incorrect depending on ollama library's implementation.**
        # A more robust solution might involve a queue between the thread and the async gen.

        # --- SIMPLIFIED ASSUMPTION FOR PATTERN ---
        # Replace with actual synchronous streaming call if available,
        # otherwise this pattern needs refinement (e.g., using a queue).
        stream = client.chat( # Pretend this is sync or blocks appropriately here
            model=model_name,
            messages=messages,
            stream=True
        )
        logger.debug(f"[Thread {time.time():.2f}] Got stream iterator.")
        for chunk in stream:
            # logger.debug(f"[Thread {time.time():.2f}] Received chunk: {str(chunk)[:100]}")
            all_chunks.append(chunk)
            # Check for done/error within the thread as well
            if chunk.get('done', False):
                if chunk.get('error'):
                    logger.error(f"[Thread {time.time():.2f}] Error in stream chunk: {chunk['error']}")
                else:
                    logger.debug(f"[Thread {time.time():.2f}] Stream done flag received.")
                break # Stop collecting on done/error
        logger.debug(f"[Thread {time.time():.2f}] Finished iterating stream. Collected {len(all_chunks)} chunks.")
        # --- END SIMPLIFIED ASSUMPTION ---

    except Exception as e:
        logger.exception(f"[Thread {time.time():.2f}] Exception during synchronous Ollama stream processing:")
        # Append an error chunk to signal failure back to the async generator
        all_chunks.append({"error": f"Thread Error: {type(e).__name__} - {e}"})
    return all_chunks


class OllamaAdapter(BackendInterface):
    """Implementation of the BackendInterface for local models via Ollama."""

    DEFAULT_OLLAMA_HOST = "http://localhost:11434" # Default Ollama API endpoint
    DEFAULT_MODEL = "llava:latest" # Default to a multimodal model like LLaVA
    # DEFAULT_MODEL = "llama3:latest" # Example text-only model

    def __init__(self):
        # Use a synchronous client for the to_thread approach
        self._sync_client: Optional[ollama.Client] = None
        self._model_name: str = self.DEFAULT_MODEL
        self._system_prompt: Optional[str] = None
        self._last_error: Optional[str] = None
        self._is_configured: bool = False
        self._ollama_host: str = self.DEFAULT_OLLAMA_HOST
        logger.info("OllamaAdapter initialized.")

    def configure(self, api_key: Optional[str], model_name: Optional[str], system_prompt: Optional[str] = None) -> bool:
        """Configures the Ollama client."""
        # API key is ignored for local Ollama, but kept for interface compatibility
        logger.info(f"OllamaAdapter: Configuring. Host: {self._ollama_host}, Model: {model_name}. System Prompt: {'Yes' if system_prompt else 'No'}")
        self._sync_client = None # Use sync client now
        self._is_configured = False
        self._last_error = None

        if not API_LIBRARY_AVAILABLE:
            self._last_error = "Ollama library ('ollama') not installed."
            logger.error(self._last_error)
            return False

        # Use provided model name or default
        self._model_name = model_name if model_name else self.DEFAULT_MODEL
        self._system_prompt = system_prompt.strip() if isinstance(system_prompt, str) else None

        try:
            # Instantiate the SYNCHRONOUS client
            self._sync_client = ollama.Client(host=self._ollama_host)
            # Optional: Add a synchronous check here if the server is reachable
            # try:
            #     self._sync_client.list() # Example sync call to check connection
            #     logger.info(f"  Successfully connected to Ollama at {self._ollama_host}.")
            # except Exception as conn_err:
            #     self._last_error = f"Failed to connect to Ollama at {self._ollama_host}: {conn_err}"
            #     logger.error(self._last_error)
            #     return False

            self._is_configured = True
            logger.info(f"  OllamaAdapter configured successfully for model '{self._model_name}' at {self._ollama_host}.")
            return True

        except Exception as e:
            self._last_error = f"Unexpected error configuring Ollama client: {type(e).__name__} - {e}"
            logger.exception(f"OllamaAdapter Config Error:")
        return False

    def is_configured(self) -> bool:
        """Checks if the adapter is configured."""
        return self._is_configured and self._sync_client is not None

    def get_last_error(self) -> Optional[str]:
        """Returns the last error message."""
        return self._last_error

    async def get_response_stream(self, history: List[ChatMessage]) -> AsyncGenerator[str, None]:
        """
        Gets a streaming response from the Ollama API using asyncio.to_thread
        to isolate the synchronous stream iteration.
        """
        logger.info(f"OllamaAdapter: Generating stream. Model: {self._model_name}, History items: {len(history)}")
        self._last_error = None

        if not self.is_configured():
            self._last_error = "Adapter is not configured."
            logger.error(self._last_error)
            raise RuntimeError(self._last_error)

        # Format history for Ollama, including image data if present
        messages = self._format_history_for_api(history)
        if not messages:
            self._last_error = "Cannot send request: No valid messages in history for the API format."
            logger.error(self._last_error)
            raise ValueError(self._last_error)

        logger.info(f"  Sending {len(messages)} messages to model '{self._model_name}'.")
        if logger.isEnabledFor(logging.DEBUG):
            for i, msg in enumerate(messages):
                 content_preview = str(msg.get('content', ''))[:50] + ('...' if len(str(msg.get('content', ''))) > 50 else '')
                 images_preview = f", Images: {len(msg.get('images', []))}" if 'images' in msg else ""
                 logger.debug(f"    Message {i}: Role={msg['role']}, Content='{content_preview}'{images_preview}")

        try:
            # --- MODIFICATION: Run synchronous stream helper in thread ---
            logger.debug("Calling asyncio.to_thread to run Ollama stream...")
            all_chunks = await asyncio.to_thread(
                _run_ollama_stream_sync,
                self._sync_client, # Pass sync client
                self._model_name,
                messages
            )
            logger.debug(f"asyncio.to_thread completed. Received {len(all_chunks)} chunks.")
            # --- END MODIFICATION ---

            # --- Process the collected chunks ---
            for chunk in all_chunks:
                # Check for errors signaled from the thread
                if chunk.get("error"):
                    self._last_error = chunk["error"]
                    logger.error(f"Error received from Ollama thread: {self._last_error}")
                    raise RuntimeError(self._last_error) # Propagate error

                # Extract the content part from the chunk
                content_part = chunk.get('message', {}).get('content', '')
                if content_part:
                    yield content_part

                # Check for 'done' flag (now just informational as loop ends)
                if chunk.get('done', False):
                     logger.info("Ollama stream finished flag received in collected chunks.")
                     break # Exit loop after processing all collected chunks

        except ollama.ResponseError as e: # Catch errors from sync client if they propagate
             self._last_error = f"Ollama API Response Error: {e.status_code} - {e.error}"
             logger.error(self._last_error)
             raise RuntimeError(self._last_error) from e
        except Exception as e:
            # Catch errors from asyncio.to_thread or async processing
            self._last_error = f"Unexpected error during Ollama stream processing: {type(e).__name__} - {e}"
            logger.exception("OllamaAdapter stream failed:")
            raise RuntimeError(self._last_error) from e

    def _format_history_for_api(self, history: List[ChatMessage]) -> List[Dict[str, Any]]:
        """
        Helper function to format conversation history for the Ollama API,
        including handling multimodal messages (text + images).
        """
        ollama_messages = []
        skipped_count = 0

        # Add system prompt first if it exists
        if self._system_prompt:
             ollama_messages.append({"role": "system", "content": self._system_prompt})

        for msg in history:
            if msg.role == USER_ROLE:
                role = 'user'
            elif msg.role == MODEL_ROLE:
                role = 'assistant' # Ollama uses 'assistant' for model role
            else:
                skipped_count += 1
                continue

            # --- Handle Multimodal Content ---
            content = msg.text # Get text part
            images_base64 = []
            if msg.has_images:
                for img_part in msg.image_parts:
                    # Ollama expects a list of base64 encoded strings
                    img_data = img_part.get("data")
                    if isinstance(img_data, str):
                         # Basic check if it looks like base64
                         try: base64.b64decode(img_data); images_base64.append(img_data)
                         except Exception: logger.warning(f"Skipping invalid base64 data in message part for role {role}.")
                    else: logger.warning(f"Skipping non-string image data part for role {role}.")

            # --- Construct Ollama Message ---
            ollama_msg: Dict[str, Any] = {"role": role}
            # Add content only if it's not empty
            if content:
                ollama_msg["content"] = content
            # Add images only if the list is not empty
            if images_base64:
                ollama_msg["images"] = images_base64

            # Add message only if it has content or images
            if "content" in ollama_msg or "images" in ollama_msg:
                 ollama_messages.append(ollama_msg)
            else:
                 skipped_count += 1
                 logger.warning(f"Skipping message with no valid text or image parts for role {role}.")
            # --- End Multimodal Handling ---

        if skipped_count > 0:
            logger.debug(f"Skipped {skipped_count} non-user/model or empty messages when formatting for Ollama API.")

        return ollama_messages