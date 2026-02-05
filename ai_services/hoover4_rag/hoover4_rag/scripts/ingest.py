#!/usr/bin/env python3
"""
RAG Ingest Script

This script processes text content from ClickHouse using the TextContentIterator,
generates embeddings, and stores everything in Milvus for RAG (Retrieval-Augmented Generation) applications.
Entity extraction is now handled by the vectorstore class for optimal performance.

Features:
- Processes text content in configurable database batches for memory efficiency
- Generates embeddings using Hoover4 embeddings client
- Stores documents in Milvus using configurable batch processing to avoid overwhelming the database
- Uses LangChain RecursiveCharacterTextSplitter for text chunking
- Supports resume functionality for large datasets
- Configurable database batch size (rows fetched per batch) and Milvus batch size (documents inserted per batch)
- Entity extraction handled by vectorstore for optimal throughput
"""

import os
import sys
import time
import logging
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from tqdm import tqdm

# Add the parent directory to the path to import our modules
sys.path.append(str(Path(__file__).parent.parent.parent))

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from hoover4_rag.text_content_iterator import TextContentIterator, TextContentEntry
from hoover4_ai_clients.milvus_client import Hoover4MilvusVectorStore
from hoover4_ai_clients.embeddings_client import Hoover4EmbeddingsClient

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ingest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class IngestConfig:
    """Configuration for the ingest process."""
    # Text content iterator settings
    database_batch_size: int = 200  # Number of rows fetched from database per batch
    collection_dataset: Optional[str] = None
    extracted_by_filter: Optional[str] = None
    min_text_length: int = 50
    resume_file: str = "text_content_progress.json"
    
    # Milvus insertion settings
    milvus_batch_size: int = 50  # Number of documents to insert to Milvus per batch
    
    # Text splitting settings
    chunk_size: int = 2048
    chunk_overlap: int = 128
    separators: List[str] = None
    
    # Milvus settings
    milvus_host: str = "http://10.69.69.5"
    milvus_port: int = 19530
    collection_name: str = "rag_chunks"
    embedding_dim: int = 1024
    
    # Client settings
    embeddings_base_url: str = "http://localhost:8000/v1"
    
    # Processing settings
    max_retries: int = 3
    retry_delay: float = 1.0
    progress_interval: int = 100  # Log progress every N documents
    show_progress_bar: bool = True  # Show tqdm progress bar
    
    def __post_init__(self):
        if self.separators is None:
            self.separators = ["\n\n", "\n", " ", ""]


