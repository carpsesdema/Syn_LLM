# Syn_LLM/services/chunking_service.py
# UPDATED FILE - Conditionally use PythonCodeTextSplitter for .py files

import os
import logging
from typing import List, Dict, Any

# --- Add LangChain imports ---
# Ensure Language is imported if needed by specific splitters, though maybe not directly used here.
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language, PythonCodeTextSplitter

# --- Keep existing imports ---
from utils import constants # For fallback/logging if needed, not direct config reading

logger = logging.getLogger(__name__)

class ChunkingService:
    """
    Handles chunking of documents using LangChain splitters.
    Configuration (chunk size, overlap) is passed during initialization.
    Uses PythonCodeTextSplitter for .py files and RecursiveCharacterTextSplitter
    as a fallback for other types.
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        """
        Initializes the ChunkingService with specified chunk size and overlap.

        Args:
            chunk_size: The target size for each chunk (e.g., in characters).
            chunk_overlap: The number of characters to overlap between chunks.
        """
        logger.info(f"ChunkingService initialized with chunk_size={chunk_size}, chunk_overlap={chunk_overlap}")
        if not isinstance(chunk_size, int) or chunk_size <= 0:
            fallback_size = 1000
            logger.warning(f"Invalid chunk_size ({chunk_size}), using fallback: {fallback_size}")
            chunk_size = fallback_size
        if not isinstance(chunk_overlap, int) or chunk_overlap < 0 or chunk_overlap >= chunk_size:
             fallback_overlap = int(chunk_size * 0.15) # 15% overlap as fallback
             logger.warning(f"Invalid chunk_overlap ({chunk_overlap}) for chunk_size {chunk_size}, using fallback: {fallback_overlap}")
             chunk_overlap = fallback_overlap

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # --- Instantiate the LangChain splitters ---
        # 1. Default/Fallback Recursive Splitter
        self.recursive_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
        )
        logger.info(f"Using LangChain RecursiveCharacterTextSplitter (size={self.chunk_size}, overlap={self.chunk_overlap}) as default.")

        # 2. Python Code Splitter
        try:
            self.python_splitter = PythonCodeTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap
                # PythonCodeTextSplitter automatically uses appropriate Python separators
            )
            logger.info(f"Initialized LangChain PythonCodeTextSplitter (size={self.chunk_size}, overlap={self.chunk_overlap}).")
        except Exception as e:
            logger.error(f"Failed to initialize PythonCodeTextSplitter: {e}. Falling back to recursive for Python.", exc_info=True)
            self.python_splitter = None # Mark as unavailable if init fails


    def chunk_document(self, content: str, source_id: str, file_ext: str) -> List[Dict[str, Any]]:
        """
        Chunks a document using the appropriate LangChain splitter based on file extension.

        Args:
            content: The text content of the document.
            source_id: The original identifier (e.g., file path) of the document.
            file_ext: The lowercased file extension (e.g., '.py', '.txt').

        Returns:
            A list of dictionaries, where each dictionary represents a chunk
            and contains 'content' and 'metadata'. Returns empty list on error.
        """
        filename_base = os.path.basename(source_id) if source_id else "unknown_source"
        logger.debug(f"Chunking document: {filename_base} (ext: {file_ext})")
        if not isinstance(content, str) or not content.strip():
            logger.warning(f"Skipping chunking for empty content: {filename_base}")
            return []

        # --- Choose the appropriate splitter ---
        splitter_to_use = None
        if file_ext == '.py' and self.python_splitter:
            logger.debug(f"Using PythonCodeTextSplitter for '{filename_base}'")
            splitter_to_use = self.python_splitter
        else:
            if file_ext == '.py': # Log fallback specifically for Python if splitter failed init
                 logger.warning(f"PythonCodeTextSplitter not available, falling back to RecursiveCharacterTextSplitter for '{filename_base}'.")
            logger.debug(f"Using default RecursiveCharacterTextSplitter for '{filename_base}'")
            splitter_to_use = self.recursive_splitter
        # ------------------------------------

        if splitter_to_use is None: # Should not happen if recursive_splitter is always initialized
             logger.error(f"No valid text splitter available for '{filename_base}'. Cannot chunk.")
             return []

        try:
            logger.debug(f"Splitting text for '{filename_base}' (length: {len(content)}) using {type(splitter_to_use).__name__}")
            split_texts = splitter_to_use.split_text(content)
            logger.debug(f"Split into {len(split_texts)} chunks for '{filename_base}'")

            # --- Format output (remains the same) ---
            chunks = []
            current_pos = 0 # Track position in original content for approximate start_index
            for i, text_chunk in enumerate(split_texts):
                if not text_chunk.strip(): # Skip empty chunks if splitter produces them
                     logger.debug(f"Skipping empty chunk {i} for '{filename_base}'")
                     continue

                # Find approximate start index (may not be perfect with overlap)
                try:
                     chunk_start_in_original = content.find(text_chunk, current_pos)
                     if chunk_start_in_original == -1:
                         # If exact chunk not found from current_pos, try from start (less accurate)
                         chunk_start_in_original = content.find(text_chunk)
                         if chunk_start_in_original == -1: chunk_start_in_original = current_pos # Fallback if find fails
                except Exception:
                     chunk_start_in_original = current_pos # Fallback on error

                metadata = {
                    "source": str(source_id),
                    "filename": filename_base,
                    "chunk_index": i, # Index of the chunk within this document
                    "start_index": chunk_start_in_original, # Approximate start char index
                    "content": text_chunk # IMPORTANT: Store original chunk content in metadata for DB lookup
                }
                chunks.append({"content": text_chunk, "metadata": metadata})

                # Update position for next search (move past the start of this chunk)
                current_pos = chunk_start_in_original + 1

            logger.info(f"{type(splitter_to_use).__name__} created {len(chunks)} non-empty chunks for {filename_base}")
            return chunks

        except Exception as e:
            logger.exception(f"Error using {type(splitter_to_use).__name__} for {filename_base}: {e}")
            return [] # Return empty list on error

    # --- Old methods are removed ---
    # def _simple_chunk_text(...): ...
    # def _extract_node_text(...): ...
    # def _chunk_python_code_by_structure(...): ...