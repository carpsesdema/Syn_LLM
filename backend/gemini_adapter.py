# SynChat/backend/gemini_adapter.py
# UPDATED FILE (Handle StopIteration via helper func in asyncio.to_thread)
import logging
import asyncio
from typing import List, Optional, AsyncGenerator, Dict, Any

# Import interface and model
from .interface import BackendInterface
from core.models import ChatMessage, MODEL_ROLE, USER_ROLE # Use roles from core.models

# Attempt import for type hinting and error checking
try:
    import google.generativeai as genai
    from google.generativeai.types import HarmBlockThreshold, HarmCategory
    from google.api_core.exceptions import GoogleAPIError, ClientError, PermissionDenied, ResourceExhausted, InvalidArgument
    API_LIBRARY_AVAILABLE = True
except ImportError:
    genai = None
    HarmCategory = type("HarmCategory", (object,), {})
    HarmBlockThreshold = type("HarmBlockThreshold", (object,), {})
    GoogleAPIError = type("GoogleAPIError", (Exception,), {})
    ClientError = type("ClientError", (GoogleAPIError,), {})
    PermissionDenied = type("PermissionDenied", (ClientError,), {})
    ResourceExhausted = type("ResourceExhausted", (ClientError,), {})
    InvalidArgument = type("InvalidArgument", (ClientError,), {})
    API_LIBRARY_AVAILABLE = False
    logging.warning("GeminiAdapter: google-generativeai library not found.")

logger = logging.getLogger(__name__)

# --- Helper function to handle StopIteration within the thread ---
_SENTINEL = object() # Use a unique object as sentinel

def _next_or_sentinel(iterator):
    """Calls next() on the iterator, returning _SENTINEL on StopIteration."""
    try:
        return next(iterator)
    except StopIteration:
        return _SENTINEL
    except Exception as e:
        # Log other exceptions occurring within next() if necessary
        logger.error(f"Error during 'next' call in thread: {e}")
        raise # Re-raise other exceptions

