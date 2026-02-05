import os
import json
import time
import clickhouse_connect
from typing import Dict, Any, Optional, Iterator, List
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


@dataclass
class TextContentEntry:
    """Data class representing a text content entry from ClickHouse."""
    collection_dataset: str
    file_hash: str
    extracted_by: str
    page_id: int
    text: str
    
    @property
    def unique_id(self) -> str:
        """
        Generate a human-readable unique ID for this entry.
        Format: {collection_dataset}__{file_hash}__{extracted_by}__{page_id}
        This creates a unique identifier that's under 255 characters and human-readable.
        """
        # Sanitize collection_dataset to remove special characters that might cause issues
        clean_dataset = "".join(c for c in self.collection_dataset if c.isalnum() or c in "_-")
        clean_extracted_by = "".join(c for c in self.extracted_by if c.isalnum() or c in "_-")
        
        unique_id = f"{clean_dataset}__{self.file_hash}__{clean_extracted_by}__{self.page_id}"
        
        # Ensure it's under 255 characters
        if len(unique_id) > 255:
            # Truncate the file_hash if needed, keeping the most important parts
            max_dataset_len = 50
            max_extracted_by_len = 20
            max_hash_len = 255 - max_dataset_len - max_extracted_by_len - 20  # 20 for separators and page_id
            
            truncated_dataset = clean_dataset[:max_dataset_len]
            truncated_extracted_by = clean_extracted_by[:max_extracted_by_len]
            truncated_hash = self.file_hash[:max_hash_len]
            
            unique_id = f"{truncated_dataset}__{truncated_hash}__{truncated_extracted_by}__{self.page_id}"
        
        return unique_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the entry to a dictionary."""
        return {
            'unique_id': self.unique_id,
            'collection_dataset': self.collection_dataset,
            'file_hash': self.file_hash,
            'extracted_by': self.extracted_by,
            'page_id': self.page_id,
            'text': self.text
        }
    


class TextContentIterator:
    """
    Iterator class for processing text_content table from ClickHouse with resume functionality.
    
    Features:
    - Batch processing for efficient memory usage
    - Resume functionality using offset tracking
    - Progress persistence to file
    - Configurable batch sizes
    - Error handling and retry logic
    """
    
    def __init__(
        self,
        batch_size: int = 100,
        resume_file: str = "text_content_progress.json",
        collection_dataset: Optional[str] = None,
        extracted_by_filter: Optional[str] = None,
        min_text_length: int = 10
    ):
        """
        Initialize the TextContentIterator.
        
        Args:
            batch_size: Number of records to fetch per batch
            resume_file: File to store progress for resume functionality
            collection_dataset: Filter by specific collection/dataset (optional)
            extracted_by_filter: Filter by specific extraction method (optional)
            min_text_length: Minimum text length to include in results
        """
        self.batch_size = batch_size
        self.resume_file = Path(resume_file)
        self.collection_dataset = collection_dataset
        self.extracted_by_filter = extracted_by_filter
        self.min_text_length = min_text_length
        
        # Progress tracking
        self.current_offset = 0
        self.total_processed = 0
        self.start_time = None
        
        # ClickHouse connection settings
        self.host = os.getenv('CLICKHOUSE_HOST', 'localhost')
        self.port = int(os.getenv('CLICKHOUSE_PORT', 8123))
        self.username = os.getenv('CLICKHOUSE_USERNAME', 'default')
        self.password = os.getenv('CLICKHOUSE_PASSWORD', '')
        self.database = os.getenv('CLICKHOUSE_DATABASE', 'default')
        
        # ClickHouse client
        self.client = None
        self.connected = False
        
        # Load progress if resume file exists
        self._load_progress()
    
    def _load_progress(self) -> None:
        """Load progress from resume file if it exists."""
        if self.resume_file.exists():
            try:
                with open(self.resume_file, 'r') as f:
                    progress = json.load(f)
                    self.current_offset = progress.get('current_offset', 0)
                    self.total_processed = progress.get('total_processed', 0)
                    print(f"Resuming from offset {self.current_offset} (total processed: {self.total_processed})")
            except Exception as e:
                print(f"Warning: Could not load progress file: {e}")
                self.current_offset = 0
                self.total_processed = 0
    
    def _save_progress(self) -> None:
        """Save current progress to resume file."""
        try:
            progress = {
                'current_offset': self.current_offset,
                'total_processed': self.total_processed,
                'last_updated': time.time(),
                'collection_dataset': self.collection_dataset,
                'extracted_by_filter': self.extracted_by_filter
            }
            with open(self.resume_file, 'w') as f:
                json.dump(progress, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save progress: {e}")
    
    def _build_query(self) -> str:
        """Build the SQL query based on filters."""
        base_query = """
        SELECT 
            collection_dataset,
            file_hash,
            extracted_by,
            page_id,
            text
        FROM text_content
        WHERE length(text) >= {min_length}
        """.format(min_length=self.min_text_length)
        
        conditions = []
        
        if self.collection_dataset:
            conditions.append(f"AND collection_dataset = '{self.collection_dataset}'")
        
        if self.extracted_by_filter:
            conditions.append(f"AND extracted_by = '{self.extracted_by_filter}'")
        
        if conditions:
            base_query += " " + " ".join(conditions)
        
        # Add ordering and pagination
        base_query += """
        ORDER BY collection_dataset, file_hash, page_id
        LIMIT {batch_size} OFFSET {offset}
        """.format(batch_size=self.batch_size, offset=self.current_offset)
        
        return base_query
    
    def connect(self) -> bool:
        """Connect to ClickHouse database."""
        try:
            self.client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                database=self.database
            )
            self.connected = True
            self.start_time = time.time()
            print(f"Successfully connected to ClickHouse at {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"Failed to connect to ClickHouse: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from ClickHouse and save progress."""
        if self.connected and self.client:
            self.client.close()
            self.client = None
            self.connected = False
            self._save_progress()
            print("ClickHouse connection closed.")
    
    def get_total_count(self) -> int:
        """Get total number of records that match the filter criteria."""
        if not self.connected:
            raise RuntimeError("Not connected to ClickHouse. Call connect() first.")
        
        count_query = """
        SELECT COUNT(*)
        FROM text_content
        WHERE length(text) >= {min_length}
        """.format(min_length=self.min_text_length)
        
        conditions = []
        if self.collection_dataset:
            conditions.append(f"AND collection_dataset = '{self.collection_dataset}'")
        
        if self.extracted_by_filter:
            conditions.append(f"AND extracted_by = '{self.extracted_by_filter}'")
        
        if conditions:
            count_query += " " + " ".join(conditions)
        
        try:
            result = self.client.query(count_query)
            return result.result_rows[0][0]
        except Exception as e:
            print(f"Error getting total count: {e}")
            return 0
    
    def reset_progress(self) -> None:
        """Reset progress to start from the beginning."""
        self.current_offset = 0
        self.total_processed = 0
        if self.resume_file.exists():
            self.resume_file.unlink()
        print("Progress reset. Will start from the beginning.")
    
    def get_progress_stats(self) -> Dict[str, Any]:
        """Get current progress statistics."""
        if self.start_time:
            elapsed_time = time.time() - self.start_time
            rate = self.total_processed / elapsed_time if elapsed_time > 0 else 0
        else:
            elapsed_time = 0
            rate = 0
        
        return {
            'total_processed': self.total_processed,
            'current_offset': self.current_offset,
            'elapsed_time': elapsed_time,
            'processing_rate': rate,
            'batch_size': self.batch_size
        }
    
    def __iter__(self) -> Iterator[List[TextContentEntry]]:
        """Make the class iterable, yielding batches of TextContentEntry objects."""
        if not self.connected:
            raise RuntimeError("Not connected to ClickHouse. Call connect() first.")
        
        while True:
            try:
                query = self._build_query()
                result = self.client.query(query)
                
                if not result.result_rows:
                    # No more data
                    print(f"Iteration complete. Total processed: {self.total_processed}")
                    break
                
                # Convert rows to TextContentEntry objects
                batch = []
                for row in result.result_rows:
                    entry = TextContentEntry(
                        collection_dataset=row[0],
                        file_hash=row[1],
                        extracted_by=row[2],
                        page_id=row[3],
                        text=row[4]
                    )
                    batch.append(entry)
                
                # Update progress
                batch_size = len(batch)
                self.current_offset += batch_size
                self.total_processed += batch_size
                
                # Save progress periodically (every 10 batches)
                if (self.total_processed // self.batch_size) % 10 == 0:
                    self._save_progress()
                
                yield batch
                
            except Exception as e:
                print(f"Error during iteration: {e}")
                self._save_progress()
                raise
    
    def __enter__(self):
        """Context manager entry."""
        if not self.connect():
            raise RuntimeError("Failed to connect to ClickHouse")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


# Example usage and utility functions
def process_text_content_for_rag(
    batch_size: int = 100,
    collection_dataset: Optional[str] = None,
    resume_file: str = "text_content_progress.json"
) -> Iterator[List[TextContentEntry]]:
    """
    Convenience function to process text content for RAG ingestion.
    
    Args:
        batch_size: Number of records per batch
        collection_dataset: Filter by specific collection (optional)
        resume_file: Progress file for resume functionality
    
    Yields:
        Batches of TextContentEntry objects
    """
    with TextContentIterator(
        batch_size=batch_size,
        collection_dataset=collection_dataset,
        resume_file=resume_file
    ) as iterator:
        
        total_count = iterator.get_total_count()
        print(f"Total records to process: {total_count}")
        
        for batch in iterator:
            # Print progress every 1000 records
            if iterator.total_processed % 1000 == 0:
                stats = iterator.get_progress_stats()
                print(f"Processed: {stats['total_processed']}/{total_count} "
                      f"({stats['total_processed']/total_count*100:.1f}%) "
                      f"Rate: {stats['processing_rate']:.1f} records/sec")
            
            yield batch


if __name__ == "__main__":
    """Example usage of the TextContentIterator."""
    
    # Example 1: Basic iteration with resume
    print("=== Example 1: Basic iteration ===")
    with TextContentIterator(batch_size=50) as iterator:
        total_count = iterator.get_total_count()
        print(f"Total records: {total_count}")
        
        for i, batch in enumerate(iterator):
            print(f"Batch {i+1}: {len(batch)} records")
            print(f"First entry: {batch[0].collection_dataset} - {batch[0].text}")
            
            # Process only first 3 batches for demo
            if i >= 2:
                break
    
    # Example 2: Filtered iteration
    print("\n=== Example 2: Filtered iteration ===")
    with TextContentIterator(
        batch_size=25,
        collection_dataset="your-dataset-name",  # Replace with actual dataset
        min_text_length=50
    ) as iterator:
        for i, batch in enumerate(iterator):
            print(f"Filtered batch {i+1}: {len(batch)} records")
            if i >= 1:
                break
