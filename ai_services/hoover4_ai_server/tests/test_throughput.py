#!/usr/bin/env python3
"""
Batch throughput tests for the embedding server
"""

import requests
import time
import statistics
import pytest
from test_utils import (
    validate_server_connection, print_test_header, check_server_health,
    DIVERSE_TEST_TEXTS, DEFAULT_MODEL, DEFAULT_TASK_DESCRIPTION
)


def test_batch_throughput(base_url: str = "http://localhost:8000",
                         num_batches: int = 10,
                         batch_size: int = 20,
                         warmup_batches: int = 3):
    """Test the throughput of the embedding server in batch mode"""

    print_test_header("BATCH THROUGHPUT TEST")

    # Validate server connection
    if not validate_server_connection(base_url):
        pytest.skip("Server not available")

    # Get server info for performance baseline
    health_data = check_server_health(base_url)

    print(f"\nTest configuration:")
    print(f"- Number of test batches: {num_batches}")
    print(f"- Batch size: {batch_size} texts per batch")
    print(f"- Warmup batches: {warmup_batches}")
    print(f"- Total texts to process: {(num_batches + warmup_batches) * batch_size}")
    print(f"- Using {len(DIVERSE_TEST_TEXTS)} unique base texts (will be repeated as needed)")

    # Prepare batches
    all_batches = []
    for batch_idx in range(num_batches + warmup_batches):
        batch_texts = []
        for i in range(batch_size):
            # Cycle through base texts and add variation
            text_idx = i % len(DIVERSE_TEST_TEXTS)
            text = DIVERSE_TEST_TEXTS[text_idx]
            # Add slight variation to avoid identical texts
            if batch_idx > 0:
                text = f"Batch {batch_idx}: {text}"
            batch_texts.append(text)
        all_batches.append(batch_texts)

    print(f"\nPrepared {len(all_batches)} batches")

    # Warmup phase
    print(f"\nRunning {warmup_batches} warmup batches...")
    warmup_times = []

    for i in range(warmup_batches):
        start_time = time.time()
        try:
            response = requests.post(
                f"{base_url}/v1/embeddings",
                json={
                    "input": all_batches[i],
                    "model": DEFAULT_MODEL,
                    "task_description": DEFAULT_TASK_DESCRIPTION
                },
                timeout=60  # 60 second timeout
            )

            assert response.status_code == 200, f"Error in warmup batch {i+1}: Status code {response.status_code}"

            end_time = time.time()
            batch_time = end_time - start_time
            warmup_times.append(batch_time)

            result = response.json()
            embeddings_count = len(result["data"])
            print(f"  Warmup batch {i+1}: {embeddings_count} embeddings in {batch_time:.2f}s")

        except requests.exceptions.Timeout:
            pytest.fail(f"Timeout in warmup batch {i+1}")
        except Exception as e:
            pytest.fail(f"Error in warmup batch {i+1}: {e}")

    avg_warmup_time = statistics.mean(warmup_times)
    print(f"Warmup completed. Average time per batch: {avg_warmup_time:.2f}s")

    # Main throughput test
    print(f"\nRunning {num_batches} test batches...")
    batch_times = []
    total_embeddings = 0

    overall_start_time = time.time()

    for i in range(warmup_batches, warmup_batches + num_batches):
        batch_num = i - warmup_batches + 1
        start_time = time.time()

        try:
            response = requests.post(
                f"{base_url}/v1/embeddings",
                json={
                    "input": all_batches[i],
                    "model": DEFAULT_MODEL,
                    "task_description": DEFAULT_TASK_DESCRIPTION
                },
                timeout=60  # 60 second timeout
            )

            assert response.status_code == 200, f"Error in batch {batch_num}: Status code {response.status_code}"

            end_time = time.time()
            batch_time = end_time - start_time
            batch_times.append(batch_time)

            result = response.json()
            embeddings_count = len(result["data"])
            total_embeddings += embeddings_count

            embeddings_per_second = embeddings_count / batch_time
            print(f"  Batch {batch_num:2d}: {embeddings_count} embeddings in {batch_time:.2f}s ({embeddings_per_second:.1f} emb/s)")

        except requests.exceptions.Timeout:
            pytest.fail(f"Timeout in batch {batch_num}")
        except Exception as e:
            pytest.fail(f"Error in batch {batch_num}: {e}")

    overall_end_time = time.time()
    total_test_time = overall_end_time - overall_start_time

    # Calculate statistics
    print("\n" + "=" * 60)
    print("THROUGHPUT ANALYSIS")
    print("=" * 60)

    avg_batch_time = statistics.mean(batch_times)
    min_batch_time = min(batch_times)
    max_batch_time = max(batch_times)
    std_batch_time = statistics.stdev(batch_times) if len(batch_times) > 1 else 0

    overall_throughput = total_embeddings / total_test_time
    avg_batch_throughput = batch_size / avg_batch_time
    peak_batch_throughput = batch_size / min_batch_time

    print(f"\nBatch timing statistics:")
    print(f"  Average batch time: {avg_batch_time:.2f}s ± {std_batch_time:.2f}s")
    print(f"  Fastest batch time: {min_batch_time:.2f}s")
    print(f"  Slowest batch time: {max_batch_time:.2f}s")

    print(f"\nThroughput statistics:")
    print(f"  Total embeddings processed: {total_embeddings}")
    print(f"  Total test time: {total_test_time:.2f}s")
    print(f"  Overall throughput: {overall_throughput:.1f} embeddings/second")
    print(f"  Average batch throughput: {avg_batch_throughput:.1f} embeddings/second")
    print(f"  Peak batch throughput: {peak_batch_throughput:.1f} embeddings/second")

    # Performance assessment
    print(f"\nPerformance assessment:")
    cpu_baseline = 5.0  # embeddings/second baseline for CPU
    gpu_baseline = 50.0  # embeddings/second baseline for GPU

    if health_data.get('cuda_available'):
        baseline = gpu_baseline
        device_type = "GPU"
    else:
        baseline = cpu_baseline
        device_type = "CPU"

    performance_ratio = overall_throughput / baseline

    print(f"  Device type: {device_type}")
    print(f"  Expected baseline: {baseline} embeddings/second")
    print(f"  Performance ratio: {performance_ratio:.2f}x baseline")

    if performance_ratio >= 0.8:
        print(f"   Excellent performance ({performance_ratio:.1f}x baseline)")
    elif performance_ratio >= 0.5:
        print(f"   Good performance ({performance_ratio:.1f}x baseline)")
    elif performance_ratio >= 0.3:
        print(f"  ⚠️  Moderate performance ({performance_ratio:.1f}x baseline)")
    else:
        print(f"   Poor performance ({performance_ratio:.1f}x baseline)")

    # Consistency check
    consistency_threshold = 0.3  # 30% variation is acceptable
    consistency_ratio = std_batch_time / avg_batch_time

    print(f"\nConsistency assessment:")
    print(f"  Timing variation coefficient: {consistency_ratio:.2f}")

    if consistency_ratio <= consistency_threshold:
        print(f"   Consistent performance (variation ≤ {consistency_threshold:.0%})")
    else:
        print(f"  ⚠️  Variable performance (variation > {consistency_threshold:.0%})")

    # Summary table
    print("\n" + "=" * 60)
    print("BATCH PERFORMANCE SUMMARY")
    print("=" * 60)
    print(f"{'Metric':<25} {'Value':<15} {'Unit'}")
    print("-" * 50)
    print(f"{'Batch size':<25} {batch_size:<15} {'texts'}")
    print(f"{'Batches processed':<25} {num_batches:<15} {'batches'}")
    print(f"{'Total embeddings':<25} {total_embeddings:<15} {'embeddings'}")
    print(f"{'Overall throughput':<25} {overall_throughput:<15.1f} {'emb/sec'}")
    print(f"{'Average batch time':<25} {avg_batch_time:<15.2f} {'seconds'}")
    print(f"{'Performance ratio':<25} {performance_ratio:<15.2f} {'x baseline'}")

    # Verify minimum performance requirements
    assert overall_throughput > 1.0, f"Overall throughput too low: {overall_throughput:.1f} emb/s"
    assert total_embeddings == num_batches * batch_size, f"Incorrect total embeddings: {total_embeddings}"

    print(" Batch throughput test completed successfully!")

    # return {
    #     'overall_throughput': overall_throughput,
    #     'avg_batch_time': avg_batch_time,
    #     'performance_ratio': performance_ratio,
    #     'consistency_ratio': consistency_ratio
    # }


