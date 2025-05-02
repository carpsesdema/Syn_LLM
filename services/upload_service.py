# Llama_Syn/services/upload_service.py
# UPDATED FILE - Removed file reading logic, uses FileHandlerService instead.

import os
import re
import datetime
import logging
import pickle # Keep pickle for now if any part uses it, otherwise remove
# import numpy as np # No longer directly needed here if numpy is used in VectorDBService
from typing import List, Tuple, Optional, Set, Dict, Any
import uuid
from html import escape

# --- Dependency Imports ---
try:
    # Embedder is still needed here
    from sentence_transformers import SentenceTransformer
    DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    EMBEDDINGS_AVAILABLE = True
except Exception as e:
    SentenceTransformer = None; EMBEDDINGS_AVAILABLE = False
    logging.error(f"UploadService: SentenceTransformer library failed ({e}). RAG will fail.")

try:
    import numpy # Needed for embedding array operations
    NUMPY_AVAILABLE = True
except ImportError:
     numpy = None; NUMPY_AVAILABLE = False; logging.error("UploadService: Numpy library not found. RAG DB cannot function.")

# PDF/DOCX Imports REMOVED - Handled by FileHandlerService

# --- Local Imports ---
from utils import constants
from core.models import USER_ROLE, SYSTEM_ROLE, ChatMessage, ERROR_ROLE
# Import ChunkingService
try:
    from .chunking_service import ChunkingService
    CHUNKING_SERVICE_AVAILABLE = True
except ImportError as e:
     ChunkingService = None; CHUNKING_SERVICE_AVAILABLE = False
     logging.error(f"UploadService: Failed to import ChunkingService ({e}). Chunking will fail.")
# Import VectorDBService
try:
    from .vector_db_service import VectorDBService
    VECTOR_DB_SERVICE_AVAILABLE = True
except ImportError as e:
     VectorDBService = None; VECTOR_DB_SERVICE_AVAILABLE = False
     logging.error(f"UploadService: Failed to import VectorDBService ({e}). RAG DB cannot function.")
# --- Import NEW FileHandlerService ---
try:
    from .file_handler_service import FileHandlerService
    FILE_HANDLER_SERVICE_AVAILABLE = True
except ImportError as e:
     FileHandlerService = None; FILE_HANDLER_SERVICE_AVAILABLE = False
     logging.error(f"UploadService: Failed to import FileHandlerService ({e}). File reading will fail.")


logger = logging.getLogger(__name__)