class RAGIngestProcessor:
    """
    Main processor for RAG ingestion pipeline.
    
    This class orchestrates the entire ingestion process:
    1. Iterates through text content from ClickHouse in configurable database batches
    2. Splits text into chunks using RecursiveCharacterTextSplitter
    3. Generates embeddings using embeddings client
    4. Stores everything in Milvus vector store in configurable Milvus batches (entity extraction handled by vectorstore)
    
    The processor supports two levels of batching:
    - Database batch size: Controls how many rows are fetched from ClickHouse per batch
    - Milvus batch size: Controls how many documents are inserted to Milvus per batch
    """
    
    def __init__(self, config: IngestConfig):
        """Initialize the RAG ingest processor."""
        self.config = config
        
        # Initialize clients
        self.embeddings_client = Hoover4EmbeddingsClient(
            base_url=config.embeddings_base_url,
            task_description="",
            timeout=30,
            max_retries=config.max_retries
        )
        
        self.milvus_client = Hoover4MilvusVectorStore(
            collection_name=config.collection_name,
            host=config.milvus_host,
            port=config.milvus_port,
            embedding_dim=config.embedding_dim,
            embedding=self.embeddings_client,
            search_mode="hybrid"
        )
        
        # Initialize text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            separators=config.separators,
            length_function=len,
            is_separator_regex=False
        )
        
        # Statistics tracking
        self.stats = {
            'total_processed': 0,
            'total_chunks': 0,
            'total_documents_stored': 0,
            'errors': 0,
            'start_time': None
        }
    
    def health_check(self) -> bool:
        """Check if all required services are healthy."""
        logger.info("Performing health checks...")
        
        # Check embeddings client
        try:
            if not self.embeddings_client.health_check():
                logger.error("Embeddings client health check failed")
                return False
            logger.info("Embeddings client is healthy")
        except Exception as e:
            logger.error(f"Embeddings client health check failed: {e}")
            return False
        
        # Check Milvus connection
        try:
            if not self.milvus_client.connect():
                logger.error("Milvus connection failed")
                return False
            logger.info("Milvus connection is healthy")
        except Exception as e:
            logger.error(f"Milvus connection failed: {e}")
            return False
        
        logger.info("All health checks passed!")
        return True
    
    def setup_milvus_collection(self) -> bool:
        """Set up the Milvus collection for storing documents."""
        try:
            logger.info(f"Setting up Milvus collection: {self.config.collection_name}")
            
            # Create collection if it doesn't exist
            if not self.milvus_client.create_collection():
                logger.error("Failed to create Milvus collection")
                return False
            
            # Load collection
            if not self.milvus_client.load_collection():
                logger.error("Failed to load Milvus collection")
                return False
            
            logger.info("Milvus collection setup complete")
            return True
            
        except Exception as e:
            logger.error(f"Failed to setup Milvus collection: {e}")
            return False
    
    def process_text_entry(self, entry: TextContentEntry) -> List[Document]:
        """
        Process a single text content entry into chunks for storage in Milvus.
        Entity extraction is now handled by the vectorstore class for optimal performance.
        
        Args:
            entry: TextContentEntry from ClickHouse
            
        Returns:
            List of Document objects ready for storage in Milvus
        """
        try:
            # Split text into chunks
            chunks = self.text_splitter.split_text(entry.text)
            
            documents = []
            for i, chunk_text in enumerate(chunks):
                if not chunk_text.strip():
                    continue
                
                # Create document with metadata (entities will be extracted by vectorstore)
                doc_metadata = {
                    'source_collection': entry.collection_dataset,
                    'source_file_hash': entry.file_hash,
                    'source_page_id': entry.page_id,
                    'source_extracted_by': entry.extracted_by,
                    'chunk_index': i,
                    'start_char': i * self.config.chunk_size,
                    'end_char': min((i + 1) * self.config.chunk_size, len(entry.text))
                }
                
                # Create document ID
                doc_id = f"{entry.unique_id}_{i}"
                
                # Create LangChain Document
                document = Document(
                    id=doc_id,
                    page_content=chunk_text,
                    metadata=doc_metadata
                )
                
                documents.append(document)
            
            return documents
            
        except Exception as e:
            logger.error(f"Failed to process text entry {entry.file_hash}_{entry.page_id}: {e}")
            self.stats['errors'] += 1
            return []
    
    def store_documents_batch(self, documents: List[Document]) -> bool:
        """
        Store a batch of documents in Milvus using optimized batch processing.
        The vectorstore will handle entity extraction and embedding generation automatically.
        Documents are processed in smaller batches to avoid overwhelming Milvus.
        
        Args:
            documents: List of Document objects to store
            
        Returns:
            True if successful, False otherwise
        """
        if not documents:
            return True
        
        try:
            # Process documents in smaller batches to avoid overwhelming Milvus
            batch_size = self.config.milvus_batch_size
            total_doc_ids = []
            
            for i in range(0, len(documents), batch_size):
                batch_documents = documents[i:i + batch_size]
                
                # Add documents to Milvus using optimized batch processing
                # The vectorstore will handle entity extraction and embedding generation
                doc_ids = self.milvus_client.add_documents(batch_documents)
                
                if len(doc_ids) != len(batch_documents):
                    logger.warning(f"Expected {len(batch_documents)} document IDs, got {len(doc_ids)}")
                
                total_doc_ids.extend(doc_ids)
                
                logger.debug(f"Stored batch {i//batch_size + 1}: {len(batch_documents)} documents")
            
            self.stats['total_documents_stored'] += len(total_doc_ids)
            logger.info(f"Successfully stored {len(total_doc_ids)} documents in {len(range(0, len(documents), batch_size))} batches")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to store documents batch: {e}")
            self.stats['errors'] += 1
            return False
    
    def process_batch(self, batch: List[TextContentEntry]) -> bool:
        """
        Process a batch of text content entries.
        
        Args:
            batch: List of TextContentEntry objects
            
        Returns:
            True if successful, False otherwise
        """
        try:
            all_documents = []
            
            # Process each entry in the batch
            for entry in batch:
                documents = self.process_text_entry(entry)
                all_documents.extend(documents)
                self.stats['total_processed'] += 1
                self.stats['total_chunks'] += len(documents)
            
            # Store all documents in Milvus
            if all_documents:
                success = self.store_documents_batch(all_documents)
                if not success:
                    logger.error("Failed to store documents batch")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to process batch: {e}")
            self.stats['errors'] += 1
            return False
    
    def log_progress(self, total_count: int = None):
        """Log current progress and statistics."""
        elapsed_time = time.time() - self.stats['start_time']
        rate = self.stats['total_processed'] / elapsed_time if elapsed_time > 0 else 0
        
        # Calculate ETA if total count is provided
        eta_info = ""
        if total_count and rate > 0:
            remaining_docs = total_count - self.stats['total_processed']
            eta_seconds = remaining_docs / rate
            eta_str = f"{int(eta_seconds//3600):02d}:{int((eta_seconds%3600)//60):02d}:{int(eta_seconds%60):02d}"
            eta_info = f", ETA: {eta_str}"
        
        logger.info(
            f"Progress: {self.stats['total_processed']} entries processed, "
            f"{self.stats['total_chunks']} chunks created, "
            f"{self.stats['total_documents_stored']} documents stored, "
            f"{self.stats['errors']} errors, "
            f"Rate: {rate:.2f} entries/sec{eta_info}"
        )
    
    def run(self) -> bool:
        """
        Run the complete ingestion process.
        
        Returns:
            True if successful, False otherwise
        """
        logger.info("Starting RAG ingestion process...")
        self.stats['start_time'] = time.time()
        
        # Health checks
        if not self.health_check():
            logger.error("Health checks failed. Aborting ingestion.")
            return False
        
        # Setup Milvus collection
        if not self.setup_milvus_collection():
            logger.error("Failed to setup Milvus collection. Aborting ingestion.")
            return False
        
        try:
            # Initialize text content iterator
            iterator = TextContentIterator(
                batch_size=self.config.database_batch_size,
                resume_file=self.config.resume_file,
                collection_dataset=self.config.collection_dataset,
                extracted_by_filter=self.config.extracted_by_filter,
                min_text_length=self.config.min_text_length
            )
            
            # Connect to ClickHouse
            if not iterator.connect():
                logger.error("Failed to connect to ClickHouse")
                return False
            
            # Get total count for progress tracking
            total_count = iterator.get_total_count()
            logger.info(f"Total records to process: {total_count}")
            
            # Create progress bar if enabled
            progress_bar = None
            if self.config.show_progress_bar:
                progress_bar = tqdm(
                    total=total_count,
                    desc="Processing documents",
                    unit="docs",
                    ncols=120,
                    bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}] ETA: {eta}"
                )
            
            # Process batches
            batch_count = 0
            try:
                for batch in iterator:
                    batch_count += 1
                    
                    # Process the batch
                    success = self.process_batch(batch)
                    if not success:
                        logger.error(f"Failed to process batch {batch_count}")
                        # Continue with next batch instead of failing completely
                    
                    # Update progress bar if enabled
                    if progress_bar:
                        progress_bar.update(len(batch))
                        
                        # Update progress bar description with current stats
                        elapsed_time = time.time() - self.stats['start_time']
                        rate = self.stats['total_processed'] / elapsed_time if elapsed_time > 0 else 0
                        
                        # Calculate ETA manually for the description
                        remaining_docs = total_count - self.stats['total_processed']
                        eta_seconds = remaining_docs / rate if rate > 0 else 0
                        eta_str = f"{int(eta_seconds//3600):02d}:{int((eta_seconds%3600)//60):02d}:{int(eta_seconds%60):02d}" if eta_seconds > 0 else "00:00:00"
                        
                        progress_bar.set_description(
                            f"Processing documents (chunks: {self.stats['total_chunks']}, "
                            f"stored: {self.stats['total_documents_stored']}, "
                            f"errors: {self.stats['errors']}, "
                            f"rate: {rate:.1f}/s, ETA: {eta_str})"
                        )
                    else:
                        # Log progress periodically if progress bar is disabled
                        if batch_count % (self.config.progress_interval // self.config.database_batch_size) == 0:
                            self.log_progress(total_count)
                
            finally:
                # Close progress bar if it was created
                if progress_bar:
                    progress_bar.close()
            
            # Final progress log
            self.log_progress(total_count)
            
            # Disconnect from ClickHouse
            iterator.disconnect()
            
            logger.info("RAG ingestion process completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"RAG ingestion process failed: {e}")
            return False
        
        finally:
            # Disconnect from Milvus
            try:
                self.milvus_client.disconnect()
            except Exception as e:
                logger.warning(f"Failed to disconnect from Milvus: {e}")


def main():
    """Main entry point for the ingest script."""
    parser = argparse.ArgumentParser(
        description="RAG Ingest Script - Process text content for RAG applications",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Text content iterator settings
    parser.add_argument(
        "--database-batch-size",
        type=int,
        default=50,
        help="Number of records to fetch from database per batch"
    )
    parser.add_argument(
        "--milvus-batch-size",
        type=int,
        default=200,
        help="Number of documents to insert to Milvus per batch"
    )
    parser.add_argument(
        "--collection-dataset",
        type=str,
        help="Filter by specific collection/dataset"
    )
    parser.add_argument(
        "--extracted-by",
        type=str,
        help="Filter by specific extraction method"
    )
    parser.add_argument(
        "--min-text-length",
        type=int,
        default=50,
        help="Minimum text length to include in results"
    )
    parser.add_argument(
        "--resume-file",
        type=str,
        default="logs/text_content_progress.json",
        help="File to store progress for resume functionality"
    )
    
    # Text splitting settings
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Size of text chunks"
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=200,
        help="Overlap between text chunks"
    )
    
    # Milvus settings
    parser.add_argument(
        "--milvus-host",
        type=str,
        default="http://10.69.69.5",
        help="Milvus host URL"
    )
    parser.add_argument(
        "--milvus-port",
        type=int,
        default=19530,
        help="Milvus port"
    )
    parser.add_argument(
        "--collection-name",
        type=str,
        default="rag_chunks",
        help="Milvus collection name"
    )
    
    # Client settings
    parser.add_argument(
        "--embeddings-url",
        type=str,
        default="http://localhost:8000/v1",
        help="Embeddings service base URL"
    )
    
    # Processing settings
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum number of retries for failed requests"
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=100,
        help="Log progress every N documents"
    )
    parser.add_argument(
        "--no-progress-bar",
        action="store_true",
        help="Disable tqdm progress bar (use logging instead)"
    )
    
    # Utility options
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Reset progress and start from the beginning"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform a dry run without storing data"
    )
    
    args = parser.parse_args()
    
    # Create configuration
    config = IngestConfig(
        database_batch_size=args.database_batch_size,
        milvus_batch_size=args.milvus_batch_size,
        collection_dataset=args.collection_dataset,
        extracted_by_filter=args.extracted_by,
        min_text_length=args.min_text_length,
        resume_file=args.resume_file,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        milvus_host=args.milvus_host,
        milvus_port=args.milvus_port,
        collection_name=args.collection_name,
        embeddings_base_url=args.embeddings_url,
        max_retries=args.max_retries,
        progress_interval=args.progress_interval,
        show_progress_bar=not args.no_progress_bar
    )
    
    # Reset progress if requested
    if args.reset_progress:
        logger.info("Resetting progress...")
        iterator = TextContentIterator(resume_file=config.resume_file)
        iterator.reset_progress()
        logger.info("Progress reset complete")
        return
    
    # Create and run processor
    processor = RAGIngestProcessor(config)
    
    if args.dry_run:
        logger.info("Dry run mode - performing health checks only")
        success = processor.health_check()
    else:
        success = processor.run()
    
    if success:
        logger.info("Ingest script completed successfully")
        sys.exit(0)
    else:
        logger.error("Ingest script failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
