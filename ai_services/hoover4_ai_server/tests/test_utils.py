#!/usr/bin/env python3
"""
Shared utility functions for embedding server tests
"""

import requests
import math
import statistics
from typing import List, Dict


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two vectors using pure Python"""
    if len(vec1) != len(vec2):
        raise ValueError("Vectors must have the same length")
    
    # Compute dot product
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    
    # Compute magnitudes (norms)
    magnitude_a = math.sqrt(sum(a * a for a in vec1))
    magnitude_b = math.sqrt(sum(b * b for b in vec2))
    
    # Avoid division by zero
    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0
    
    return dot_product / (magnitude_a * magnitude_b)


def euclidean_distance(vec1: List[float], vec2: List[float]) -> float:
    """Compute Euclidean distance between two vectors using pure Python"""
    if len(vec1) != len(vec2):
        raise ValueError("Vectors must have the same length")
    
    # Compute sum of squared differences
    squared_diff_sum = sum((a - b) ** 2 for a, b in zip(vec1, vec2))
    
    # Return square root
    return math.sqrt(squared_diff_sum)


def check_server_health(base_url: str = "http://localhost:8000") -> Dict:
    """Check if the embedding server is healthy"""
    try:
        health_response = requests.get(f"{base_url}/health")
        if health_response.status_code == 200:
            return health_response.json()
        else:
            return {"status": "unhealthy", "error": f"Status code: {health_response.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"status": "unreachable", "error": "Cannot connect to server"}


def print_test_header(title: str, width: int = 60):
    """Print a formatted test section header"""
    print("=" * width)
    print(title)
    print("=" * width)


def print_test_subheader(title: str, width: int = 50):
    """Print a formatted test subsection header"""
    print("=" * width)
    print(title)
    print("=" * width)


def print_server_status(health_data: Dict):
    """Print formatted server status information"""
    print(f"\nServer status: {health_data.get('status', 'unknown')}")
    if health_data.get('model_loaded'):
        print(f"Embedding model loaded: {health_data.get('embedding_model_loaded', False)}")
    if 'reranker_model_loaded' in health_data:
        print(f"Reranker model loaded: {health_data.get('reranker_model_loaded', False)}")
    if 'ner_model_loaded' in health_data:
        print(f"NER model loaded: {health_data.get('ner_model_loaded', False)}")
    if 'transformers_available' in health_data:
        print(f"Transformers available: {health_data.get('transformers_available', False)}")
    if health_data.get('cuda_available'):
        print(f"CUDA available: Yes, GPU count: {health_data.get('gpu_count', 0)}")
    else:
        print("CUDA available: No (using CPU)")


def validate_server_connection(base_url: str = "http://localhost:8000") -> bool:
    """Validate server connection and return True if healthy"""
    health_data = check_server_health(base_url)
    if health_data.get("status") == "unreachable":
        print(f"\nError: Cannot connect to embedding server at {base_url}")
        print("Make sure the server is running with: python hoover4_ai_server.py")
        print("Or with Docker: docker-compose up")
        return False
    elif health_data.get("status") == "unhealthy":
        print(f"\nWarning: Health check failed: {health_data.get('error', 'Unknown error')}")
        return False
    else:
        print_server_status(health_data)
        return True


# Common test configurations
DEFAULT_MODEL = "intfloat/multilingual-e5-large-instruct"
DEFAULT_TASK_DESCRIPTION = "Given a web search query, retrieve relevant passages that answer the query"

# Common test texts
SIMILARITY_TEST_TEXTS = [
    "Cats are wonderful pets that love to play and sleep.",  # Similar text 1
    "Felines are amazing companions that enjoy playing and resting.",  # Similar text 2  
    "Cars are vehicles that transport people from one place to another."  # Different text
]

DIVERSE_TEST_TEXTS = [
    "Machine learning is transforming the way we analyze data.",
    "The weather today is sunny with a chance of rain in the afternoon.",
    "Python programming offers excellent libraries for data science.",
    "Artificial intelligence applications are growing rapidly across industries.",
    "The restaurant serves delicious Italian cuisine with fresh ingredients.",
    "Climate change requires immediate action from governments worldwide.",
    "Software development teams benefit from agile methodologies.",
    "Financial markets showed volatility due to economic uncertainty.",
    "Educational technology enhances learning experiences for students.",
    "Healthcare innovations are improving patient outcomes significantly.",
    "Renewable energy sources are becoming more cost-effective.",
    "Space exploration missions reveal fascinating discoveries about the universe.",
    "Social media platforms influence modern communication patterns.",
    "Autonomous vehicles represent the future of transportation.",
    "Cybersecurity measures protect sensitive information from threats.",
    "Digital transformation accelerates business process optimization.",
    "Sustainable agriculture practices support environmental conservation.",
    "Quantum computing promises revolutionary computational capabilities.",
    "Virtual reality creates immersive experiences for entertainment.",
    "Blockchain technology enables secure decentralized transactions."
]
