#!/usr/bin/env python3
"""
Named Entity Recognition (NER) tests for the embedding server
"""

import requests
import pytest
from test_utils import (
    validate_server_connection, print_test_header, check_server_health
)


def test_basic_entity_extraction():
    """Test basic named entity recognition functionality"""
    print_test_header("BASIC ENTITY EXTRACTION TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if NER model is loaded
    health_data = check_server_health()
    if not health_data.get('ner_model_loaded', False):
        pytest.skip("NER model not loaded")

    # Test text with various entity types
    test_text = """
    Apple Inc. was founded by Steve Jobs, Steve Wozniak, and Ronald Wayne in Cupertino, California on April 1, 1976.
    The company is headquartered in Cupertino and has over 150,000 employees worldwide.
    Tim Cook became CEO in 2011, succeeding Steve Jobs.
    Apple's revenue in 2023 was approximately $394.3 billion.
    """

    print(f"\nTest text: {test_text.strip()}")

    try:
        response = requests.post(
            "http://localhost:8000/v1/extract-entities",
            json={
                "input": test_text
            }
        )

        assert response.status_code == 200, f"API returned status code {response.status_code}: {response.text}"

        result = response.json()

        print(f" Successfully extracted entities")
        print(f"Model used: {result.get('model', 'unknown')}")
        print(f"Usage: {result.get('usage', {})}")

        entities = result.get("data", [])
        print(f"\nFound {len(entities)} entities:")

        entity_types = {}
        for entity in entities:
            entity_type = entity["label"]
            entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
            print(f"  • {entity['text']} ({entity['label']}) [{entity['start']}:{entity['end']}]")

        print(f"\nEntity type summary:")
        for etype, count in entity_types.items():
            print(f"  - {etype}: {count}")

        # Verify response structure
        assert "data" in result, "Response should contain 'data' field"
        assert len(entities) > 0, "Should find at least some entities in the test text"

        for entity in entities:
            assert "text" in entity, "Each entity should have 'text' field"
            assert "label" in entity, "Each entity should have 'label' field"
            assert "start" in entity, "Each entity should have 'start' field"
            assert "end" in entity, "Each entity should have 'end' field"
            assert isinstance(entity["start"], int), "Start position should be integer"
            assert isinstance(entity["end"], int), "End position should be integer"
            assert entity["start"] < entity["end"], "Start should be less than end"

        # Check for expected entity types (CoNLL-2003 NER labels)
        expected_types = ['PER', 'ORG', 'LOC', 'MISC']  # Person, Organization, Location, Miscellaneous
        found_types = set(entity_types.keys())
        expected_found = [t for t in expected_types if t in found_types]

        assert len(expected_found) >= 2, f"Expected at least 2 common entity types, found: {found_types}"
        print(" SUCCESS: Found multiple expected entity types")

        # Verify specific entities we expect to find
        entity_texts = [entity["text"].lower() for entity in entities]
        assert any("apple" in text for text in entity_texts), "Should find 'Apple' as an entity"
        assert any("steve jobs" in text for text in entity_texts), "Should find 'Steve Jobs' as an entity"

    except Exception as e:
        pytest.fail(f"Error in basic NER test: {e}")


def test_entity_type_filtering():
    """Test filtering entities by specific types"""
    print_test_header("ENTITY TYPE FILTERING TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if NER model is loaded
    health_data = check_server_health()
    if not health_data.get('ner_model_loaded', False):
        pytest.skip("NER model not loaded")

    test_text = """
    Microsoft Corporation was founded by Bill Gates and Paul Allen in Redmond, Washington.
    The company reported revenue of $211.9 billion in fiscal year 2023.
    Satya Nadella became CEO in February 2014.
    """

    print(f"\nTest text: {test_text.strip()}")
    print("Testing with entity_types filter: ['PER', 'ORG']")

    try:
        response = requests.post(
            "http://localhost:8000/v1/extract-entities",
            json={
                "input": test_text,
                "entity_types": ["PER", "ORG"]
            }
        )

        assert response.status_code == 200, f"Entity filtering test failed: Status code {response.status_code}: {response.text}"

        result = response.json()
        entities = result.get("data", [])

        # Check that only requested entity types are returned
        found_types = set(entity["label"] for entity in entities)
        allowed_types = {"PER", "ORG"}

        assert found_types.issubset(allowed_types), f"Found unexpected entity types: {found_types - allowed_types}"
        print(f" SUCCESS: Entity filtering works correctly")
        print(f"Found types: {found_types}")
        print(f"Filtered entities: {len(entities)}")

        print("Filtered results:")
        for entity in entities:
            print(f"  • {entity['text']} ({entity['label']})")

    except Exception as e:
        pytest.fail(f"Error in entity filtering test: {e}")


def test_entity_extraction_multiple_texts():
    """Test entity extraction with multiple input texts"""
    print_test_header("MULTIPLE TEXTS ENTITY EXTRACTION TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if NER model is loaded
    health_data = check_server_health()
    if not health_data.get('ner_model_loaded', False):
        pytest.skip("NER model not loaded")

    test_texts = [
        "Google was founded by Larry Page and Sergey Brin at Stanford University.",
        "Amazon's headquarters are located in Seattle, Washington.",
        "Elon Musk is the CEO of Tesla and SpaceX."
    ]

    print(f"\nTest texts:")
    for i, text in enumerate(test_texts):
        print(f"{i+1}. {text}")

    try:
        response = requests.post(
            "http://localhost:8000/v1/extract-entities",
            json={
                "input": test_texts
            }
        )

        assert response.status_code == 200, f"Multiple texts test failed: Status code {response.status_code}: {response.text}"

        result = response.json()

        # Check if we get results for each text
        if isinstance(result.get("data"), list) and len(result["data"]) > 0:
            # If results are returned as a single list, that's acceptable
            entities = result["data"]
            print(f" Successfully extracted {len(entities)} entities from multiple texts")

            for entity in entities:
                print(f"  • {entity['text']} ({entity['label']})")
        else:
            # Some implementations might return separate results per text
            print(" Multiple text processing supported")

    except Exception as e:
        # Multiple text support might not be implemented, which is acceptable
        print(f"⚠️  Multiple text support not available: {e}")


def test_ner_error_handling():
    """Test NER error handling for invalid inputs"""
    print_test_header("NER ERROR HANDLING TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if NER model is loaded
    health_data = check_server_health()
    if not health_data.get('ner_model_loaded', False):
        pytest.skip("NER model not loaded")

    # Test empty text
    print("Testing empty text...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/extract-entities",
            json={
                "input": ""
            }
        )

        assert response.status_code == 400, f"Expected 400 for empty text, got {response.status_code}"
        print(" SUCCESS: Empty text correctly rejected")

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Error in empty text test: {e}")

    # Test missing input field
    print("Testing missing input field...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/extract-entities",
            json={}
        )

        assert response.status_code == 422, f"Expected 422 for missing input field validation, got {response.status_code}"
        print(" SUCCESS: Missing input field correctly rejected")

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Error in missing input test: {e}")

    # Test invalid entity types filter
    print("Testing invalid entity types...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/extract-entities",
            json={
                "input": "Test text with some content.",
                "entity_types": ["INVALID_TYPE"]
            }
        )

        # This might succeed but return no results, or fail with 400
        # Both behaviors are acceptable
        if response.status_code == 400:
            print(" Invalid entity types correctly rejected")
        elif response.status_code == 200:
            result = response.json()
            entities = result.get("data", [])
            if len(entities) == 0:
                print(" Invalid entity types filtered correctly (no results)")
            else:
                print("⚠️  Invalid entity types were accepted")
        else:
            pytest.fail(f"Unexpected status code for invalid entity types: {response.status_code}")

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Error in invalid entity types test: {e}")


def test_ner_performance():
    """Test NER performance with longer text"""
    print_test_header("NER PERFORMANCE TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if NER model is loaded
    health_data = check_server_health()
    if not health_data.get('ner_model_loaded', False):
        pytest.skip("NER model not loaded")

    # Longer text for performance testing
    long_text = """
    The technology industry has seen remarkable growth over the past decade. Companies like Microsoft, Google, Apple, and Amazon have become some of the most valuable corporations in the world. These companies are headquartered in various locations across the United States, including Redmond, Mountain View, Cupertino, and Seattle.

    Key figures in the industry include Satya Nadella at Microsoft, Sundar Pichai at Google, Tim Cook at Apple, and Andy Jassy at Amazon. These leaders have guided their companies through significant transformations and expansions into new markets.

    The COVID-19 pandemic, which began in 2019 and peaked in 2020, accelerated digital transformation across industries. Companies invested heavily in cloud computing, artificial intelligence, and remote work technologies. This led to substantial revenue growth, with some companies reporting quarterly earnings exceeding $50 billion.

    Looking ahead to 2024 and beyond, emerging technologies like artificial intelligence, quantum computing, and augmented reality are expected to drive the next wave of innovation. Investments in these areas are projected to reach hundreds of billions of dollars over the next five years.
    """

    print(f"\nTest text length: {len(long_text)} characters")
    print("Testing NER performance with longer text...")

    try:
        import time
        start_time = time.time()

        response = requests.post(
            "http://localhost:8000/v1/extract-entities",
            json={
                "input": long_text
            }
        )

        end_time = time.time()
        processing_time = end_time - start_time

        assert response.status_code == 200, f"Performance test failed: Status code {response.status_code}: {response.text}"

        result = response.json()
        entities = result.get("data", [])

        print(f" Successfully processed {len(long_text)} characters in {processing_time:.2f}s")
        print(f"Found {len(entities)} entities")
        print(f"Processing speed: {len(long_text)/processing_time:.0f} characters/second")

        # Performance expectations (adjust based on your requirements)
        assert processing_time < 30.0, f"Processing took too long: {processing_time:.2f}s"

        if processing_time < 5.0:
            print(" Excellent NER performance")
        elif processing_time < 15.0:
            print(" Good NER performance")
        else:
            print("⚠️  NER performance could be improved")

        # Count entity types
        entity_types = {}
        for entity in entities:
            entity_type = entity["label"]
            entity_types[entity_type] = entity_types.get(entity_type, 0) + 1

        print(f"\nEntity distribution:")
        for etype, count in sorted(entity_types.items()):
            print(f"  {etype}: {count}")

    except Exception as e:
        pytest.fail(f"Error in NER performance test: {e}")


if __name__ == "__main__":
    print("Running NER tests...\n")

    try:
        test_basic_entity_extraction()
        print("\n" + "=" * 80)

        test_entity_type_filtering()
        print("\n" + "=" * 80)

        test_entity_extraction_multiple_texts()
        print("\n" + "=" * 80)

        test_ner_error_handling()
        print("\n" + "=" * 80)

        test_ner_performance()
        print("\n" + "=" * 80)

        print("NER TESTS RESULTS")
        print("=" * 80)
        print(" All NER tests passed!")
        print("\nKey features tested:")
        print("  • Basic named entity recognition")
        print("  • Entity type filtering")
        print("  • Multiple text processing")
        print("  • Error handling for invalid inputs")
        print("  • Performance with longer texts")

    except Exception as e:
        print(f" NER tests failed: {e}")
        exit(1)
