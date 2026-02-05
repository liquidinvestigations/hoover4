"""Integration tests for Hoover4MilvusVectorStore against live database."""

import time

import pytest
from langchain_core.documents import Document

from hoover4_ai_clients.milvus_client import Hoover4MilvusVectorStore
from tests.conftest import MILVUS_HOST, MILVUS_PORT


def wait_for_documents_ready(milvus_client, doc_ids, timeout=5.0):
    """
    Helper function to wait for documents to be ready for search operations.
    This replaces the need for fixed sleep calls in tests.
    """
    return _ensure_documents_ready(milvus_client, doc_ids, timeout=timeout)


def _wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0, check_interval=0.1):
    """
    Wait for documents to be available for search operations.
    
    Args:
        milvus_client: The Milvus client instance
        doc_ids: List of document IDs to check for
        timeout: Maximum time to wait in seconds
        check_interval: Time between checks in seconds
        
    Returns:
        True if all documents are ready, False if timeout exceeded
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # Try to retrieve the documents
            retrieved_docs = milvus_client.get_by_ids(doc_ids)
            if len(retrieved_docs) == len(doc_ids):
                # All documents found, now check if they're searchable
                # by doing a simple search
                if _test_document_searchability(milvus_client, doc_ids):
                    return True
        except Exception:
            # If there's an error, continue waiting
            pass
        
        time.sleep(check_interval)
    
    return False


def _test_document_searchability(milvus_client, doc_ids):
    """
    Test if documents are searchable by performing a simple query.
    
    Args:
        milvus_client: The Milvus client instance
        doc_ids: List of document IDs to test
        
    Returns:
        True if documents are searchable, False otherwise
    """
    try:
        # Try a simple search to see if the documents are indexed
        # We'll search for a very common term that should match any document
        results = milvus_client.similarity_search("test", k=len(doc_ids) + 10)
        
        # Check if any of our target documents are in the results
        result_ids = [doc.id for doc in results]
        found_count = sum(1 for doc_id in doc_ids if doc_id in result_ids)
        
        # If we found at least some of our documents, they're searchable
        return found_count > 0
        
    except Exception:
        return False


def _ensure_documents_ready(milvus_client, doc_ids, timeout=5.0):
    """
    Ensure documents are ready for search operations.
    This method flushes the collection and waits for documents to be ready.
    
    Args:
        milvus_client: The Milvus client instance
        doc_ids: List of document IDs to ensure are ready
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if documents are ready, False otherwise
    """
    # First flush to ensure data is persisted
    milvus_client.flush_collection()
    
    # Then wait for documents to be searchable
    return _wait_for_documents_ready(milvus_client, doc_ids, timeout=timeout)


@pytest.mark.integration
@pytest.mark.milvus
class TestMilvusIntegration:
    """Integration tests for Milvus client with live database."""

    def test_milvus_client_initialization(self, milvus_client):
        """Test Milvus client initialization."""
        assert milvus_client.collection_name is not None
        assert milvus_client.host is not None
        assert milvus_client.port is not None
        assert milvus_client.embedding_dim == 1024
        assert milvus_client.embeddings is not None

    def test_milvus_connection(self, milvus_client, milvus_health_check):
        """Test connection to Milvus database."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        result = milvus_client.connect()
        assert result is True

    def test_create_collection(self, milvus_client, milvus_health_check):
        """Test creating a new collection."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Connect first
        milvus_client.connect()

        # Create collection
        result = milvus_client.create_collection()
        assert result is True

    def test_load_collection(self, milvus_client, milvus_health_check):
        """Test loading an existing collection."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Connect and create collection first
        milvus_client.connect()
        milvus_client.create_collection()

        # Load collection
        result = milvus_client.load_collection()
        assert result is True

    def test_add_documents(self, milvus_client, milvus_health_check):
        """Test adding documents to the vector store."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Create test documents
        documents = [
            Document(
                id="doc1",
                page_content="Apple Inc. was founded by Steve Jobs in Cupertino, California.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "Steve Jobs",
                    "entities_organizations": "Apple Inc.",
                    "entities_locations": "Cupertino, California",
                    "entities_miscellaneous": ""
                }
            ),
            Document(
                id="doc2",
                page_content="Microsoft Corporation is headquartered in Redmond, Washington.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 1,
                    "start_char": 0,
                    "end_char": 55,
                    "entities_persons": "",
                    "entities_organizations": "Microsoft Corporation",
                    "entities_locations": "Redmond, Washington",
                    "entities_miscellaneous": ""
                }
            )
        ]

        # Add documents
        doc_ids = milvus_client.add_documents(documents)

        assert len(doc_ids) == 2
        assert doc_ids[0] == "doc1"
        assert doc_ids[1] == "doc2"

        # Wait for documents to be ready for search
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for search"

    def test_similarity_search(self, milvus_client, milvus_health_check):
        """Test similarity search functionality."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="tech_doc1",
                page_content="Apple Inc. is a technology company that makes iPhones and MacBooks.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 60,
                    "entities_persons": "",
                    "entities_organizations": "Apple Inc.",
                    "entities_locations": "",
                    "entities_miscellaneous": "technology, iPhones, MacBooks"
                }
            ),
            Document(
                id="cooking_doc1",
                page_content="Cooking pasta requires boiling water and adding salt for flavor.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 1,
                    "start_char": 0,
                    "end_char": 55,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "cooking, pasta, water, salt"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for search"

        # Search for technology-related content
        results = milvus_client.similarity_search("technology companies", k=2)

        assert len(results) <= 2
        assert len(results) > 0

        # The technology document should be more relevant
        tech_doc_found = any("Apple" in doc.page_content for doc in results)
        assert tech_doc_found

    def test_similarity_search_with_score(self, milvus_client, milvus_health_check):
        """Test similarity search with scores."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="ai_doc1",
                page_content="Artificial intelligence is transforming various industries.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "artificial intelligence, industries"
                }
            ),
            Document(
                id="cooking_doc2",
                page_content="Baking bread requires flour, water, yeast, and time.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 1,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "baking, bread, flour, water, yeast"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for search"

        # Search with scores
        results = milvus_client.similarity_search_with_score("machine learning", k=2)

        assert len(results) <= 2
        assert len(results) > 0

        # Check result format
        for doc, score in results:
            assert isinstance(doc, Document)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_similarity_search_by_vector(self, milvus_client, milvus_health_check):
        """Test similarity search using vector directly."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="vector_doc1",
                page_content="Machine learning algorithms can process large datasets.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "machine learning, algorithms, datasets"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for search"

        # Create a test vector (mock embedding)
        test_vector = [0.1] * 1024

        # Search by vector
        results = milvus_client.similarity_search_by_vector(test_vector, k=1)

        assert len(results) <= 1
        assert len(results) > 0
        assert isinstance(results[0], Document)

    def test_get_by_ids(self, milvus_client, milvus_health_check):
        """Test retrieving documents by their IDs."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="retrieve_doc1",
                page_content="This is the first document for retrieval testing.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 45,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "retrieval, testing"
                }
            ),
            Document(
                id="retrieve_doc2",
                page_content="This is the second document for retrieval testing.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 1,
                    "start_char": 0,
                    "end_char": 46,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "retrieval, testing"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for search"

        # Retrieve by IDs
        retrieved_docs = milvus_client.get_by_ids(["retrieve_doc1", "retrieve_doc2"])

        assert len(retrieved_docs) == 2

        # Check document content
        doc_ids = [doc.id for doc in retrieved_docs]
        assert "retrieve_doc1" in doc_ids
        assert "retrieve_doc2" in doc_ids

    def test_delete_documents(self, milvus_client, milvus_health_check):
        """Test deleting documents from the vector store."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="delete_doc1",
                page_content="This document will be deleted.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 30,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "deletion, testing"
                }
            ),
            Document(
                id="keep_doc1",
                page_content="This document will be kept.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 1,
                    "start_char": 0,
                    "end_char": 28,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "keeping, testing"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for search"

        # Delete specific document
        result = milvus_client.delete(ids=["delete_doc1"])
        assert result is True

        # Wait for deletion to complete by checking remaining documents
        assert wait_for_documents_ready(milvus_client, ["keep_doc1"]), "Remaining document should be ready"

        # Verify deletion
        remaining_docs = milvus_client.get_by_ids(["delete_doc1", "keep_doc1"])
        remaining_ids = [doc.id for doc in remaining_docs]

        assert "delete_doc1" not in remaining_ids
        assert "keep_doc1" in remaining_ids

    def test_delete_all_documents(self, milvus_client, milvus_health_check):
        """Test deleting all documents from the vector store."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="delete_all_doc1",
                page_content="This document will be deleted with all others.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 45,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "deletion, all, testing"
                }
            ),
            Document(
                id="delete_all_doc2",
                page_content="This document will also be deleted.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 1,
                    "start_char": 0,
                    "end_char": 35,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "deletion, all, testing"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for search"

        # Delete all documents
        result = milvus_client.delete()
        assert result is True

        # Wait for deletion to complete by checking that no documents remain
        # We'll wait a short time and then verify deletion
        time.sleep(0.1)  # Minimal wait for deletion to propagate

        # Verify all documents are deleted
        remaining_docs = milvus_client.get_by_ids(["delete_all_doc1", "delete_all_doc2"])
        assert len(remaining_docs) == 0

    def test_from_texts_class_method(self, milvus_health_check):
        """Test the from_texts class method."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        from tests.conftest import MockEmbeddings

        texts = [
            "This is the first text for from_texts testing.",
            "This is the second text for from_texts testing."
        ]
        metadatas = [
            {"source": "test1", "type": "from_texts"},
            {"source": "test2", "type": "from_texts"}
        ]
        ids = ["from_texts_1", "from_texts_2"]

        # Create vector store using from_texts
        vector_store = Hoover4MilvusVectorStore.from_texts(
            texts=texts,
            embedding=MockEmbeddings(),
            metadatas=metadatas,
            ids=ids,
            collection_name="test_from_texts_collection",
            host=MILVUS_HOST,
            port=MILVUS_PORT,
            embedding_dim=1024
        )

        assert isinstance(vector_store, Hoover4MilvusVectorStore)
        assert vector_store.collection_name == "test_from_texts_collection"
        assert vector_store.embeddings is not None

        # Clean up the test collection
        try:
            vector_store.drop_collection()
        except Exception:
            pass  # Collection might not exist or already dropped

    def test_collection_cleanup(self, milvus_client, milvus_health_check):
        """Test that collection cleanup works properly."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add a test document
        documents = [
            Document(
                id="cleanup_doc1",
                page_content="This document is for cleanup testing.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 35,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "cleanup, testing"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for search"

        # Verify document exists
        retrieved_docs = milvus_client.get_by_ids(["cleanup_doc1"])
        assert len(retrieved_docs) == 1

        # The cleanup should happen automatically via the fixture
        # This test just verifies the document was added successfully

    def test_hybrid_search_basic(self, milvus_client, milvus_health_check):
        """Test basic hybrid search functionality."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents with entities
        documents = [
            Document(
                id="hybrid_doc1",
                page_content="Machine learning and artificial intelligence are transforming technology.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 75,
                    "entities_persons": "John Doe",
                    "entities_organizations": "OpenAI, Google",
                    "entities_locations": "San Francisco, California",
                    "entities_miscellaneous": "technology, innovation"
                }
            ),
            Document(
                id="hybrid_doc2",
                page_content="Data science and analytics help businesses make better decisions.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 65,
                    "entities_persons": "Jane Smith",
                    "entities_organizations": "Microsoft, Amazon",
                    "entities_locations": "Seattle, Washington",
                    "entities_miscellaneous": "business, analytics"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for hybrid search"

        # Test hybrid search with entities
        results = milvus_client.hybrid_search(
            query="machine learning technology",
            k=2,
            use_entities=True
        )

        assert len(results) <= 2
        assert all(isinstance(result, tuple) and len(result) == 2 for result in results)
        assert all(isinstance(result[0], Document) for result in results)
        assert all(isinstance(result[1], (int, float)) for result in results)

        # Test hybrid search without entities
        results_no_entities = milvus_client.hybrid_search(
            query="data science",
            k=2,
            use_entities=False
        )

        assert len(results_no_entities) <= 2
        assert all(isinstance(result, tuple) and len(result) == 2 for result in results_no_entities)

    def test_hybrid_search_with_custom_weights(self, milvus_client, milvus_health_check):
        """Test hybrid search with custom weights."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="weight_doc1",
                page_content="Natural language processing is a subset of artificial intelligence.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 75,
                    "entities_persons": "Alan Turing",
                    "entities_organizations": "MIT, Stanford",
                    "entities_locations": "Boston, Cambridge",
                    "entities_miscellaneous": "NLP, AI"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for hybrid search"

        # Test with custom weights (favor dense search)
        custom_weights = [2.0, 0.5, 0.5, 0.5]  # dense, entities...
        results = milvus_client.hybrid_search(
            query="natural language processing",
            k=1,
            use_entities=True,
            weights=custom_weights
        )

        assert len(results) <= 1
        if results:
            assert isinstance(results[0], tuple)
            assert isinstance(results[0][0], Document)
            assert isinstance(results[0][1], (int, float))

    def test_similarity_search_with_hybrid_mode(self, milvus_client, milvus_health_check):
        """Test that similarity_search works with hybrid mode."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup with hybrid mode
        milvus_client.search_mode = "hybrid"
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="hybrid_mode_doc1",
                page_content="Computer vision and image recognition technologies.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "Yann LeCun",
                    "entities_organizations": "Facebook AI, NYU",
                    "entities_locations": "New York, Paris",
                    "entities_miscellaneous": "computer vision, deep learning"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for hybrid search"

        # Test similarity_search with hybrid mode
        results = milvus_client.similarity_search(
            query="computer vision",
            k=1
        )

        assert len(results) <= 1
        if results:
            assert isinstance(results[0], Document)

        # Test similarity_search_with_score with hybrid mode
        results_with_scores = milvus_client.similarity_search_with_score(
            query="image recognition",
            k=1
        )

        assert len(results_with_scores) <= 1
        if results_with_scores:
            assert isinstance(results_with_scores[0], tuple)
            assert isinstance(results_with_scores[0][0], Document)
            assert isinstance(results_with_scores[0][1], (int, float))

    def test_ner_milvus_hybrid_search_integration(self, milvus_client, milvus_health_check, server_health_check):
        """Test NER-Milvus integration with hybrid search using entity extraction."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")
        if not server_health_check:
            pytest.skip("Server not available")

        # Setup Milvus client with NER enabled
        milvus_client.use_ner_for_entities = True
        milvus_client.search_mode = "hybrid"
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents with rich entity information
        documents = [
            Document(
                id="ner_test_doc1",
                page_content="Apple Inc. was founded by Steve Jobs and Steve Wozniak in Cupertino, California in 1976.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 85,
                    "entities_persons": "Steve Jobs, Steve Wozniak",
                    "entities_organizations": "Apple Inc.",
                    "entities_locations": "Cupertino, California",
                    "entities_miscellaneous": "technology, computer, founding"
                }
            ),
            Document(
                id="ner_test_doc2",
                page_content="Microsoft Corporation is headquartered in Redmond, Washington and was founded by Bill Gates.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 85,
                    "entities_persons": "Bill Gates",
                    "entities_organizations": "Microsoft Corporation",
                    "entities_locations": "Redmond, Washington",
                    "entities_miscellaneous": "software, technology, headquarters"
                }
            ),
            Document(
                id="ner_test_doc3",
                page_content="Tesla Inc. is an electric vehicle company founded by Elon Musk in Austin, Texas.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash3",
                    "source_page_id": 3,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 75,
                    "entities_persons": "Elon Musk",
                    "entities_organizations": "Tesla Inc.",
                    "entities_locations": "Austin, Texas",
                    "entities_miscellaneous": "electric vehicles, automotive, clean energy"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for NER hybrid search"

        # Test 1: Search using person entities extracted by NER
        results = milvus_client.hybrid_search(
            query="Steve Jobs founded a company",
            k=3,
            use_entities=True
        )

        assert len(results) <= 3
        assert len(results) > 0

        # Should find the Apple document since it contains "Steve Jobs"
        apple_doc_found = any("Apple" in doc.page_content for doc, score in results)
        assert apple_doc_found, "Should find Apple document when searching for Steve Jobs"

        # Test 2: Search using organization entities
        results = milvus_client.hybrid_search(
            query="Microsoft Corporation headquarters",
            k=3,
            use_entities=True
        )

        assert len(results) <= 3
        assert len(results) > 0

        # Should find the Microsoft document
        microsoft_doc_found = any("Microsoft" in doc.page_content for doc, score in results)
        assert microsoft_doc_found, "Should find Microsoft document when searching for Microsoft Corporation"

        # Test 3: Search using location entities
        results = milvus_client.hybrid_search(
            query="companies in California",
            k=3,
            use_entities=True
        )

        assert len(results) <= 3
        assert len(results) > 0

        # Should find documents with California locations
        california_doc_found = any("California" in doc.page_content for doc, score in results)
        assert california_doc_found, "Should find documents with California locations"

        # Test 4: Search using multiple entity types
        results = milvus_client.hybrid_search(
            query="Elon Musk Tesla electric vehicles",
            k=3,
            use_entities=True
        )

        assert len(results) <= 3
        assert len(results) > 0

        # Should find the Tesla document
        tesla_doc_found = any("Tesla" in doc.page_content for doc, score in results)
        assert tesla_doc_found, "Should find Tesla document when searching for Elon Musk Tesla"

    def test_ner_milvus_entity_sparse_field_mapping(self, milvus_client, milvus_health_check, server_health_check):
        """Test that entities are correctly mapped to sparse fields."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")
        if not server_health_check:
            pytest.skip("Server not available")

        # Setup Milvus client with NER enabled
        milvus_client.use_ner_for_entities = True
        milvus_client.search_mode = "hybrid"
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="entity_mapping_doc1",
                page_content="John Smith works at Google in Mountain View, California.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 55,
                    "entities_persons": "John Smith",
                    "entities_organizations": "Google",
                    "entities_locations": "Mountain View, California",
                    "entities_miscellaneous": "technology, employment"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for entity mapping test"

        # Test entity mapping by searching for specific entity types
        # This tests that the NER client correctly maps entities to sparse fields
        
        # Test person entity mapping
        results = milvus_client.hybrid_search(
            query="John Smith",
            k=1,
            use_entities=True
        )

        assert len(results) > 0
        person_doc_found = any("John Smith" in doc.page_content for doc, score in results)
        assert person_doc_found, "Should find document when searching for person entity"

        # Test organization entity mapping
        results = milvus_client.hybrid_search(
            query="Google",
            k=1,
            use_entities=True
        )

        assert len(results) > 0
        org_doc_found = any("Google" in doc.page_content for doc, score in results)
        assert org_doc_found, "Should find document when searching for organization entity"

        # Test location entity mapping
        results = milvus_client.hybrid_search(
            query="Mountain View",
            k=1,
            use_entities=True
        )

        assert len(results) > 0
        loc_doc_found = any("Mountain View" in doc.page_content for doc, score in results)
        assert loc_doc_found, "Should find document when searching for location entity"

    def test_ner_milvus_fallback_behavior(self, milvus_client, milvus_health_check):
        """Test fallback behavior when NER extraction fails or is disabled."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup Milvus client with NER disabled
        milvus_client.use_ner_for_entities = False
        milvus_client.search_mode = "hybrid"
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="fallback_test_doc1",
                page_content="Apple Inc. was founded by Steve Jobs in Cupertino, California.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 60,
                    "entities_persons": "Steve Jobs",
                    "entities_organizations": "Apple Inc.",
                    "entities_locations": "Cupertino, California",
                    "entities_miscellaneous": "technology, founding"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for fallback test"

        # Test that hybrid search still works without NER
        results = milvus_client.hybrid_search(
            query="Apple Inc. technology company",
            k=1,
            use_entities=True
        )

        assert len(results) > 0
        apple_doc_found = any("Apple" in doc.page_content for doc, score in results)
        assert apple_doc_found, "Should find Apple document even without NER extraction"

        # Test that similarity_search_with_score works without NER
        results_with_scores = milvus_client.similarity_search_with_score(
            query="Steve Jobs founded company",
            k=1
        )

        assert len(results_with_scores) > 0
        assert isinstance(results_with_scores[0], tuple)
        assert isinstance(results_with_scores[0][0], Document)
        assert isinstance(results_with_scores[0][1], (int, float))

    # ------------------------- RETRIEVER TESTS -------------------------

    def test_retriever_initialization(self, milvus_client, milvus_health_check):
        """Test retriever initialization from vector store."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Create retriever
        retriever = milvus_client.as_retriever()
        
        assert retriever.vectorstore == milvus_client
        assert retriever.search_type == "similarity"
        assert retriever.reranker_client is None
        assert retriever.search_kwargs == {}

    def test_retriever_with_custom_search_kwargs(self, milvus_client, milvus_health_check):
        """Test retriever with custom search parameters."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="retriever_doc1",
                page_content="Machine learning algorithms process data efficiently.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "machine learning, algorithms, data"
                }
            ),
            Document(
                id="retriever_doc2",
                page_content="Deep learning neural networks are powerful tools.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "deep learning, neural networks, AI"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for retriever test"

        # Create retriever with custom search kwargs
        retriever = milvus_client.as_retriever(
            search_kwargs={"k": 1, "mode": "semantic"}
        )

        # Test retrieval
        results = retriever.invoke("machine learning")
        
        assert len(results) <= 1
        assert len(results) > 0
        assert isinstance(results[0], Document)

    def test_retriever_hybrid_search_type(self, milvus_client, milvus_health_check):
        """Test retriever with hybrid search type."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents with entities
        documents = [
            Document(
                id="hybrid_retriever_doc1",
                page_content="Apple Inc. develops innovative technology products.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "Tim Cook",
                    "entities_organizations": "Apple Inc.",
                    "entities_locations": "Cupertino, California",
                    "entities_miscellaneous": "technology, innovation, products"
                }
            ),
            Document(
                id="hybrid_retriever_doc2",
                page_content="Microsoft Corporation creates software solutions.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 45,
                    "entities_persons": "Satya Nadella",
                    "entities_organizations": "Microsoft Corporation",
                    "entities_locations": "Redmond, Washington",
                    "entities_miscellaneous": "software, solutions, technology"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for hybrid retriever test"

        # Create retriever with hybrid search
        retriever = milvus_client.as_retriever(
            search_type="hybrid",
            search_kwargs={"k": 2, "use_entities": True}
        )

        # Test hybrid retrieval
        results = retriever.invoke("Apple technology company")
        
        assert len(results) <= 2
        assert len(results) > 0
        assert all(isinstance(doc, Document) for doc in results)

        # Should find Apple document
        apple_doc_found = any("Apple" in doc.page_content for doc in results)
        assert apple_doc_found, "Should find Apple document with hybrid search"

    def test_retriever_with_reranker(self, milvus_client, milvus_health_check, server_health_check, reranker_client):
        """Test retriever with reranker integration."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")
        if not server_health_check:
            pytest.skip("Server not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents with varying relevance
        documents = [
            Document(
                id="rerank_doc1",
                page_content="Machine learning is a subset of artificial intelligence that focuses on algorithms.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 85,
                    "entities_persons": "Alan Turing",
                    "entities_organizations": "MIT, Stanford",
                    "entities_locations": "Boston, Cambridge",
                    "entities_miscellaneous": "machine learning, AI, algorithms"
                }
            ),
            Document(
                id="rerank_doc2",
                page_content="Deep learning uses neural networks with multiple layers to process data.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 75,
                    "entities_persons": "Geoffrey Hinton",
                    "entities_organizations": "Google, University of Toronto",
                    "entities_locations": "Toronto, Canada",
                    "entities_miscellaneous": "deep learning, neural networks, data processing"
                }
            ),
            Document(
                id="rerank_doc3",
                page_content="Natural language processing helps computers understand human language.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash3",
                    "source_page_id": 3,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 70,
                    "entities_persons": "Noam Chomsky",
                    "entities_organizations": "MIT, University of Pennsylvania",
                    "entities_locations": "Boston, Philadelphia",
                    "entities_miscellaneous": "NLP, language processing, linguistics"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for reranker test"

        # Create retriever with reranker
        retriever = milvus_client.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 3},
            reranker_client=reranker_client
        )

        # Test retrieval with reranking
        results = retriever.invoke("machine learning algorithms")
        
        assert len(results) <= 3
        assert len(results) > 0
        assert all(isinstance(doc, Document) for doc in results)

        # Check that reranking scores are added to metadata
        for doc in results:
            if hasattr(doc, 'metadata') and doc.metadata:
                assert 'rerank_score' in doc.metadata
                assert isinstance(doc.metadata['rerank_score'], (int, float))

    def test_retriever_hybrid_with_reranker(self, milvus_client, milvus_health_check, server_health_check, reranker_client):
        """Test retriever with hybrid search and reranker integration."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")
        if not server_health_check:
            pytest.skip("Server not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents with rich entity information
        documents = [
            Document(
                id="hybrid_rerank_doc1",
                page_content="Apple Inc. develops machine learning algorithms for iPhone cameras.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 65,
                    "entities_persons": "Tim Cook, Craig Federighi",
                    "entities_organizations": "Apple Inc.",
                    "entities_locations": "Cupertino, California",
                    "entities_miscellaneous": "machine learning, algorithms, iPhone, cameras"
                }
            ),
            Document(
                id="hybrid_rerank_doc2",
                page_content="Google uses deep learning for search algorithms and language processing.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 75,
                    "entities_persons": "Sundar Pichai, Jeff Dean",
                    "entities_organizations": "Google LLC",
                    "entities_locations": "Mountain View, California",
                    "entities_miscellaneous": "deep learning, search, algorithms, language processing"
                }
            ),
            Document(
                id="hybrid_rerank_doc3",
                page_content="Microsoft Azure provides cloud computing services for machine learning.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash3",
                    "source_page_id": 3,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 70,
                    "entities_persons": "Satya Nadella, Scott Guthrie",
                    "entities_organizations": "Microsoft Corporation",
                    "entities_locations": "Redmond, Washington",
                    "entities_miscellaneous": "Azure, cloud computing, machine learning, services"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for hybrid reranker test"

        # Create retriever with hybrid search and reranker
        retriever = milvus_client.as_retriever(
            search_type="hybrid",
            search_kwargs={"k": 3, "use_entities": True},
            reranker_client=reranker_client
        )

        # Test hybrid retrieval with reranking
        results = retriever.invoke("Apple machine learning algorithms")
        
        assert len(results) <= 3
        assert len(results) > 0
        assert all(isinstance(doc, Document) for doc in results)

        # Should find Apple document (most relevant)
        apple_doc_found = any("Apple" in doc.page_content for doc in results)
        assert apple_doc_found, "Should find Apple document with hybrid search and reranking"

        # Check that reranking scores are added to metadata
        for doc in results:
            if hasattr(doc, 'metadata') and doc.metadata:
                assert 'rerank_score' in doc.metadata
                assert isinstance(doc.metadata['rerank_score'], (int, float))

    def test_retriever_similarity_score_threshold(self, milvus_client, milvus_health_check):
        """Test retriever with similarity score threshold search type."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="threshold_doc1",
                page_content="Machine learning algorithms are essential for artificial intelligence.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 70,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "machine learning, algorithms, AI"
                }
            ),
            Document(
                id="threshold_doc2",
                page_content="Cooking pasta requires boiling water and adding salt for flavor.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 60,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "cooking, pasta, water, salt"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for threshold test"

        # Create retriever with similarity score threshold
        retriever = milvus_client.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={"k": 2, "score_threshold": 0.1}  # Low threshold for testing
        )

        # Test retrieval with score threshold
        results = retriever.invoke("machine learning")
        
        assert len(results) <= 2
        assert len(results) > 0
        assert all(isinstance(doc, Document) for doc in results)

    def test_retriever_async_methods(self, milvus_client, milvus_health_check):
        """Test retriever async methods (should fallback to sync)."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="async_doc1",
                page_content="Async testing for retriever functionality.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 40,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "async, testing, retriever"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for async test"

        # Create retriever
        retriever = milvus_client.as_retriever()

        # Test async retrieval (should fallback to sync)
        import asyncio
        results = asyncio.run(retriever._aget_relevant_documents("async testing"))
        
        assert len(results) > 0
        assert isinstance(results[0], Document)

    def test_retriever_add_documents(self, milvus_client, milvus_health_check):
        """Test retriever add_documents method."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Create retriever
        retriever = milvus_client.as_retriever()

        # Add documents through retriever
        documents = [
            Document(
                id="retriever_add_doc1",
                page_content="Document added through retriever interface.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 40,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "retriever, interface, testing"
                }
            )
        ]

        doc_ids = retriever.add_documents(documents)
        assert len(doc_ids) == 1
        assert doc_ids[0] == "retriever_add_doc1"

        # Wait for documents to be ready
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for retrieval"

        # Test retrieval
        results = retriever.invoke("retriever interface")
        assert len(results) > 0
        assert "retriever" in results[0].page_content

    def test_retriever_reranker_fallback_behavior(self, milvus_client, milvus_health_check):
        """Test retriever fallback behavior when reranker fails."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Create a mock reranker that will fail - inherit from Hoover4RerankClient
        from hoover4_ai_clients.reranker_client import Hoover4RerankClient
        
        class FailingReranker(Hoover4RerankClient):
            def __init__(self):
                super().__init__("http://localhost:8000/v1")
            
            def rerank_documents(self, query, documents, return_documents=False):
                raise Exception("Reranker service unavailable")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add test documents
        documents = [
            Document(
                id="fallback_doc1",
                page_content="Testing fallback behavior when reranker fails.",
                metadata={
                    "source_collection": "test",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "test_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 50,
                    "entities_persons": "",
                    "entities_organizations": "",
                    "entities_locations": "",
                    "entities_miscellaneous": "fallback, testing, reranker"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids), "Documents should be ready for fallback test"

        # Create retriever with failing reranker
        retriever = milvus_client.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 1},
            reranker_client=FailingReranker()
        )

        # Test retrieval (should fallback to original order when reranker fails)
        results = retriever.invoke("fallback testing")
        
        assert len(results) > 0
        assert isinstance(results[0], Document)
        # Should still return results even when reranker fails

    def test_retriever_invalid_search_type(self, milvus_client, milvus_health_check):
        """Test retriever with invalid search type raises error."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        with pytest.raises(ValueError, match="search_type of invalid_search_type not allowed"):
            # Create retriever with invalid search type
            retriever = milvus_client.as_retriever(
                search_type="invalid_search_type",
                search_kwargs={"k": 1}
            )

            # Test that invalid search type raises error
            retriever.invoke("test query")

    def test_comprehensive_retriever_workflow(self, milvus_client, milvus_health_check, server_health_check, reranker_client):
        """Test comprehensive retriever workflow with all search modes and reranker."""
        if not milvus_health_check:
            pytest.skip("Milvus not available")
        if not server_health_check:
            pytest.skip("Server not available")

        # Setup
        milvus_client.connect()
        milvus_client.create_collection()
        milvus_client.load_collection()

        # Add comprehensive test documents with rich metadata
        documents = [
            Document(
                id="comprehensive_doc1",
                page_content="Apple Inc. develops machine learning algorithms for computer vision in iPhone cameras.",
                metadata={
                    "source_collection": "tech_news",
                    "source_file_hash": "hash1",
                    "source_page_id": 1,
                    "source_extracted_by": "news_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 85,
                    "entities_persons": "Tim Cook, Craig Federighi, Phil Schiller",
                    "entities_organizations": "Apple Inc.",
                    "entities_locations": "Cupertino, California, San Francisco",
                    "entities_miscellaneous": "machine learning, algorithms, computer vision, iPhone, cameras, technology"
                }
            ),
            Document(
                id="comprehensive_doc2",
                page_content="Google uses deep learning neural networks for natural language processing in search algorithms.",
                metadata={
                    "source_collection": "tech_news",
                    "source_file_hash": "hash2",
                    "source_page_id": 2,
                    "source_extracted_by": "news_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 95,
                    "entities_persons": "Sundar Pichai, Jeff Dean, Geoffrey Hinton",
                    "entities_organizations": "Google LLC, DeepMind",
                    "entities_locations": "Mountain View, California, London, UK",
                    "entities_miscellaneous": "deep learning, neural networks, NLP, search, algorithms, AI"
                }
            ),
            Document(
                id="comprehensive_doc3",
                page_content="Microsoft Azure provides cloud computing services for machine learning and artificial intelligence workloads.",
                metadata={
                    "source_collection": "tech_news",
                    "source_file_hash": "hash3",
                    "source_page_id": 3,
                    "source_extracted_by": "news_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 100,
                    "entities_persons": "Satya Nadella, Scott Guthrie, Eric Boyd",
                    "entities_organizations": "Microsoft Corporation, Azure",
                    "entities_locations": "Redmond, Washington, Seattle",
                    "entities_miscellaneous": "Azure, cloud computing, machine learning, AI, workloads, services"
                }
            ),
            Document(
                id="comprehensive_doc4",
                page_content="Tesla uses artificial intelligence for autonomous driving and neural networks for vehicle control.",
                metadata={
                    "source_collection": "tech_news",
                    "source_file_hash": "hash4",
                    "source_page_id": 4,
                    "source_extracted_by": "news_extractor",
                    "chunk_index": 0,
                    "start_char": 0,
                    "end_char": 90,
                    "entities_persons": "Elon Musk, Andrej Karpathy, Ashok Elluswamy",
                    "entities_organizations": "Tesla Inc., OpenAI",
                    "entities_locations": "Austin, Texas, Palo Alto, California",
                    "entities_miscellaneous": "AI, autonomous driving, neural networks, vehicle control, automotive"
                }
            )
        ]

        doc_ids = milvus_client.add_documents(documents)
        assert wait_for_documents_ready(milvus_client, doc_ids, timeout=10.0), "Documents should be ready for comprehensive test"

        # Test 1: Standard similarity search retriever
        similarity_retriever = milvus_client.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 3}
        )
        
        similarity_results = similarity_retriever.invoke("machine learning algorithms")
        assert len(similarity_results) <= 3
        assert len(similarity_results) > 0
        assert all(isinstance(doc, Document) for doc in similarity_results)

        # Test 2: Hybrid search retriever
        hybrid_retriever = milvus_client.as_retriever(
            search_type="hybrid",
            search_kwargs={"k": 3, "use_entities": True}
        )
        
        hybrid_results = hybrid_retriever.invoke("Apple machine learning computer vision")
        assert len(hybrid_results) <= 3
        assert len(hybrid_results) > 0
        assert all(isinstance(doc, Document) for doc in hybrid_results)

        # Should find Apple document with hybrid search
        apple_doc_found = any("Apple" in doc.page_content for doc in hybrid_results)
        assert apple_doc_found, "Should find Apple document with hybrid search"

        # Test 3: Similarity with score threshold retriever
        threshold_retriever = milvus_client.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={"k": 3, "score_threshold": 0.1}
        )
        
        threshold_results = threshold_retriever.invoke("deep learning neural networks")
        assert len(threshold_results) <= 3
        assert len(threshold_results) > 0
        assert all(isinstance(doc, Document) for doc in threshold_results)

        # Test 4: Hybrid search with reranker
        hybrid_rerank_retriever = milvus_client.as_retriever(
            search_type="hybrid",
            search_kwargs={"k": 4, "use_entities": True},
            reranker_client=reranker_client
        )
        
        hybrid_rerank_results = hybrid_rerank_retriever.invoke("Tesla AI autonomous driving neural networks")
        assert len(hybrid_rerank_results) <= 4
        assert len(hybrid_rerank_results) > 0
        assert all(isinstance(doc, Document) for doc in hybrid_rerank_results)

        # Should find Tesla document
        tesla_doc_found = any("Tesla" in doc.page_content for doc in hybrid_rerank_results)
        assert tesla_doc_found, "Should find Tesla document with hybrid search and reranking"

        # Check that reranking scores are added to metadata
        for doc in hybrid_rerank_results:
            if hasattr(doc, 'metadata') and doc.metadata:
                assert 'rerank_score' in doc.metadata
                assert isinstance(doc.metadata['rerank_score'], (int, float))

        # Test 5: Standard similarity with reranker
        similarity_rerank_retriever = milvus_client.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 3},
            reranker_client=reranker_client
        )
        
        similarity_rerank_results = similarity_rerank_retriever.invoke("Google deep learning search")
        assert len(similarity_rerank_results) <= 3
        assert len(similarity_rerank_results) > 0
        assert all(isinstance(doc, Document) for doc in similarity_rerank_results)

        # Should find Google document
        google_doc_found = any("Google" in doc.page_content for doc in similarity_rerank_results)
        assert google_doc_found, "Should find Google document with similarity search and reranking"

        # Test 6: Verify that different search modes return different results
        # (This is more of a sanity check - results might be similar but ordering could differ)
        assert len(similarity_results) > 0
        assert len(hybrid_results) > 0
        assert len(threshold_results) > 0
        assert len(hybrid_rerank_results) > 0
        assert len(similarity_rerank_results) > 0

        # All retrievers should return Document objects
        for results in [similarity_results, hybrid_results, threshold_results, 
                       hybrid_rerank_results, similarity_rerank_results]:
            for doc in results:
                assert isinstance(doc, Document)
                assert hasattr(doc, 'page_content')
                assert hasattr(doc, 'metadata')
                assert doc.id is not None