def test_small_batch_performance():
    """Test performance with smaller batches"""
    print_test_header("SMALL BATCH PERFORMANCE TEST")

    test_batch_throughput(
        num_batches=5,
        batch_size=5,
        warmup_batches=2
    )


def test_large_batch_performance():
    """Test performance with larger batches"""
    print_test_header("LARGE BATCH PERFORMANCE TEST")

    test_batch_throughput(
        num_batches=3,
        batch_size=100,
        warmup_batches=1
    )


if __name__ == "__main__":
    print("Running throughput tests...\n")

    try:
        # Standard throughput test
        standard_results = test_batch_throughput()
        print("\n" + "=" * 80)

        # Small batch test
        small_results = test_small_batch_performance()
        print("\n" + "=" * 80)

        # Large batch test
        large_results = test_large_batch_performance()
        print("\n" + "=" * 80)

        print("THROUGHPUT TESTS COMPARISON")
        print("=" * 80)
        print(f"{'Test Type':<20} {'Throughput':<15} {'Avg Time':<15} {'Performance':<15}")
        print("-" * 65)
        print(f"{'Standard (20)':<20} {standard_results['overall_throughput']:<15.1f} {standard_results['avg_batch_time']:<15.2f} {standard_results['performance_ratio']:<15.2f}")
        print(f"{'Small (5)':<20} {small_results['overall_throughput']:<15.1f} {small_results['avg_batch_time']:<15.2f} {small_results['performance_ratio']:<15.2f}")
        print(f"{'Large (100)':<20} {large_results['overall_throughput']:<15.1f} {large_results['avg_batch_time']:<15.2f} {large_results['performance_ratio']:<15.2f}")

        print("\n All throughput tests completed successfully!")

    except Exception as e:
        print(f" Throughput tests failed: {e}")
        exit(1)
