"""Tests for TextContentIterator."""

import os
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from hoover4_rag import TextContentIterator, TextContentEntry


class TestTextContentEntry:
    """Test TextContentEntry data class."""
    
    def test_text_content_entry_creation(self):
        """Test creating a TextContentEntry."""
        entry = TextContentEntry(
            collection_dataset="test_dataset",
            file_hash="abc123",
            extracted_by="test_extractor",
            page_id=1,
            text="Sample text content"
        )
        
        assert entry.collection_dataset == "test_dataset"
        assert entry.file_hash == "abc123"
        assert entry.extracted_by == "test_extractor"
        assert entry.page_id == 1
        assert entry.text == "Sample text content"
    
    def test_to_dict(self):
        """Test converting TextContentEntry to dictionary."""
        entry = TextContentEntry(
            collection_dataset="test_dataset",
            file_hash="abc123",
            extracted_by="test_extractor",
            page_id=1,
            text="Sample text content"
        )
        
        expected = {
            'collection_dataset': "test_dataset",
            'file_hash': "abc123",
            'extracted_by': "test_extractor",
            'page_id': 1,
            'text': "Sample text content"
        }
        
        assert entry.to_dict() == expected


class TestTextContentIterator:
    """Test TextContentIterator class."""
    
    @pytest.fixture
    def temp_resume_file(self):
        """Create a temporary resume file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            yield f.name
        # Cleanup
        if os.path.exists(f.name):
            os.unlink(f.name)
    
    @pytest.fixture
    def mock_clickhouse_client(self):
        """Mock clickhouse client."""
        with patch('hoover4_rag.text_content_iterator.clickhouse_connect.get_client') as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            yield mock_client
    
    def test_init_default_values(self, temp_resume_file):
        """Test iterator initialization with default values."""
        iterator = TextContentIterator(resume_file=temp_resume_file)
        
        assert iterator.batch_size == 100
        assert iterator.resume_file == Path(temp_resume_file)
        assert iterator.collection_dataset is None
        assert iterator.extracted_by_filter is None
        assert iterator.min_text_length == 10
        assert iterator.current_offset == 0
        assert iterator.total_processed == 0
        assert iterator.connected is False
    
    def test_init_custom_values(self, temp_resume_file):
        """Test iterator initialization with custom values."""
        iterator = TextContentIterator(
            batch_size=50,
            resume_file=temp_resume_file,
            collection_dataset="test_dataset",
            extracted_by_filter="test_extractor",
            min_text_length=25
        )
        
        assert iterator.batch_size == 50
        assert iterator.collection_dataset == "test_dataset"
        assert iterator.extracted_by_filter == "test_extractor"
        assert iterator.min_text_length == 25
    
    def test_load_progress_no_file(self):
        """Test loading progress when no resume file exists."""
        # Use a file that definitely doesn't exist
        non_existent_file = "definitely_does_not_exist_12345.json"
        
        iterator = TextContentIterator(resume_file=non_existent_file)
        
        assert iterator.current_offset == 0
        assert iterator.total_processed == 0
    
    def test_load_progress_with_file(self, temp_resume_file):
        """Test loading progress from existing resume file."""
        # Create a resume file with progress
        progress_data = {
            'current_offset': 150,
            'total_processed': 150,
            'last_updated': 1234567890,
            'collection_dataset': 'test_dataset',
            'extracted_by_filter': 'test_extractor'
        }
        
        with open(temp_resume_file, 'w') as f:
            json.dump(progress_data, f)
        
        iterator = TextContentIterator(resume_file=temp_resume_file)
        
        assert iterator.current_offset == 150
        assert iterator.total_processed == 150
    
    def test_save_progress(self, temp_resume_file):
        """Test saving progress to file."""
        iterator = TextContentIterator(
            resume_file=temp_resume_file,
            collection_dataset="test_dataset"
        )
        iterator.current_offset = 100
        iterator.total_processed = 100
        
        iterator._save_progress()
        
        # Verify file was created and contains correct data
        assert os.path.exists(temp_resume_file)
        
        with open(temp_resume_file, 'r') as f:
            saved_data = json.load(f)
        
        assert saved_data['current_offset'] == 100
        assert saved_data['total_processed'] == 100
        assert saved_data['collection_dataset'] == "test_dataset"
        assert 'last_updated' in saved_data
    
    def test_build_query_basic(self, temp_resume_file):
        """Test building basic query without filters."""
        iterator = TextContentIterator(
            batch_size=50,
            resume_file=temp_resume_file,
            min_text_length=20
        )
        iterator.current_offset = 100
        
        query = iterator._build_query()
        
        assert "FROM text_content" in query
        assert "WHERE length(text) >= 20" in query
        assert "ORDER BY collection_dataset, file_hash, page_id" in query
        assert "LIMIT 50 OFFSET 100" in query
        assert "AND collection_dataset" not in query
        assert "AND extracted_by" not in query
    
    def test_build_query_with_filters(self, temp_resume_file):
        """Test building query with filters."""
        iterator = TextContentIterator(
            batch_size=25,
            resume_file=temp_resume_file,
            collection_dataset="test_dataset",
            extracted_by_filter="test_extractor",
            min_text_length=15
        )
        iterator.current_offset = 50
        
        query = iterator._build_query()
        
        assert "WHERE length(text) >= 15" in query
        assert "AND collection_dataset = 'test_dataset'" in query
        assert "AND extracted_by = 'test_extractor'" in query
        assert "LIMIT 25 OFFSET 50" in query
    
    @patch.dict(os.environ, {
        'CLICKHOUSE_HOST': 'test_host',
        'CLICKHOUSE_PORT': '9000',
        'CLICKHOUSE_USERNAME': 'test_user',
        'CLICKHOUSE_PASSWORD': 'test_pass',
        'CLICKHOUSE_DATABASE': 'test_db'
    })
    def test_connect_success(self, mock_clickhouse_client, temp_resume_file):
        """Test successful connection to ClickHouse."""
        iterator = TextContentIterator(resume_file=temp_resume_file)
        
        result = iterator.connect()
        
        assert result is True
        assert iterator.connected is True
        assert iterator.start_time is not None
        mock_clickhouse_client.close.assert_not_called()
    
    def test_connect_failure(self, temp_resume_file):
        """Test failed connection to ClickHouse."""
        with patch('hoover4_rag.text_content_iterator.clickhouse_connect.get_client') as mock_get_client:
            mock_get_client.side_effect = Exception("Connection failed")
            
            iterator = TextContentIterator(resume_file=temp_resume_file)
            
            result = iterator.connect()
            
            assert result is False
            assert iterator.connected is False
    
    def test_disconnect(self, mock_clickhouse_client, temp_resume_file):
        """Test disconnecting from ClickHouse."""
        iterator = TextContentIterator(resume_file=temp_resume_file)
        iterator.client = mock_clickhouse_client
        iterator.connected = True
        
        iterator.disconnect()
        
        assert iterator.connected is False
        assert iterator.client is None
        mock_clickhouse_client.close.assert_called_once()
    
    def test_get_total_count(self, mock_clickhouse_client, temp_resume_file):
        """Test getting total count of records."""
        # Mock query result
        mock_result = Mock()
        mock_result.result_rows = [[1000]]
        mock_clickhouse_client.query.return_value = mock_result
        
        iterator = TextContentIterator(
            resume_file=temp_resume_file,
            collection_dataset="test_dataset"
        )
        iterator.client = mock_clickhouse_client
        iterator.connected = True
        
        count = iterator.get_total_count()
        
        assert count == 1000
        mock_clickhouse_client.query.assert_called_once()
        
        # Verify the query contains the filter
        query_arg = mock_clickhouse_client.query.call_args[0][0]
        assert "AND collection_dataset = 'test_dataset'" in query_arg
    
    def test_get_total_count_not_connected(self, temp_resume_file):
        """Test getting total count when not connected."""
        iterator = TextContentIterator(resume_file=temp_resume_file)
        
        with pytest.raises(RuntimeError, match="Not connected to ClickHouse"):
            iterator.get_total_count()
    
    def test_reset_progress(self):
        """Test resetting progress."""
        # Use a temporary file that we can control
        test_file = "test_reset_progress_temp.json"
        
        try:
            # Create a resume file
            with open(test_file, 'w') as f:
                json.dump({'current_offset': 100, 'total_processed': 100}, f)
            
            iterator = TextContentIterator(resume_file=test_file)
            iterator.current_offset = 100
            iterator.total_processed = 100
            
            iterator.reset_progress()
            
            assert iterator.current_offset == 0
            assert iterator.total_processed == 0
            assert not os.path.exists(test_file)
        
        finally:
            # Cleanup in case test fails
            if os.path.exists(test_file):
                try:
                    os.unlink(test_file)
                except:
                    pass
    
    def test_get_progress_stats(self, temp_resume_file):
        """Test getting progress statistics."""
        iterator = TextContentIterator(batch_size=50, resume_file=temp_resume_file)
        iterator.current_offset = 150
        iterator.total_processed = 150
        iterator.start_time = 1000.0
        
        with patch('time.time', return_value=1010.0):  # 10 seconds elapsed
            stats = iterator.get_progress_stats()
        
        assert stats['total_processed'] == 150
        assert stats['current_offset'] == 150
        assert stats['elapsed_time'] == 10.0
        assert stats['processing_rate'] == 15.0  # 150 records / 10 seconds
        assert stats['batch_size'] == 50
    
    def test_context_manager(self, mock_clickhouse_client, temp_resume_file):
        """Test using iterator as context manager."""
        iterator = TextContentIterator(resume_file=temp_resume_file)
        
        with patch.object(iterator, 'connect', return_value=True) as mock_connect:
            with patch.object(iterator, 'disconnect') as mock_disconnect:
                with iterator as ctx:
                    assert ctx is iterator
                
                mock_connect.assert_called_once()
                mock_disconnect.assert_called_once()
    
    def test_context_manager_connection_failure(self, temp_resume_file):
        """Test context manager when connection fails."""
        iterator = TextContentIterator(resume_file=temp_resume_file)
        
        with patch.object(iterator, 'connect', return_value=False):
            with pytest.raises(RuntimeError, match="Failed to connect to ClickHouse"):
                with iterator:
                    pass
    
    def test_iteration(self, mock_clickhouse_client, temp_resume_file):
        """Test iterator functionality."""
        # Mock query results for two batches
        batch1_result = Mock()
        batch1_result.result_rows = [
            ['dataset1', 'hash1', 'extractor1', 0, 'text content 1'],
            ['dataset1', 'hash2', 'extractor1', 0, 'text content 2']
        ]
        
        batch2_result = Mock()
        batch2_result.result_rows = [
            ['dataset1', 'hash3', 'extractor1', 0, 'text content 3']
        ]
        
        # Empty result to end iteration
        empty_result = Mock()
        empty_result.result_rows = []
        
        mock_clickhouse_client.query.side_effect = [batch1_result, batch2_result, empty_result]
        
        iterator = TextContentIterator(batch_size=2, resume_file=temp_resume_file)
        iterator.client = mock_clickhouse_client
        iterator.connected = True
        
        batches = list(iterator)
        
        assert len(batches) == 2
        
        # Check first batch
        assert len(batches[0]) == 2
        assert batches[0][0].collection_dataset == 'dataset1'
        assert batches[0][0].file_hash == 'hash1'
        assert batches[0][0].text == 'text content 1'
        
        # Check second batch
        assert len(batches[1]) == 1
        assert batches[1][0].file_hash == 'hash3'
        
        # Check progress tracking
        assert iterator.current_offset == 3  # 2 + 1
        assert iterator.total_processed == 3
    
    def test_iteration_not_connected(self, temp_resume_file):
        """Test iteration when not connected."""
        iterator = TextContentIterator(resume_file=temp_resume_file)
        
        with pytest.raises(RuntimeError, match="Not connected to ClickHouse"):
            list(iterator)


class TestTextContentIteratorIntegration:
    """Integration tests for TextContentIterator (requires actual ClickHouse connection)."""
    
    @pytest.fixture(autouse=True)
    def setup_environment(self):
        """Setup environment variables for testing."""
        # Only run if ClickHouse is available
        if not os.getenv('CLICKHOUSE_HOST'):
            pytest.skip("ClickHouse connection not available")
    
    def test_real_connection(self):
        """Test connecting to real ClickHouse instance."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            resume_file = f.name
        
        try:
            iterator = TextContentIterator(
                batch_size=10,
                resume_file=resume_file
            )
            
            # Test connection
            assert iterator.connect() is True
            assert iterator.connected is True
            
            # Test getting count (should work even if no data)
            count = iterator.get_total_count()
            assert isinstance(count, int)
            assert count >= 0
            
            # Test basic iteration (just first batch)
            batch_count = 0
            for batch in iterator:
                assert isinstance(batch, list)
                if batch:
                    assert isinstance(batch[0], TextContentEntry)
                batch_count += 1
                if batch_count >= 1:  # Only test first batch
                    break
            
            iterator.disconnect()
            assert iterator.connected is False
            
        finally:
            # Cleanup
            if os.path.exists(resume_file):
                os.unlink(resume_file)


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
