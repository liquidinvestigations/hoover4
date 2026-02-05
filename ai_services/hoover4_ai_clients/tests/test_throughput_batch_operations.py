#!/usr/bin/env python3
"""
Comprehensive throughput tests for batch operations using real connections.

This test suite measures the performance of batch operations for:
- Hoover4EmbeddingsClient: Batch embedding generation
- Hoover4NERClient: Batch entity extraction
- Hoover4MilvusVectorStore: Batch document insertion, search, and deletion

All tests use real connections (no mocks) and include proper cleanup.
"""

import asyncio
import logging
import statistics
import time
from typing import Dict, List, Tuple

import pytest
from langchain_core.documents import Document

from hoover4_ai_clients.embeddings_client import Hoover4EmbeddingsClient
from hoover4_ai_clients.milvus_client import Hoover4MilvusVectorStore
from hoover4_ai_clients.ner_client import Hoover4NERClient

# Configure logging for throughput tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ThroughputMetrics:
    """Container for throughput test metrics."""
    
    def __init__(self):
        self.operation_times: List[float] = []
        self.total_operations: int = 0
        self.total_documents: int = 0  # Track total documents processed
        self.total_time: float = 0.0
        self.successful_operations: int = 0
        self.failed_operations: int = 0
        self.errors: List[str] = []
    
    def add_operation(self, duration: float, documents_processed: int = 1, success: bool = True, error: str = None):
        """Add an operation result to metrics."""
        self.operation_times.append(duration)
        self.total_operations += 1
        self.total_documents += documents_processed
        self.total_time += duration
        
        if success:
            self.successful_operations += 1
        else:
            self.failed_operations += 1
            if error:
                self.errors.append(error)
    
    def get_stats(self) -> Dict:
        """Get comprehensive statistics."""
        if not self.operation_times:
            return {"error": "No operations recorded"}
        
        return {
            "total_operations": self.total_operations,
            "total_documents": self.total_documents,
            "successful_operations": self.successful_operations,
            "failed_operations": self.failed_operations,
            "success_rate": self.successful_operations / self.total_operations,
            "total_time": self.total_time,
            "avg_time_per_operation": self.total_time / self.total_operations,
            "avg_documents_per_operation": self.total_documents / self.total_operations,
            "min_time": min(self.operation_times),
            "max_time": max(self.operation_times),
            "median_time": statistics.median(self.operation_times),
            "operations_per_second": self.total_operations / self.total_time if self.total_time > 0 else 0,
            "documents_per_second": self.total_documents / self.total_time if self.total_time > 0 else 0,
            "errors": self.errors[:10]  # Limit to first 10 errors
        }