class UploadService:
    """
    Handles processing of uploaded files/directories for RAG.
    Orchestrates reading (via FileHandlerService), chunking (via ChunkingService),
    embedding, and adding/querying the vector store (via VectorDBService).
    """

    def __init__(self):
        logger.info("UploadService initializing...")
        self._embedder: Optional[SentenceTransformer] = None
        self._chunking_service: Optional[ChunkingService] = None
        self._vector_db_service: Optional[VectorDBService] = None
        self._file_handler_service: Optional[FileHandlerService] = None # Added
        self._index_dim = -1 # Store embedder dimension
        self._dependencies_ready = False

        # --- Check Core Dependencies ---
        if not EMBEDDINGS_AVAILABLE:
            logger.critical("UploadService cannot initialize: SentenceTransformer failed to load.")
            return
        if not CHUNKING_SERVICE_AVAILABLE:
            logger.critical("UploadService cannot initialize: ChunkingService failed to load.")
            return
        if not VECTOR_DB_SERVICE_AVAILABLE:
            logger.critical("UploadService cannot initialize: VectorDBService failed to load.")
            return
        if not FILE_HANDLER_SERVICE_AVAILABLE: # Added Check
             logger.critical("UploadService cannot initialize: FileHandlerService failed to load.")
             return
        if not NUMPY_AVAILABLE:
            logger.critical("UploadService cannot initialize: Numpy failed to load.")
            return


        # --- Initialize Components ---
        try:
            # 1. Initialize Embedder & Get Dimension
            logger.info(f"Initializing embedder: {DEFAULT_EMBEDDING_MODEL}")
            self._embedder = SentenceTransformer(DEFAULT_EMBEDDING_MODEL)
            dummy_emb = self._embedder.encode(["test"])
            self._index_dim = dummy_emb.shape[1]
            if self._index_dim <= 0: raise ValueError("Failed to determine embedding dimension.")
            logger.info(f"Detected embedding dimension: {self._index_dim}")

            # 2. Initialize FileHandlerService
            logger.info("Initializing FileHandlerService...")
            self._file_handler_service = FileHandlerService()

            # 3. Initialize ChunkingService
            logger.info("Initializing ChunkingService...")
            rag_chunk_size = getattr(constants, 'RAG_CHUNK_SIZE', 1000)
            rag_chunk_overlap = getattr(constants, 'RAG_CHUNK_OVERLAP', 150)
            logger.info(f"  Using RAG_CHUNK_SIZE={rag_chunk_size}, RAG_CHUNK_OVERLAP={rag_chunk_overlap} from constants.")
            self._chunking_service = ChunkingService(
                chunk_size=rag_chunk_size,
                chunk_overlap=rag_chunk_overlap
            )

            # 4. Initialize VectorDBService (PASS dimension)
            logger.info("Initializing VectorDBService...")
            self._vector_db_service = VectorDBService(index_dimension=self._index_dim)
            # VectorDBService now handles its own loading/initialization inside its __init__

            # Check overall readiness
            self._dependencies_ready = (
                self._embedder is not None and
                self._file_handler_service is not None and # Added check
                self._chunking_service is not None and
                self._vector_db_service is not None and
                self._vector_db_service.is_ready() # Check if DB loaded/initialized correctly
            )

            if self._dependencies_ready:
                logger.info("UploadService initialized successfully with all components.")
            else:
                 logger.error("UploadService initialized BUT one or more components failed (check logs). RAG may not function.")


        except Exception as e:
             logger.exception(f"CRITICAL FAILURE during UploadService component initialization: {e}")
             self._dependencies_ready = False


    def is_vector_db_ready(self) -> bool: # Consider renaming to is_ready()
        """Checks if embedder, file handler, chunker, and vector DB service are ready."""
        return (
            self._dependencies_ready and
            self._file_handler_service is not None and # Added check
            self._vector_db_service is not None and
            self._vector_db_service.is_ready()
        )

    # --- Removed FAISS specific methods ---


    def process_files_for_context(self, file_paths: List[str]) -> Optional[ChatMessage]:
        """ Processes files, chunks, embeds, adds content to VectorDB, returns summary. """
        if not isinstance(file_paths, list):
            logger.error(f"Invalid file_paths argument: Expected list, got {type(file_paths)}")
            return ChatMessage(role=ERROR_ROLE, parts=["[System Error: Invalid input provided.]"])

        num_files = len(file_paths); logger.info(f"UploadService: Processing {num_files} files for RAG DB...")
        processed_files_display = []; binary_files = []; error_files = []; files_processed_for_db = 0; chunks_generated_total = 0; files_added_successfully = 0; db_add_errors_occurred = False; files_with_successful_adds = set()

        if not self.is_vector_db_ready(): # Check uses updated method
            logger.error("RAG DB components (Embedder/Handler/Chunker/VectorDB) not ready."); return ChatMessage(role=ERROR_ROLE, parts=["[Error: RAG components not initialized.]"], metadata={"upload_error": "Components not ready"})

        # --- Batch processing variables ---
        all_embeddings_list = []
        all_metadata_list = []
        files_in_batch = [] # Track files contributing to the current batch

        for i, file_path in enumerate(file_paths):
            # --- File path validation ---
            if not isinstance(file_path, str) or not file_path.strip():
                 error_files.append(f"Invalid Path (Index {i})"); continue
            display_name = os.path.basename(file_path); processed_files_display.append(escape(display_name))

            if not os.path.exists(file_path): error_files.append(escape(display_name) + " (Not Found)"); logger.warning(f"File not found: {file_path}"); continue
            if not os.path.isfile(file_path): error_files.append(escape(display_name) + " (Not a File)"); logger.warning(f"Path is not a file: {file_path}"); continue

            logger.info(f"  Processing [{i+1}/{num_files}]: {display_name}")

            # --- Read File Content using FileHandlerService ---
            try:
                read_result = self._file_handler_service.read_file_content(file_path)
            except Exception as e_read:
                logger.exception(f"  Unexpected error calling FileHandlerService for '{display_name}': {e_read}")
                error_files.append(escape(display_name) + " (Read Service Error)")
                continue
            # --- End Change ---

            if read_result is None or not isinstance(read_result, tuple) or len(read_result) != 3:
                 logger.error(f"  Invalid result from FileHandlerService reading '{display_name}'. Skipping file.")
                 error_files.append(escape(display_name) + " (Internal Read Error)"); continue
            content, file_type, error_msg = read_result

            if file_type == "error": error_files.append(escape(display_name) + f" ({error_msg or 'Read Error'})"); continue
            if file_type == "binary": binary_files.append(escape(display_name)); logger.info(f"  Skipping binary file: {display_name}"); continue

            # --- Process Text Files ---
            if file_type == "text" and content is not None:
                files_processed_for_db += 1
                file_ext = os.path.splitext(file_path)[1].lower()
                chunks = []
                try:
                    # 1. Chunking
                    logger.debug(f"  Calling ChunkingService for '{display_name}' (ext: {file_ext})")
                    chunks = self._chunking_service.chunk_document(content, source_id=file_path, file_ext=file_ext)
                    if not chunks:
                         logger.warning(f"  No chunks generated by ChunkingService for '{display_name}'.")
                         if content.strip(): error_files.append(escape(display_name) + " (No Chunks)")
                         continue # Skip to next file if no chunks

                    logger.info(f"  Generated {len(chunks)} chunks for '{display_name}'")
                    chunks_generated_total += len(chunks)

                    # 2. Embedding (Batching Recommended for Efficiency)
                    chunk_contents = [chunk['content'] for chunk in chunks if isinstance(chunk, dict) and 'content' in chunk]
                    chunk_metadata = [chunk['metadata'] for chunk in chunks if isinstance(chunk, dict) and 'metadata' in chunk]

                    if not chunk_contents or len(chunk_contents) != len(chunk_metadata):
                         logger.error(f"  Content/Metadata mismatch after chunking '{display_name}'. Skipping add for this file.")
                         error_files.append(escape(display_name) + " (Chunk Data Error)")
                         continue

                    logger.debug(f"  Encoding {len(chunk_contents)} chunks for '{display_name}'...")
                    embeddings = self._embedder.encode(chunk_contents, show_progress_bar=False)
                    embeddings_np = numpy.array(embeddings) # No need for float32 conversion here, VectorDB handles it

                    # 3. Accumulate for Batch Add
                    all_embeddings_list.append(embeddings_np)
                    all_metadata_list.extend(chunk_metadata) # Keep metadata flat
                    files_in_batch.append(display_name) # Track which file this batch belongs to (for logging success/failure)


                except Exception as e_proc:
                     logger.exception(f"  Error during chunking or embedding for {display_name}: {e_proc}")
                     error_files.append(escape(display_name) + " (Processing Error)")
                     continue # Skip adding this file on error
            else:
                 logger.warning(f"  Skipping file '{display_name}' due to unexpected type/content state ({file_type}).")


        # --- Add Accumulated Batch to Vector DB ---
        batch_add_success = False
        if all_embeddings_list:
            try:
                logger.info(f"Adding batch of {len(all_metadata_list)} embeddings from {len(files_in_batch)} files to Vector DB...")
                # Concatenate embeddings from all files in the batch
                final_embeddings = numpy.concatenate(all_embeddings_list, axis=0)
                # Call VectorDBService to add the batch
                batch_add_success = self._vector_db_service.add_embeddings(final_embeddings, all_metadata_list)

                if batch_add_success:
                     logger.info(f"Successfully added batch to Vector DB.")
                     # Mark all files contributing to the successful batch
                     files_with_successful_adds.update(files_in_batch)
                else:
                    logger.error("Failed to add batch to Vector DB.")
                    db_add_errors_occurred = True
                    # Add error note for all files in the failed batch
                    for f_name in files_in_batch:
                         if f_name not in error_files: # Avoid duplicates
                              error_files.append(escape(f_name) + " (DB Batch Add Failed)")

            except Exception as e_batch_add:
                 logger.exception(f"Critical error concatenating or adding embedding batch: {e_batch_add}")
                 db_add_errors_occurred = True
                 for f_name in files_in_batch:
                      if f_name not in error_files:
                           error_files.append(escape(f_name) + " (DB Batch Add Error)")
        else:
             logger.info("No embeddings were generated or accumulated to add to the DB.")


        # --- Save Index After Processing All Files ---
        save_success = True
        if batch_add_success: # Save only if a batch was successfully added
            logger.info("Attempting to save index after processing batch...")
            save_success = self._vector_db_service.save() # Call save on VectorDBService
            if not save_success:
                error_files.append("Index/Metadata Save Failed")
                db_add_errors_occurred = True # Mark DB error if save failed


        # --- Generate Summary Message ---
        # (This logic remains the same as before)
        if not processed_files_display:
            return ChatMessage(role=SYSTEM_ROLE, parts=["[Upload Info: No files provided or processed.]"])

        status_notes = []
        num_success = len(files_with_successful_adds) # Count unique files successfully added

        if num_success > 0: status_notes.append(f"{num_success} file(s) added successfully")
        elif files_processed_for_db > 0: status_notes.append("No files added (Check logs for errors/empty files/chunk issues)")

        num_errors = len(error_files)
        # Filter out duplicate error messages before counting/displaying
        unique_error_files = sorted(list(set(error_files)))
        num_unique_errors = len(unique_error_files)
        if num_unique_errors > 0: status_notes.append(f"{num_unique_errors} item(s) with errors (see logs)")
        if binary_files: status_notes.append(f"{len(binary_files)} binary file(s) ignored")

        file_list_str = ", ".join(f"'{f}'" for f in processed_files_display)
        if len(file_list_str) > 150: file_list_str = file_list_str[:147] + "...'"

        role = USER_ROLE if num_success > 0 else SYSTEM_ROLE
        if db_add_errors_occurred: role = ERROR_ROLE

        summary_text_prefix = f"[Upload Processed {num_files} item(s): {file_list_str}"
        if status_notes:
            summary_text = summary_text_prefix + " | Status: " + "; ".join(status_notes) + "]"
        else:
            summary_text = summary_text_prefix + " | Status: No text files processed or errors occurred]"

        upload_timestamp = datetime.datetime.now().isoformat()
        logger.info(f"UploadService: Upload processing finished. Summary: {'; '.join(status_notes)}")
        return ChatMessage(role=role, parts=[summary_text], timestamp=upload_timestamp,
                           metadata={"upload_summary": f"{num_success}/{files_processed_for_db} added",
                                     "errors": num_unique_errors, "binary_skipped": len(binary_files),
                                     "chunks_generated": chunks_generated_total})


    def process_directory_for_context(self, dir_path: str) -> Optional[ChatMessage]:
        """ Scans directory, processes files for RAG DB, returns summary. """
        logger.info(f"UploadService: Processing directory for RAG DB: {dir_path}")
        try:
            if not isinstance(dir_path, str) or not dir_path:
                 return ChatMessage(role=ERROR_ROLE, parts=["[Error: Invalid directory path provided.]"])
            if not os.path.isdir(dir_path):
                 logger.error(f"Path is not a directory: {dir_path}"); return ChatMessage(role=ERROR_ROLE, parts=[f"[Error: Not a directory: '{os.path.basename(dir_path)}']"])

            # Scan directory for valid files
            valid_files, skipped_info = self._scan_directory(dir_path) # Uses internal method

            if not valid_files:
                logger.warning(f"Scan of '{os.path.basename(dir_path)}' found no allowed/readable files.")
                scan_summary_msg = f"[Upload Info: Scan of '{os.path.basename(dir_path)}' found no suitable files."
                if skipped_info: scan_summary_msg += f" Skipped/Errors during scan: {len(skipped_info)} (see logs)."
                scan_summary_msg += "]"; return ChatMessage(role=SYSTEM_ROLE, parts=[scan_summary_msg])

            logger.info(f"Directory scan found {len(valid_files)} files. Processing for RAG DB...")

            # Process the found files using the existing method
            context_message = self.process_files_for_context(valid_files)

            # Add scan summary info to the result message if available
            if context_message and skipped_info:
                 scan_summary_detail = f"{len(skipped_info)} items skipped/error during scan (see logs)."
                 if context_message.metadata: context_message.metadata["scan_summary"] = scan_summary_detail
                 else: context_message.metadata = {"scan_summary": scan_summary_detail}
                 if context_message.parts:
                      original_text = context_message.parts[0]
                      if original_text.endswith(']'): context_message.parts[0] = original_text[:-1] + f" | Scan: {scan_summary_detail}]"
                      else: context_message.parts[0] = original_text + f" [Scan: {scan_summary_detail}]"

            return context_message

        except Exception as e:
            logger.exception(f"CRITICAL ERROR during directory processing '{dir_path}': {e}")
            return ChatMessage(role=ERROR_ROLE, parts=[f"[System: Critical error processing directory '{os.path.basename(dir_path)}'. See logs.]"])

    def query_vector_db(self, query_text: str, n_results: int = constants.RAG_NUM_RESULTS) -> List[Dict[str, Any]]:
        """ Queries the VectorDBService for relevant chunks based on semantic similarity. """
        if not self.is_vector_db_ready():
            logger.error("Cannot query Vector DB: RAG components not ready."); return []
        if not isinstance(query_text, str) or not query_text.strip():
            logger.warning("Attempted query Vector DB with empty or invalid text."); return []
        if not isinstance(n_results, int) or n_results <= 0:
            logger.warning(f"Invalid n_results ({n_results}), using default: {constants.RAG_NUM_RESULTS}")
            n_results = constants.RAG_NUM_RESULTS

        # VectorDBService handles its own size check, but we can check here too
        db_size = self._vector_db_service.get_index_size()
        if db_size == 0:
            logger.warning("Cannot query Vector DB: Index is empty."); return []

        effective_k = min(n_results, db_size)
        if effective_k <= 0:
             logger.warning(f"Effective k for search is zero."); return []

        logger.info(f"Querying Vector DB (size={db_size}) for '{query_text[:50]}...' (k={effective_k})")
        try:
            # 1. Embed the query text
            logger.debug("Encoding query text...")
            query_embedding = self._embedder.encode([query_text])
            query_embedding_np = numpy.array(query_embedding) # Shape (1, dim)

            if query_embedding_np.shape != (1, self._index_dim):
                 logger.error(f"Query embedding dimension mismatch! Expected (1, {self._index_dim}), got {query_embedding_np.shape}. Aborting.")
                 return []

            # 2. Call VectorDBService search
            logger.debug("Calling VectorDBService.search...")
            results = self._vector_db_service.search(query_embedding_np, k=effective_k)

            # 3. Return results (format should already match requirements)
            logger.info(f"Vector DB query returned {len(results)} results.")
            return results

        except Exception as e:
            logger.exception(f"Error querying Vector DB: {e}")
            return []

    # --- File Reading Method REMOVED ---
    # def _read_file_content(...) -> ... :
    #    ... (logic moved to FileHandlerService) ...

    # --- Directory Scanning Method (Remains Here) ---
    def _scan_directory(
        self,
        root_dir: str,
        allowed_extensions: Set[str] = constants.ALLOWED_TEXT_EXTENSIONS,
        ignored_dirs: Set[str] = constants.DEFAULT_IGNORED_DIRS,
    ) -> Tuple[List[str], List[str]]:
        """ Recursively scans a directory. """
        valid_files: List[str] = []; skipped_info: List[str] = []
        logger.info(f"Scanning directory: {root_dir}")
        ignored_dirs_lower = {d.lower() for d in ignored_dirs if isinstance(d, str)}
        allowed_extensions_lower = {e.lower() for e in allowed_extensions if isinstance(e, str)}
        max_depth = getattr(constants, 'MAX_SCAN_DEPTH', 5)
        max_size_mb = getattr(constants, 'RAG_MAX_FILE_SIZE_MB', 50)
        max_size_bytes = max_size_mb * 1024 * 1024

        if not os.path.isdir(root_dir):
            skipped_info.append(f"Error: Root path is not a directory: {root_dir}"); return [], skipped_info

        try:
            for dirpath, dirnames, filenames in os.walk(root_dir, topdown=True, onerror=None):
                try: rel_dirpath = os.path.relpath(dirpath, root_dir)
                except ValueError: logger.warning(f"Cannot get relative path for {dirpath}. Skipping dir content."); continue

                depth = 0 if rel_dirpath == '.' else len(rel_dirpath.split(os.sep))
                if depth >= max_depth:
                     skipped_info.append(f"Max Depth ({max_depth}): '{rel_dirpath}'"); dirnames[:] = []; continue

                original_dir_count = len(dirnames)
                dirnames[:] = [d for d in dirnames if not d.startswith('.') and d.lower() not in ignored_dirs_lower and d not in ignored_dirs]
                skipped_dir_count = original_dir_count - len(dirnames)
                if skipped_dir_count > 0: logger.debug(f"Skipped {skipped_dir_count} subdirs in '{rel_dirpath}'.")

                for filename in filenames:
                    rel_filepath = os.path.join(rel_dirpath, filename) if rel_dirpath != '.' else filename
                    full_path = os.path.join(dirpath, filename)

                    if filename.startswith('.'): skipped_info.append(f"Hidden File: '{rel_filepath}'"); continue
                    _, ext = os.path.splitext(filename)
                    # Check against the globally defined allowed extensions
                    if not ext or ext.lower() not in allowed_extensions_lower:
                         skipped_info.append(f"Wrong Ext ('{ext}'): '{rel_filepath}'"); continue
                    try:
                        if not os.access(full_path, os.R_OK): skipped_info.append(f"Unreadable: '{rel_filepath}'"); continue
                        size = os.path.getsize(full_path)
                        if size == 0: skipped_info.append(f"Empty: '{rel_filepath}'"); continue
                        if size > max_size_bytes: skipped_info.append(f"Too Large ({size/(1024*1024):.1f}MB): '{rel_filepath}'"); continue
                    except OSError as file_err: skipped_info.append(f"OS Error Accessing '{rel_filepath}': {file_err}"); logger.warning(f"OS Error accessing '{full_path}': {file_err}"); continue
                    except Exception as e_file: skipped_info.append(f"Error Accessing '{rel_filepath}': {e_file}"); logger.warning(f"Unexpected error checking '{full_path}': {e_file}"); continue

                    valid_files.append(full_path)
        except OSError as walk_err: error_msg = f"Error scanning directory tree ('{root_dir}'): {walk_err}"; skipped_info.append(error_msg); logger.error(error_msg)
        except Exception as e_walk: error_msg = f"Unexpected error during directory scan: {e_walk}"; skipped_info.append(error_msg); logger.exception("Directory scan failed")

        logger.info(f"Scan complete for '{os.path.basename(root_dir)}'. Found {len(valid_files)} valid files. Skipped/Errors: {len(skipped_info)}")
        return valid_files, skipped_info