class GeminiAdapter(BackendInterface):
    """Implementation of the BackendInterface for Google Gemini models."""

    def __init__(self):
        self._model: Optional[genai.GenerativeModel] = None
        self._model_name: Optional[str] = None
        self._system_prompt: Optional[str] = None
        self._last_error: Optional[str] = None
        self._is_configured: bool = False
        logger.info("GeminiAdapter initialized.")

    def configure(self, api_key: Optional[str], model_name: str, system_prompt: Optional[str] = None) -> bool:
        """Configures the Gemini API."""
        logger.info(f"GeminiAdapter: Configuring. Model: {model_name}. System Prompt: {'Yes' if system_prompt else 'No'}")
        self._model = None
        self._is_configured = False
        self._last_error = None

        if not API_LIBRARY_AVAILABLE:
            self._last_error = "Gemini API library (google-generativeai) not installed."
            logger.error(self._last_error)
            return False

        if not api_key or not api_key.strip():
            self._last_error = "API Key is missing or empty."
            logger.error(self._last_error)
            return False

        if not model_name:
            self._last_error = "Model name is required for configuration."
            logger.error(self._last_error)
            return False

        try:
            logger.info(f"  Configuring genai with API Key starting: {api_key[:5]}...")
            genai.configure(api_key=api_key)

            safety_settings = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }

            effective_prompt = system_prompt.strip() if isinstance(system_prompt, str) and system_prompt.strip() else None

            logger.info(f"  Instantiating GenerativeModel: '{model_name}'. System Instruction: {'Present' if effective_prompt else 'None'}")
            self._model = genai.GenerativeModel(
                model_name=model_name,
                safety_settings=safety_settings,
                system_instruction=effective_prompt
            )
            self._model_name = model_name
            self._system_prompt = effective_prompt
            self._is_configured = True
            logger.info(f"  GeminiAdapter configured successfully for model '{model_name}'.")
            return True

        except ValueError as ve:
             self._last_error = f"Configuration Error: {ve}"
             logger.error(f"GeminiAdapter Config Error: {ve}")
        except Exception as e:
            self._last_error = f"Unexpected error configuring Gemini model '{model_name}': {type(e).__name__} - {e}"
            logger.exception(f"GeminiAdapter Config Error:")
        return False

    def is_configured(self) -> bool:
        """Checks if the adapter is configured."""
        return self._is_configured and self._model is not None

    def get_last_error(self) -> Optional[str]:
        """Returns the last error message."""
        return self._last_error

    async def get_response_stream(self, history: List[ChatMessage]) -> AsyncGenerator[str, None]:
        """Gets a streaming response from the Gemini API."""
        logger.info(f"GeminiAdapter: Generating stream. History items: {len(history)}")
        self._last_error = None

        if not self.is_configured():
            self._last_error = "Adapter is not configured."
            logger.error(self._last_error)
            raise RuntimeError(self._last_error)

        gemini_history = self._format_history_for_api(history)
        if not gemini_history:
             self._last_error = "Cannot send request: No valid messages in history for the API format."
             logger.error(self._last_error)
             raise ValueError(self._last_error)

        logger.info(f"  Sending {len(gemini_history)} entries to model.")

        try:
            if not hasattr(self._model, 'generate_content'):
                 self._last_error = "Internal Error: Configured model object lacks 'generate_content'."
                 logger.error(self._last_error); raise AttributeError(self._last_error)

            logger.debug("  Making initial blocking API call in thread...")
            response_object = await asyncio.to_thread(
                self._model.generate_content,
                gemini_history,
                stream=True,
            )
            logger.debug("  Initial API call returned response object.")

            sync_iterator = iter(response_object)

            async def yield_chunks() -> AsyncGenerator[str, None]:
                logger.debug("    Starting async chunk yielding loop...")
                chunk_count = 0
                try:
                    while True:
                        # --- FIX: Call helper function via asyncio.to_thread ---
                        chunk_or_sentinel = await asyncio.to_thread(_next_or_sentinel, sync_iterator)
                        if chunk_or_sentinel is _SENTINEL:
                            logger.info("    Stream finished normally (Sentinel received from thread).")
                            break # Exit loop cleanly
                        # --- END FIX ---

                        # We have a valid chunk
                        chunk = chunk_or_sentinel
                        chunk_count += 1
                        text_content = None
                        error_in_chunk = None

                        # Check for prompt feedback/blocks
                        prompt_feedback = getattr(chunk, 'prompt_feedback', None)
                        if prompt_feedback:
                             block_reason = getattr(prompt_feedback, 'block_reason', None)
                             if block_reason:
                                 error_in_chunk = f"Content blocked by API safety filters: {block_reason}."
                                 logger.warning(f"API Blocked in stream: {error_in_chunk}")
                                 self._last_error = error_in_chunk
                                 break

                        # Extract text content
                        if hasattr(chunk, 'parts') and chunk.parts and hasattr(chunk.parts[0], 'text'):
                            text_content = chunk.parts[0].text
                        elif hasattr(chunk, 'text'):
                            text_content = chunk.text

                        if text_content:
                            yield text_content

                except Exception as e_yield:
                     # Catch errors *during* processing/yielding
                     self._last_error = f"Error during stream processing/yielding chunk: {type(e_yield).__name__} - {e_yield}"
                     logger.exception("    Error during async yield loop:")
                     raise RuntimeError(self._last_error) from e_yield
                finally:
                     logger.info(f"    Async chunk yielding loop finished after {chunk_count} chunks.")

            return yield_chunks()

        except InvalidArgument as e:
            self._last_error = f"API Error (Invalid Argument): {e}"; logger.error(self._last_error); raise
        except PermissionDenied as e:
            self._last_error = f"API Error (Permission/Safety Block): {e}"; logger.error(self._last_error); raise
        except ResourceExhausted as e:
            self._last_error = f"API Error (Resource Exhausted/Quota): {e}"; logger.error(self._last_error); raise
        except ClientError as e:
             self._last_error = f"API Client Error: {type(e).__name__} - {e}"; logger.error(self._last_error); raise
        except GoogleAPIError as e:
             self._last_error = f"Google API Error: {type(e).__name__} - {e}"; logger.error(self._last_error); raise
        except Exception as e:
            self._last_error = f"Unexpected error preparing stream: {type(e).__name__} - {e}"
            logger.exception("GeminiAdapter stream preparation failed:")
            raise RuntimeError(self._last_error) from e


    def _format_history_for_api(self, history: List[ChatMessage]) -> List[Dict[str, Any]]:
        """Helper function to format conversation history for the Gemini API."""
        gemini_history = []
        skipped_count = 0
        for msg in history:
            if msg.role == USER_ROLE:
                role = 'user'
            elif msg.role == MODEL_ROLE:
                role = 'model'
            else:
                skipped_count += 1
                continue

            parts_list = [str(p).strip() for p in msg.parts if isinstance(p, (str, int, float)) and str(p).strip()]
            if not parts_list:
                 skipped_count += 1
                 continue

            gemini_history.append({"role": role, "parts": parts_list})

        return gemini_history