@pytest.mark.throughput
@pytest.mark.embeddings
@pytest.mark.ner
@pytest.mark.milvus
class TestBatchThroughput:
    """Comprehensive throughput tests for batch operations."""
    
    # Test data generation
    SAMPLE_TEXTS = [
        "Apple Inc. was founded by Steve Jobs and Steve Wozniak in Cupertino, California in 1976.",
        "Microsoft Corporation is headquartered in Redmond, Washington and was founded by Bill Gates.",
        "Google LLC is based in Mountain View, California and was founded by Larry Page and Sergey Brin.",
        "Tesla Inc. was founded by Elon Musk and is located in Austin, Texas.",
        "Amazon.com Inc. is headquartered in Seattle, Washington and was founded by Jeff Bezos.",
        "Meta Platforms Inc. is based in Menlo Park, California and was founded by Mark Zuckerberg.",
        "Netflix Inc. is headquartered in Los Gatos, California and was founded by Reed Hastings.",
        "Uber Technologies Inc. is based in San Francisco, California and was founded by Travis Kalanick.",
        "Airbnb Inc. is headquartered in San Francisco, California and was founded by Brian Chesky.",
        "Twitter Inc. is based in San Francisco, California and was founded by Jack Dorsey."
    ]
    
    SEARCH_QUERIES = [
        "technology companies in California",
        "companies founded by Steve Jobs",
        "tech companies in Washington state",
        "electric vehicle companies",
        "e-commerce companies",
        "social media companies",
        "ride-sharing companies",
        "streaming services",
        "companies in Silicon Valley",
        "startups in San Francisco"
    ]
    
    # Fixtures are now provided by conftest.py
    
    def generate_test_texts(self, count: int) -> List[str]:
        """Generate test texts by repeating and varying the sample texts."""
        texts = []
        for i in range(count):
            base_text = self.SAMPLE_TEXTS[i % len(self.SAMPLE_TEXTS)]
            # Add variation to make each text unique
            texts.append(f"{base_text} (Test document {i+1})")
        return texts
    
    def test_embeddings_batch_throughput(self, throughput_embeddings_client, server_health_check):
        """Test batch embeddings throughput with various batch sizes."""
        if not server_health_check:
            pytest.skip("Server not available")
        
        batch_sizes = [50, 100, 200]
        total_texts = 200  # Total texts to process across all batches
        
        logger.info("Starting embeddings batch throughput test...")
        
        for batch_size in batch_sizes:
            logger.info(f"Testing batch size: {batch_size}")
            metrics = ThroughputMetrics()
            
            # Generate test texts
            all_texts = self.generate_test_texts(total_texts)
            
            # Process in batches
            for i in range(0, len(all_texts), batch_size):
                batch_texts = all_texts[i:i + batch_size]
                
                start_time = time.time()
                try:
                    embeddings = throughput_embeddings_client.embed_documents(batch_texts)
                    end_time = time.time()
                    
                    # Validate results
                    assert len(embeddings) == len(batch_texts)
                    assert all(len(emb) == 1024 for emb in embeddings)
                    assert all(all(isinstance(x, float) for x in emb) for emb in embeddings)
                    
                    metrics.add_operation(end_time - start_time, documents_processed=len(batch_texts), success=True)
                    
                except Exception as e:
                    end_time = time.time()
                    metrics.add_operation(end_time - start_time, documents_processed=len(batch_texts), success=False, error=str(e))
            
            # Report metrics
            stats = metrics.get_stats()
            logger.info(f"Batch size {batch_size} results:")
            logger.info(f"  Documents/sec: {stats['documents_per_second']:.2f}")
            logger.info(f"  Operations/sec: {stats['operations_per_second']:.2f}")
            logger.info(f"  Avg documents per batch: {stats['avg_documents_per_operation']:.1f}")
            logger.info(f"  Avg time per batch: {stats['avg_time_per_operation']:.3f}s")
            logger.info(f"  Success rate: {stats['success_rate']:.2%}")
            logger.info(f"  Total documents processed: {stats['total_documents']}")
            logger.info(f"  Total time: {stats['total_time']:.2f}s")
            
            # Assert minimum performance thresholds
            assert stats['success_rate'] >= 0.95, f"Success rate too low: {stats['success_rate']:.2%}"
            assert stats['documents_per_second'] > 0.5, f"Throughput too low: {stats['documents_per_second']:.2f} docs/sec"
    
    def test_ner_batch_throughput(self, throughput_ner_client, server_health_check):
        """Test batch NER throughput with various batch sizes."""
        if not server_health_check:
            pytest.skip("Server not available")
        
        batch_sizes = [50, 100, 200]
        total_texts = 200  # Total texts to process across all batches
        
        logger.info("Starting NER batch throughput test...")
        
        for batch_size in batch_sizes:
            logger.info(f"Testing batch size: {batch_size}")
            metrics = ThroughputMetrics()
            
            # Generate test texts
            all_texts = self.generate_test_texts(total_texts)
            
            # Process in batches
            for i in range(0, len(all_texts), batch_size):
                batch_texts = all_texts[i:i + batch_size]
                
                start_time = time.time()
                try:
                    entities = throughput_ner_client.extract_entities(batch_texts)
                    end_time = time.time()
                    
                    # Validate results
                    assert len(entities) == len(batch_texts)
                    assert all(isinstance(entity_dict, dict) for entity_dict in entities)
                    assert all("PER" in entity_dict for entity_dict in entities)
                    assert all("ORG" in entity_dict for entity_dict in entities)
                    assert all("LOC" in entity_dict for entity_dict in entities)
                    assert all("MISC" in entity_dict for entity_dict in entities)
                    
                    metrics.add_operation(end_time - start_time, documents_processed=len(batch_texts), success=True)
                    
                except Exception as e:
                    end_time = time.time()
                    metrics.add_operation(end_time - start_time, documents_processed=len(batch_texts), success=False, error=str(e))
            
            # Report metrics
            stats = metrics.get_stats()
            logger.info(f"Batch size {batch_size} results:")
            logger.info(f"  Documents/sec: {stats['documents_per_second']:.2f}")
            logger.info(f"  Operations/sec: {stats['operations_per_second']:.2f}")
            logger.info(f"  Avg documents per batch: {stats['avg_documents_per_operation']:.1f}")
            logger.info(f"  Avg time per batch: {stats['avg_time_per_operation']:.3f}s")
            logger.info(f"  Success rate: {stats['success_rate']:.2%}")
            logger.info(f"  Total documents processed: {stats['total_documents']}")
            logger.info(f"  Total time: {stats['total_time']:.2f}s")
            
            # Assert minimum performance thresholds
            assert stats['success_rate'] >= 0.95, f"Success rate too low: {stats['success_rate']:.2%}"
            assert stats['documents_per_second'] > 0.5, f"Throughput too low: {stats['documents_per_second']:.2f} docs/sec"
    
    def test_milvus_batch_throughput(self, throughput_milvus_client, server_health_check, milvus_health_check):
        """Test batch Milvus operations throughput."""
        if not server_health_check or not milvus_health_check:
            pytest.skip("Required services not available")
        
        logger.info("Starting Milvus batch throughput test...")
        
        # Setup: Create and load collection
        assert throughput_milvus_client.connect(), "Failed to connect to Milvus"
        assert throughput_milvus_client.create_collection(), "Failed to create collection"
        assert throughput_milvus_client.load_collection(), "Failed to load collection"
        
        try:
            self._test_milvus_batch_insertion(throughput_milvus_client)
            
        finally:
            # Cleanup: Drop collection
            try:
                throughput_milvus_client.drop_collection()
                logger.info("Cleaned up test collection")
            except Exception as e:
                logger.warning(f"Failed to clean up collection: {e}")
    
    def _test_milvus_batch_insertion(self, milvus_client):
        """Test batch document insertion throughput using optimized client."""
        logger.info("Testing Milvus batch insertion with optimized client...")
        
        batch_sizes = [50, 100, 200]
        total_docs = 200
        
        for batch_size in batch_sizes:
            logger.info(f"Testing insertion batch size: {batch_size}")
            metrics = ThroughputMetrics()
            
            # Generate test documents - no need to pre-process NER or embeddings
            texts = self.generate_test_texts(total_docs)
            documents = []
            
            for i, text in enumerate(texts):
                doc = Document(
                    id=f"doc_{i}",
                    page_content=text,
                    metadata={
                        "source_collection": "throughput_test",
                        "source_file_hash": f"hash_{i}",
                        "source_page_id": i,
                        "source_extracted_by": "throughput_test",
                        "chunk_index": i,
                        "start_char": 0,
                        "end_char": len(text),
                        # Let the optimized client handle NER extraction internally
                    }
                )
                documents.append(doc)
            
            # Process in batches - optimized client handles embeddings and NER internally
            for i in range(0, len(documents), batch_size):
                batch_docs = documents[i:i + batch_size]
                
                start_time = time.time()
                try:
                    doc_ids = milvus_client.add_documents(batch_docs)
                    end_time = time.time()
                    
                    # Validate results
                    assert len(doc_ids) == len(batch_docs)
                    
                    metrics.add_operation(end_time - start_time, documents_processed=len(batch_docs), success=True)
                    
                except Exception as e:
                    end_time = time.time()
                    metrics.add_operation(end_time - start_time, documents_processed=len(batch_docs), success=False, error=str(e))
            
            # Report metrics
            stats = metrics.get_stats()
            logger.info(f"Insertion batch size {batch_size} results:")
            logger.info(f"  Documents/sec: {stats['documents_per_second']:.2f}")
            logger.info(f"  Operations/sec: {stats['operations_per_second']:.2f}")
            logger.info(f"  Avg documents per batch: {stats['avg_documents_per_operation']:.1f}")
            logger.info(f"  Avg time per batch: {stats['avg_time_per_operation']:.3f}s")
            logger.info(f"  Success rate: {stats['success_rate']:.2%}")
            logger.info(f"  Total documents processed: {stats['total_documents']}")
            logger.info(f"  Total time: {stats['total_time']:.2f}s")
            
            # Assert minimum performance thresholds
            assert stats['success_rate'] >= 0.95, f"Success rate too low: {stats['success_rate']:.2%}"
            assert stats['documents_per_second'] > 0.1, f"Throughput too low: {stats['documents_per_second']:.2f} docs/sec"

if __name__ == "__main__":
    # Run the tests with pytest
    pytest.main([__file__, "-v", "--throughput"])
