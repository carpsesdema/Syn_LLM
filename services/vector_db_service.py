# Llama_Syn/services/vector_db_service.py
# UPDATED FILE - Added methods to retrieve metadata for viewing

import os
import logging
import pickle
# --- ADDED ---
import copy
# -----------
from typing import List, Dict, Any, Optional, Tuple

# --- Dependency Imports ---
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    faiss = None; FAISS_AVAILABLE = False
    logging.error("VectorDBService: FAISS library not found. RAG DB cannot function.")

try:
    import numpy
    NUMPY_AVAILABLE = True
except ImportError:
    numpy = None; NUMPY_AVAILABLE = False
    logging.error("VectorDBService: Numpy library not found. RAG DB cannot function.")

# --- Local Imports ---
from utils import constants

logger = logging.getLogger(__name__)

class VectorDBService:
    """
    Manages the FAISS vector index and associated metadata storage.
    Handles loading, saving, adding vectors, and searching.
    Does NOT handle embedding creation.
    """

    def __init__(self, index_dimension: int):
        """
        Initializes the VectorDBService.

        Args:
            index_dimension: The dimensionality of the vectors to be stored (must match embedder output).
        """
        logger.info(f"VectorDBService initializing with index dimension: {index_dimension}...")
        if not FAISS_AVAILABLE or not NUMPY_AVAILABLE:
            logger.critical("VectorDBService cannot initialize: Missing FAISS or Numpy.")
            self._faiss_index: Optional[faiss.Index] = None
            self._metadata_store: List[Dict[str, Any]] = []
            self._index_dim: int = -1
            self._storage_ready: bool = False
            return

        if not isinstance(index_dimension, int) or index_dimension <= 0:
             raise ValueError(f"Invalid index_dimension provided: {index_dimension}. Must be a positive integer.")

        self._faiss_index = None
        self._metadata_store = []
        self._index_dim = index_dimension
        self._storage_ready = False # Set to True after successful load/init

        # --- Paths ---
        try:
            # Ensure base user data directory exists
            os.makedirs(constants.USER_DATA_DIR, exist_ok=True)
        except OSError as e:
            logger.critical(f"Failed to create USER_DATA_DIR '{constants.USER_DATA_DIR}': {e}")
            # Cannot proceed without storage path
            return

        self._index_path = os.path.join(constants.USER_DATA_DIR, "code_index.faiss")
        self._metadata_path = os.path.join(constants.USER_DATA_DIR, "code_metadata.pkl")
        logger.info(f"  Index Path: {self._index_path}")
        logger.info(f"  Metadata Path: {self._metadata_path}")

        # Load or initialize the database immediately
        self.load_or_initialize()

    def load_or_initialize(self):
        """Loads existing FAISS index and metadata, or initializes new ones."""
        logger.info("Attempting to load or initialize FAISS DB...")
        self._storage_ready = False # Assume not ready until success

        # Check if files exist
        index_exists = os.path.exists(self._index_path)
        metadata_exists = os.path.exists(self._metadata_path)

        if index_exists and metadata_exists:
            try:
                logger.info(f"Loading FAISS index from: {self._index_path}")
                loaded_index = faiss.read_index(self._index_path)

                logger.info(f"Loading metadata from: {self._metadata_path}")
                with open(self._metadata_path, "rb") as f:
                    loaded_metadata = pickle.load(f)

                # --- Validation ---
                index_valid = True
                if not hasattr(loaded_index, 'd') or not isinstance(loaded_index.d, int):
                    logger.error("Loaded FAISS index invalid (missing or invalid dimension 'd')."); index_valid = False
                elif loaded_index.d != self._index_dim:
                    logger.error(f"FATAL: FAISS dimension mismatch (Index={loaded_index.d}, Expected={self._index_dim}). Delete index files & restart."); index_valid = False
                if not hasattr(loaded_index, 'ntotal') or not isinstance(loaded_index.ntotal, int):
                     logger.error("Loaded FAISS index invalid (missing or invalid 'ntotal')."); index_valid = False
                if index_valid and not isinstance(loaded_metadata, list):
                     logger.error(f"Loaded metadata invalid (not a list, type: {type(loaded_metadata)})."); index_valid = False
                if index_valid and loaded_index.ntotal != len(loaded_metadata):
                    logger.warning(f"Index/Metadata size mismatch (Index={loaded_index.ntotal}, Metadata={len(loaded_metadata)}).")
                    # Decide if this should prevent loading or just warn. Warning for now.
                    # index_valid = False # Uncomment to force re-init on mismatch

                if index_valid:
                    self._faiss_index = loaded_index
                    self._metadata_store = loaded_metadata
                    logger.info(f"FAISS index (d={self._faiss_index.d}, ntotal={self._faiss_index.ntotal}) and metadata ({len(self._metadata_store)}) loaded successfully.")
                    self._storage_ready = True
                    return # Successfully loaded

                else:
                    logger.error("FAISS index/metadata loaded but failed validation. Re-initializing.")
                    self._faiss_index = None # Clear potentially bad index
                    self._metadata_store = []

            except EOFError:
                logger.error(f"EOFError loading metadata from {self._metadata_path}. File corrupt/empty. Re-initializing.")
            except pickle.UnpicklingError as e_pickle:
                logger.error(f"UnpicklingError loading metadata from {self._metadata_path}: {e_pickle}. Re-initializing.")
            except Exception as e:
                logger.exception(f"Unexpected error loading FAISS index/metadata. Re-initializing. Error: {e}")
                self._faiss_index = None # Ensure clean state on error
                self._metadata_store = []

        # --- Initialize New Index ---
        logger.info("Initializing new FAISS index and metadata store.")
        if self._index_dim <= 0:
            logger.error("Cannot initialize FAISS: Invalid index dimension configuration."); return
        try:
            # Using IndexFlatL2 - simple L2 distance search.
            self._faiss_index = faiss.IndexFlatL2(self._index_dim)
            self._metadata_store = []
            self._storage_ready = True
            logger.info(f"New FAISS IndexFlatL2 (dim={self._index_dim}) initialized.")
        except Exception as e:
            logger.exception(f"Failed to initialize new FAISS index: {e}")
            self._faiss_index = None
            self._metadata_store = []
            self._storage_ready = False

    def save(self) -> bool:
         """Saves the current FAISS index and metadata store to disk."""
         if not self.is_ready():
             logger.error("Cannot save: Vector DB not ready."); return False

         # Check consistency before saving
         if not self._faiss_index or not hasattr(self._faiss_index, 'ntotal'):
              logger.error("Cannot save: FAISS index is invalid or None.")
              return False
         if not isinstance(self._metadata_store, list):
              logger.error("Cannot save: Metadata store is invalid (not a list).")
              return False
         if self._faiss_index.ntotal != len(self._metadata_store):
              logger.error(f"CRITICAL SAVE ABORTED: Index size ({self._faiss_index.ntotal}) != Metadata size ({len(self._metadata_store)}).")
              return False

         if self._faiss_index.ntotal == 0:
             logger.info("Skipping save: FAISS index is empty.")
             # Optionally clean up files if index is empty but files exist?
             # if os.path.exists(self._index_path): os.remove(self._index_path)
             # if os.path.exists(self._metadata_path): os.remove(self._metadata_path)
             return True

         try:
              logger.info(f"Saving FAISS index (ntotal={self._faiss_index.ntotal}) to: {self._index_path}")
              faiss.write_index(self._faiss_index, self._index_path)
              logger.info(f"Saving metadata ({len(self._metadata_store)}) to: {self._metadata_path}")
              with open(self._metadata_path, "wb") as f:
                  pickle.dump(self._metadata_store, f)
              logger.info("FAISS index and metadata saved successfully.")
              return True
         except Exception as e:
             logger.exception(f"Error saving FAISS index or metadata: {e}")
             return False

    def add_embeddings(self, embeddings: numpy.ndarray, metadata_list: List[Dict]) -> bool:
        """
        Adds pre-computed embeddings and their corresponding metadata to the store.

        Args:
            embeddings: A numpy array of embeddings (shape: [n, index_dimension]).
            metadata_list: A list of metadata dictionaries, one for each embedding.
                           Must contain 'content' key.

        Returns:
            True if adding was successful, False otherwise.
        """
        if not self.is_ready():
             logger.error("Cannot add embeddings: Vector DB not ready."); return False
        if not isinstance(embeddings, numpy.ndarray) or embeddings.ndim != 2:
             logger.error(f"Invalid embeddings format: Expected 2D numpy array, got {type(embeddings)} with ndim={getattr(embeddings, 'ndim', 'N/A')}."); return False
        if not isinstance(metadata_list, list) or len(embeddings) != len(metadata_list):
             logger.error(f"Embeddings count ({len(embeddings)}) does not match metadata count ({len(metadata_list)})."); return False
        if embeddings.shape[1] != self._index_dim:
             logger.error(f"Embedding dimension mismatch! Expected {self._index_dim}, got {embeddings.shape[1]}."); return False
        if len(embeddings) == 0:
             logger.info("No embeddings provided to add."); return True # Nothing to do

        # --- Add to FAISS and Metadata Store ---
        try:
             logger.info(f"Adding {embeddings.shape[0]} vectors to FAISS index (current size: {self._faiss_index.ntotal})...")
             # Ensure embeddings are float32 for FAISS
             embeddings_float32 = embeddings.astype('float32')
             self._faiss_index.add(embeddings_float32)
             self._metadata_store.extend(metadata_list)

             # --- Post-Add Sanity Check ---
             if self._faiss_index.ntotal != len(self._metadata_store):
                  logger.error("CRITICAL INCONSISTENCY after adding embeddings!")
                  logger.error(f"  FAISS index size: {self._faiss_index.ntotal}")
                  logger.error(f"  Metadata store size: {len(self._metadata_store)}")
                  # Attempt rollback? Difficult with IndexFlatL2. Log and report failure.
                  # Consider more robust index types (like IVFFlat) or DBs (Chroma) if transactional adds are needed.
                  return False
             # --- End Sanity Check ---

             logger.info(f"Successfully added {embeddings.shape[0]} embeddings. New Index Total: {self._faiss_index.ntotal}")
             return True

        except Exception as e:
             logger.exception(f"FAILED TO ADD embeddings batch: {e}")
             # Rollback is hard here, the index might be partially updated.
             return False

    def search(self, query_embedding: numpy.ndarray, k: int) -> List[Dict[str, Any]]:
        """
        Searches the FAISS index using a pre-computed query embedding.

        Args:
            query_embedding: A numpy array for the query (shape: [1, index_dimension]).
            k: The number of nearest neighbors to retrieve.

        Returns:
            A list of dictionaries, each containing the metadata of a relevant chunk
            and its distance. Returns empty list on error or no results.
        """
        if not self.is_ready():
            logger.error("Cannot search: Vector DB not ready."); return []
        if self.get_index_size() == 0:
            logger.warning("Cannot search: Index is empty."); return []
        if not isinstance(query_embedding, numpy.ndarray) or query_embedding.ndim != 2 or query_embedding.shape[0] != 1:
             logger.error(f"Invalid query embedding format: Expected shape (1, {self._index_dim}), got {query_embedding.shape}."); return []
        if query_embedding.shape[1] != self._index_dim:
             logger.error(f"Query embedding dimension mismatch! Expected {self._index_dim}, got {query_embedding.shape[1]}."); return []
        if not isinstance(k, int) or k <= 0:
             logger.warning(f"Invalid k value ({k}) for search, using default 1."); k = 1

        effective_k = min(k, self.get_index_size())
        if effective_k <= 0:
             logger.warning("Effective k for search is zero."); return []

        logger.info(f"Searching FAISS index (size={self.get_index_size()}) with k={effective_k}")
        try:
            # Ensure query embedding is float32
            query_embedding_float32 = query_embedding.astype('float32')

            # FAISS search returns distances and indices
            distances, indices = self._faiss_index.search(query_embedding_float32, k=effective_k)
            # Distances are L2 (Euclidean) squared by default with IndexFlatL2. Lower is better.
            # Indices is a 2D array (shape [1, effective_k] for single query)

            processed_results = []
            unique_indices = set() # Track indices to avoid duplicates

            if indices.size > 0 and len(indices[0]) > 0:
                logger.debug(f"FAISS search raw results - Distances: {distances[0]}, Indices: {indices[0]}")
                for i, idx in enumerate(indices[0]):
                    idx = int(idx) # Ensure index is integer
                    if idx == -1 or idx in unique_indices:
                        logger.debug(f"Skipping index {idx} (invalid or duplicate)."); continue
                    if 0 <= idx < len(self._metadata_store):
                        try:
                            # Retrieve metadata using the valid index
                            metadata = self._metadata_store[idx]
                            # Get content from metadata (where it MUST be stored)
                            content = metadata.get("content", "[Content Missing in Metadata! Check ChunkingService]")
                            distance = distances[0][i]
                            unique_indices.add(idx)

                            # Structure the result (matches previous UploadService format)
                            result_item = {
                                "content": content, # Content of the retrieved chunk
                                "metadata": metadata, # Full metadata associated with the chunk
                                "distance": float(distance) # L2 distance (squared for IndexFlatL2)
                            }
                            processed_results.append(result_item)
                            logger.debug(f"  Result {len(processed_results)}: Index={idx}, Dist={distance:.4f}, Source='{metadata.get('filename', 'N/A')}'")
                        except Exception as e_meta:
                             logger.error(f"Error processing metadata for index {idx}: {e_meta}")
                             continue # Skip this result if metadata processing fails
                    else:
                        # This indicates a serious index/metadata mismatch
                        logger.error(f"FAISS search returned invalid index: {idx} (Metadata store size: {len(self._metadata_store)})")

                logger.info(f"FAISS Search yielded {len(processed_results)} valid, unique results.")
            else:
                logger.info("FAISS Query returned no valid indices.")

            return processed_results

        except Exception as e:
            logger.exception(f"Error during FAISS search: {e}")
            return []

    def is_ready(self) -> bool:
        """Checks if the FAISS index is loaded/initialized and ready."""
        return self._storage_ready and self._faiss_index is not None

    def get_index_size(self) -> int:
        """Returns the number of vectors currently in the FAISS index."""
        if self.is_ready() and hasattr(self._faiss_index, 'ntotal'):
            return self._faiss_index.ntotal
        return 0

    # --- ADDED ---
    def get_all_metadata(self) -> List[Dict[str, Any]]:
        """
        Returns a copy of the entire metadata store.

        Returns:
            A list of dictionaries, each representing the metadata of a chunk.
            Returns an empty list if not ready or metadata is empty.
        """
        if not self.is_ready():
            logger.error("Cannot get metadata: Vector DB not ready.")
            return []
        logger.info(f"Retrieving copy of metadata store (size: {len(self._metadata_store)})")
        # Return a deep copy to prevent external modification of the internal store
        return copy.deepcopy(self._metadata_store)
    # -----------