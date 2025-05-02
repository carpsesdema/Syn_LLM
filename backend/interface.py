# SynChat/backend/interface.py
# NEW FILE
from abc import ABC, abstractmethod
from typing import List, Optional, AsyncGenerator, Dict, Any

# Import ChatMessage model
from core.models import ChatMessage

class BackendInterface(ABC):
    """Abstract Base Class defining the interface for AI backend communication."""

    @abstractmethod
    def configure(self, api_key: Optional[str], model_name: str, system_prompt: Optional[str] = None) -> bool:
        """
        Configures the backend adapter with necessary credentials and settings.

        Args:
            api_key: The API key for the backend service.
            model_name: The specific model identifier to use.
            system_prompt: An optional system-level instruction/personality prompt.

        Returns:
            True if configuration was successful, False otherwise.
        """
        pass

    @abstractmethod
    async def get_response_stream(self, history: List[ChatMessage]) -> AsyncGenerator[str, None]:
        """
        Gets a streaming response from the AI backend based on the provided history.

        Args:
            history: A list of ChatMessage objects representing the conversation history.

        Yields:
            str: Chunks of the generated response text as they become available.

        Raises:
            Exception: If an error occurs during the API call or streaming.
        """
        # Ensure the generator is handled correctly in implementations
        # Example: yield '' must be present if the method is empty
        # This is abstract, so implementations must define it.
        # The type hint ensures it's treated as an async generator.
        if False: # This code is never executed, it's just for type hinting correctness
             yield ''
        pass # Implementations must override this


    @abstractmethod
    def get_last_error(self) -> Optional[str]:
        """
        Returns the last error message encountered by the adapter, if any.
        """
        pass

    @abstractmethod
    def is_configured(self) -> bool:
        """
        Checks if the backend adapter is currently configured and ready.
        """
        pass

    # Optional: Add methods for capabilities like function calling, image input, etc. later
    # @abstractmethod
    # def supports_function_calling(self) -> bool:
    #     pass