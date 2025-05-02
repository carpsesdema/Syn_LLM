# SynaChat/backend/ollama_adapter.py
# UPDATED FILE - Format history to include images for multimodal models

import logging
import asyncio
import base64 # Added for image data check
from typing import List, Optional, AsyncGenerator, Dict, Any

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

class OllamaAdapter(BackendInterface):
    """Implementation of the BackendInterface for local models via Ollama."""

    DEFAULT_OLLAMA_HOST = "http://localhost:11434" # Default Ollama API endpoint
    DEFAULT_MODEL = "llava:latest" # Default to a multimodal model like LLaVA
    # DEFAULT_MODEL = "llama3:latest" # Example text-only model

    def __init__(self):
        self._client: Optional[ollama.AsyncClient] = None
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
        self._client = None
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
            # TODO: Add check if Ollama server is running at the host?
            # This might require a synchronous check or handling connection errors later.
            # For now, assume the server is available.
            self._client = ollama.AsyncClient(host=self._ollama_host)
            self._is_configured = True
            logger.info(f"  OllamaAdapter configured successfully for model '{self._model_name}' at {self._ollama_host}.")
            return True

        except Exception as e:
            self._last_error = f"Unexpected error configuring Ollama client: {type(e).__name__} - {e}"
            logger.exception(f"OllamaAdapter Config Error:")
        return False

    def is_configured(self) -> bool:
        """Checks if the adapter is configured."""
        return self._is_configured and self._client is not None

    def get_last_error(self) -> Optional[str]:
        """Returns the last error message."""
        return self._last_error

    async def get_response_stream(self, history: List[ChatMessage]) -> AsyncGenerator[str, None]:
        """Gets a streaming response from the Ollama API."""
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
            # Use the client's chat method with stream=True
            stream = await self._client.chat(
                model=self._model_name,
                messages=messages,
                stream=True
            )

            async for chunk in stream:
                # Extract the content part from the chunk
                content_part = chunk.get('message', {}).get('content', '')
                if content_part:
                    yield content_part
                # Check for 'done' flag (might indicate error or finish)
                if chunk.get('done', False):
                     if chunk.get('error'):
                          error_msg = chunk['error']
                          self._last_error = f"Ollama API Error: {error_msg}"
                          logger.error(self._last_error)
                          break
                     else:
                          logger.info("Ollama stream finished.")
                          break # Normal finish

        except ollama.ResponseError as e:
             self._last_error = f"Ollama API Response Error: {e.status_code} - {e.error}"
             logger.error(self._last_error)
             raise RuntimeError(self._last_error) from e
        except Exception as e:
            self._last_error = f"Unexpected error during Ollama stream: {type(e).__name__} - {e}"
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
                role = 'assistant'
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