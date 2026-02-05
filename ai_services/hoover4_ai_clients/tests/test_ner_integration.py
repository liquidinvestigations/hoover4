"""Integration tests for Hoover4NERClient against live server."""

import pytest


@pytest.mark.integration
@pytest.mark.ner
class TestNERIntegration:
    """Integration tests for NER client with live server."""

    def test_ner_client_initialization(self, ner_client):
        """Test NER client initialization."""
        assert ner_client.base_url is not None
        assert ner_client.session is not None

    def test_extract_entities_single_text(self, ner_client, server_health_check):
        """Test extracting entities from a single text."""
        if not server_health_check:
            pytest.skip("Server not available")

        text = "Apple Inc. was founded by Steve Jobs in Cupertino, California in 1976."
        entities = ner_client.extract_entities([text])

        assert isinstance(entities, list)
        assert len(entities) == 1

        text_entities = entities[0]
        assert isinstance(text_entities, dict)

        # Check that we have the expected entity type keys
        expected_keys = {"PER", "ORG", "LOC", "MISC"}
        assert set(text_entities.keys()) == expected_keys

        # Check that entities are lists
        for entity_list in text_entities.values():
            assert isinstance(entity_list, list)
            for entity in entity_list:
                assert isinstance(entity, str)

        # Verify specific entities were extracted
        assert "Apple Inc." in text_entities["ORG"]
        assert "Steve Jobs" in text_entities["PER"]
        assert "Cupertino" in text_entities["LOC"] or "California" in text_entities["LOC"]

    def test_extract_entities_multiple_texts(self, ner_client, server_health_check):
        """Test extracting entities from multiple texts."""
        if not server_health_check:
            pytest.skip("Server not available")

        texts = [
            "Apple Inc. was founded by Steve Jobs in Cupertino, California.",
            "Microsoft Corporation is headquartered in Redmond, Washington.",
            "Google LLC is based in Mountain View, California.",
            "Tesla Inc. was founded by Elon Musk and is located in Austin, Texas."
        ]

        entities = ner_client.extract_entities(texts)

        assert isinstance(entities, list)
        assert len(entities) == len(texts)

        for i, text_entities in enumerate(entities):
            assert isinstance(text_entities, dict)
            expected_keys = {"PER", "ORG", "LOC", "MISC"}
            assert set(text_entities.keys()) == expected_keys

            # Check that we extracted some entities for each text
            total_entities = sum(len(entity_list) for entity_list in text_entities.values())
            assert total_entities > 0, f"No entities extracted for text {i}: {texts[i]}"

    def test_extract_entities_with_specific_types(self, ner_client, server_health_check):
        """Test extracting only specific entity types."""
        if not server_health_check:
            pytest.skip("Server not available")

        text = "Apple Inc. was founded by Steve Jobs in Cupertino, California in 1976."

        # Test extracting only organizations
        org_entities = ner_client.extract_entities([text], entity_types=["ORG"])
        assert len(org_entities) == 1
        assert len(org_entities[0]["ORG"]) > 0
        assert "Apple Inc." in org_entities[0]["ORG"]

        # Test extracting only persons
        per_entities = ner_client.extract_entities([text], entity_types=["PER"])
        assert len(per_entities) == 1
        assert len(per_entities[0]["PER"]) > 0
        assert "Steve Jobs" in per_entities[0]["PER"]

        # Test extracting only locations
        loc_entities = ner_client.extract_entities([text], entity_types=["LOC"])
        assert len(loc_entities) == 1
        assert len(loc_entities[0]["LOC"]) > 0

    def test_extract_entities_empty_text(self, ner_client, server_health_check):
        """Test extracting entities from empty text."""
        if not server_health_check:
            pytest.skip("Server not available")

        entities = ner_client.extract_entities([""])

        assert len(entities) == 1
        text_entities = entities[0]

        # Should have all entity type keys but empty lists
        expected_keys = {"PER", "ORG", "LOC", "MISC"}
        assert set(text_entities.keys()) == expected_keys

        for entity_list in text_entities.values():
            assert entity_list == []

    def test_extract_entities_no_entities(self, ner_client, server_health_check):
        """Test extracting entities from text with no named entities."""
        if not server_health_check:
            pytest.skip("Server not available")

        text = "This is just a regular sentence with no named entities."
        entities = ner_client.extract_entities([text])

        assert len(entities) == 1
        text_entities = entities[0]

        # Should have all entity type keys
        expected_keys = {"PER", "ORG", "LOC", "MISC"}
        assert set(text_entities.keys()) == expected_keys

        # All entity lists should be empty
        for entity_list in text_entities.values():
            assert entity_list == []

    def test_extract_entities_large_text(self, ner_client, server_health_check):
        """Test extracting entities from a large text."""
        if not server_health_check:
            pytest.skip("Server not available")

        # Create a larger text with multiple entities
        large_text = """
        Apple Inc. is an American multinational technology company headquartered in Cupertino, California.
        The company was founded by Steve Jobs, Steve Wozniak, and Ronald Wayne in April 1976.
        Apple is known for its consumer electronics, software, and online services.
        The company's hardware products include the iPhone smartphone, iPad tablet computer, Mac personal computer,
        iPod portable media player, Apple Watch smartwatch, Apple TV digital media player, and HomePod smart speaker.
        Apple's software includes the macOS and iOS operating systems, the iTunes media player, the Safari web browser,
        and the iLife and iWork creativity and productivity suites.
        """

        entities = ner_client.extract_entities([large_text])

        assert len(entities) == 1
        text_entities = entities[0]

        # Should extract multiple entities
        total_entities = sum(len(entity_list) for entity_list in text_entities.values())
        assert total_entities > 5  # Should extract several entities

        # Should have found Apple Inc. as an organization
        assert "Apple Inc." in text_entities["ORG"]

        # Should have found some persons
        assert len(text_entities["PER"]) > 0

    def test_extract_entities_multilingual(self, ner_client, server_health_check):
        """Test extracting entities from multilingual text."""
        if not server_health_check:
            pytest.skip("Server not available")

        multilingual_texts = [
            "Apple Inc. was founded by Steve Jobs in Cupertino, California.",  # English
            "Microsoft Corporation est basée à Redmond, Washington.",  # French
            "Google LLC tiene su sede en Mountain View, California.",  # Spanish
        ]

        entities = ner_client.extract_entities(multilingual_texts)

        assert len(entities) == len(multilingual_texts)

        for i, text_entities in enumerate(entities):
            assert isinstance(text_entities, dict)
            expected_keys = {"PER", "ORG", "LOC", "MISC"}
            assert set(text_entities.keys()) == expected_keys

            # Should extract some entities even from non-English text
            total_entities = sum(len(entity_list) for entity_list in text_entities.values())
            assert total_entities > 0, f"No entities extracted for multilingual text {i}"

    def test_extract_entities_consistency(self, ner_client, server_health_check):
        """Test that same input produces consistent entity extraction."""
        if not server_health_check:
            pytest.skip("Server not available")

        text = "Apple Inc. was founded by Steve Jobs in Cupertino, California."

        # Extract entities twice
        entities1 = ner_client.extract_entities([text])
        entities2 = ner_client.extract_entities([text])

        # Should be identical
        assert entities1 == entities2

    def test_extract_entities_special_characters(self, ner_client, server_health_check):
        """Test extracting entities from text with special characters."""
        if not server_health_check:
            pytest.skip("Server not available")

        texts_with_special_chars = [
            "AT&T Inc. is a telecommunications company.",
            "3M Company is based in St. Paul, Minnesota.",
            "Johnson & Johnson is a pharmaceutical company.",
            "Coca-Cola Company is headquartered in Atlanta, Georgia."
        ]

        entities = ner_client.extract_entities(texts_with_special_chars)

        assert len(entities) == len(texts_with_special_chars)

        for i, text_entities in enumerate(entities):
            assert isinstance(text_entities, dict)
            expected_keys = {"PER", "ORG", "LOC", "MISC"}
            assert set(text_entities.keys()) == expected_keys

            # Should extract entities despite special characters
            total_entities = sum(len(entity_list) for entity_list in text_entities.values())
            assert total_entities > 0, f"No entities extracted for text with special chars {i}"

    def test_extract_entities_batch_performance(self, ner_client, server_health_check):
        """Test batch processing performance."""
        if not server_health_check:
            pytest.skip("Server not available")

        import time

        # Create a batch of texts
        batch_size = 20
        texts = [
            f"Company {i} was founded by Person {i} in City {i}, State {i}."
            for i in range(batch_size)
        ]

        start_time = time.time()
        entities = ner_client.extract_entities(texts)
        end_time = time.time()

        processing_time = end_time - start_time

        assert len(entities) == batch_size
        assert processing_time < 30.0  # Should complete within 30 seconds

        # Calculate throughput
        throughput = batch_size / processing_time
        print(f"NER batch processing throughput: {throughput:.2f} texts/sec")

        # Should be reasonably fast
        assert throughput > 0.5  # At least 0.5 texts per second
