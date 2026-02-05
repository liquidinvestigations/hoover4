#!/usr/bin/env python3
"""
Batch size optimization tests for the embedding server
"""

import requests
import time
import statistics
import pytest
from typing import List
from test_utils import (
    validate_server_connection, print_test_header, print_test_subheader, check_server_health,
    DIVERSE_TEST_TEXTS, DEFAULT_MODEL, DEFAULT_TASK_DESCRIPTION
)


def test_batch_size_optimization(base_url: str = "http://localhost:8000",
                                batch_sizes: List[int] = None,
                                test_batches_per_size: int = 5,
                                warmup_batches: int = 2):
    """Test different batch sizes to find the optimal throughput sweet spot"""

    if batch_sizes is None:
        # Test a range of batch sizes from small to large
        batch_sizes = [1, 5, 10, 20, 50, 100, 200, 500]

    print_test_header("BATCH SIZE OPTIMIZATION TEST")

    # Validate server connection
    if not validate_server_connection(base_url):
        pytest.skip("Server not available")

    # Get server info for performance baseline
    health_data = check_server_health(base_url)

    print(f"\nTest configuration:")
    print(f"- Batch sizes to test: {batch_sizes}")
    print(f"- Test batches per size: {test_batches_per_size}")
    print(f"- Warmup batches per size: {warmup_batches}")
    print(f"- Using {len(DIVERSE_TEST_TEXTS)} unique base texts")

    results = {}

    for batch_size in batch_sizes:
        print(f"\n{'='*50}")
        print(f"TESTING BATCH SIZE: {batch_size}")
        print(f"{'='*50}")

        # Prepare batches for this batch size
        all_batches = []
        for batch_idx in range(test_batches_per_size + warmup_batches):
            batch_texts = []
            for i in range(batch_size):
                # Cycle through base texts with variation
                text_idx = i % len(DIVERSE_TEST_TEXTS)
                text = DIVERSE_TEST_TEXTS[text_idx]
                if batch_idx > 0:
                    text = f"Size{batch_size}_Batch{batch_idx}: {text}"
                batch_texts.append(text)
            all_batches.append(batch_texts)

        # Warmup phase
        print(f"Running {warmup_batches} warmup batches...")
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
                    timeout=120  # Longer timeout for large batches
                )

                if response.status_code != 200:
                    print(f" Error in warmup batch {i+1}: Status code {response.status_code}")
                    # Skip this batch size if warmup fails
                    results[batch_size] = {
                        'status': 'failed',
                        'error': f'Warmup failed with status {response.status_code}'
                    }
                    break

                end_time = time.time()
                batch_time = end_time - start_time
                warmup_times.append(batch_time)

                result = response.json()
                embeddings_count = len(result["data"])
                throughput = embeddings_count / batch_time
                print(f"  Warmup {i+1}: {embeddings_count} embeddings in {batch_time:.2f}s ({throughput:.1f} emb/s)")

            except requests.exceptions.Timeout:
                print(f" Timeout in warmup batch {i+1} (batch size {batch_size})")
                results[batch_size] = {
                    'status': 'failed',
                    'error': 'Timeout during warmup'
                }
                break
            except Exception as e:
                print(f" Error in warmup batch {i+1}: {e}")
                results[batch_size] = {
                    'status': 'failed',
                    'error': str(e)
                }
                break

        # Skip to next batch size if warmup failed
        if batch_size in results and results[batch_size]['status'] == 'failed':
            continue

        # Main test phase
        print(f"Running {test_batches_per_size} test batches...")
        batch_times = []
        total_embeddings = 0

        overall_start_time = time.time()

        for i in range(warmup_batches, warmup_batches + test_batches_per_size):
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
                    timeout=120  # Longer timeout for large batches
                )

                if response.status_code != 200:
                    print(f" Error in test batch {batch_num}: Status code {response.status_code}")
                    results[batch_size] = {
                        'status': 'failed',
                        'error': f'Test failed with status {response.status_code}'
                    }
                    break

                end_time = time.time()
                batch_time = end_time - start_time
                batch_times.append(batch_time)

                result = response.json()
                embeddings_count = len(result["data"])
                total_embeddings += embeddings_count

                throughput = embeddings_count / batch_time
                print(f"  Test {batch_num}: {embeddings_count} embeddings in {batch_time:.2f}s ({throughput:.1f} emb/s)")

            except requests.exceptions.Timeout:
                print(f" Timeout in test batch {batch_num} (batch size {batch_size})")
                results[batch_size] = {
                    'status': 'failed',
                    'error': 'Timeout during test'
                }
                break
            except Exception as e:
                print(f" Error in test batch {batch_num}: {e}")
                results[batch_size] = {
                    'status': 'failed',
                    'error': str(e)
                }
                break

        # Skip to next batch size if test failed
        if batch_size in results and results[batch_size]['status'] == 'failed':
            continue

        overall_end_time = time.time()
        total_test_time = overall_end_time - overall_start_time

        # Calculate statistics for this batch size
        if batch_times:
            avg_batch_time = statistics.mean(batch_times)
            min_batch_time = min(batch_times)
            max_batch_time = max(batch_times)
            std_batch_time = statistics.stdev(batch_times) if len(batch_times) > 1 else 0

            overall_throughput = total_embeddings / total_test_time
            avg_batch_throughput = batch_size / avg_batch_time
            peak_batch_throughput = batch_size / min_batch_time

            efficiency = overall_throughput / batch_size  # batches per second

            results[batch_size] = {
                'status': 'success',
                'batch_size': batch_size,
                'avg_batch_time': avg_batch_time,
                'min_batch_time': min_batch_time,
                'max_batch_time': max_batch_time,
                'std_batch_time': std_batch_time,
                'overall_throughput': overall_throughput,
                'avg_batch_throughput': avg_batch_throughput,
                'peak_batch_throughput': peak_batch_throughput,
                'total_embeddings': total_embeddings,
                'total_test_time': total_test_time,
                'efficiency': efficiency,
                'consistency': 1.0 - (std_batch_time / avg_batch_time) if avg_batch_time > 0 else 0
            }

            print(f"\nResults for batch size {batch_size}:")
            print(f"  Overall throughput: {overall_throughput:.1f} embeddings/second")
            print(f"  Average batch time: {avg_batch_time:.2f}s ± {std_batch_time:.2f}s")
            print(f"  Efficiency: {efficiency:.2f} batches/second")

    # Analysis and recommendations
    print("\n" + "=" * 60)
    print("BATCH SIZE OPTIMIZATION ANALYSIS")
    print("=" * 60)

    successful_results = {k: v for k, v in results.items() if v['status'] == 'success'}

    if not successful_results:
        pytest.fail("No successful batch size tests completed")

    # Find optimal batch sizes
    best_throughput_size = max(successful_results.keys(),
                              key=lambda k: successful_results[k]['overall_throughput'])
    best_efficiency_size = max(successful_results.keys(),
                              key=lambda k: successful_results[k]['efficiency'])
    most_consistent_size = max(successful_results.keys(),
                              key=lambda k: successful_results[k]['consistency'])

    print(f"\nOptimal batch sizes:")
    print(f"  Best throughput: {best_throughput_size} ({successful_results[best_throughput_size]['overall_throughput']:.1f} emb/s)")
    print(f"  Best efficiency: {best_efficiency_size} ({successful_results[best_efficiency_size]['efficiency']:.2f} batches/s)")
    print(f"  Most consistent: {most_consistent_size} (consistency: {successful_results[most_consistent_size]['consistency']:.2f})")

    # Summary table
    print(f"\n{'Batch Size':<12} {'Throughput':<12} {'Avg Time':<12} {'Efficiency':<12} {'Consistency':<12} {'Status'}")
    print("-" * 72)

    for batch_size in batch_sizes:
        if batch_size in results:
            result = results[batch_size]
            if result['status'] == 'success':
                print(f"{batch_size:<12} {result['overall_throughput']:<12.1f} {result['avg_batch_time']:<12.2f} {result['efficiency']:<12.2f} {result['consistency']:<12.2f} {' Pass'}")
            else:
                print(f"{batch_size:<12} {'N/A':<12} {'N/A':<12} {'N/A':<12} {'N/A':<12} {' ' + result['error'][:20]}")
        else:
            print(f"{batch_size:<12} {'N/A':<12} {'N/A':<12} {'N/A':<12} {'N/A':<12} {' Skipped'}")

    # Recommendations
    print(f"\n{'='*60}")
    print("RECOMMENDATIONS")
    print(f"{'='*60}")

    best_overall = best_throughput_size
    best_result = successful_results[best_overall]

    print(f"\n🎯 RECOMMENDED BATCH SIZE: {best_overall}")
    print(f"   Expected throughput: {best_result['overall_throughput']:.1f} embeddings/second")
    print(f"   Average processing time: {best_result['avg_batch_time']:.2f} seconds per batch")
    print(f"   Estimated time for 1M embeddings: {1000000 / best_result['overall_throughput'] / 3600:.1f} hours")

    # Performance insights
    if best_result['overall_throughput'] > 100:
        print(f"   🚀 Excellent performance - well optimized for your hardware")
    elif best_result['overall_throughput'] > 50:
        print(f"    Good performance - suitable for production workloads")
    else:
        print(f"   ⚠️  Moderate performance - consider GPU acceleration if available")

    if best_result['consistency'] > 0.8:
        print(f"   📊 Highly consistent performance")
    elif best_result['consistency'] > 0.6:
        print(f"   📊 Reasonably consistent performance")
    else:
        print(f"   ⚠️  Variable performance - monitor for stability issues")

    # Verify we got meaningful results
    assert len(successful_results) > 0, "At least one batch size should succeed"
    assert best_result['overall_throughput'] > 1.0, f"Best throughput too low: {best_result['overall_throughput']:.1f} emb/s"


def test_small_batch_sizes():
    """Test optimization for small batch sizes only"""
    print_test_header("SMALL BATCH SIZE OPTIMIZATION")

    small_batch_sizes = [1, 2, 5, 10, 15, 20]
    test_batch_size_optimization(
        batch_sizes=small_batch_sizes,
        test_batches_per_size=3,
        warmup_batches=1
    )


def test_large_batch_sizes():
    """Test optimization for large batch sizes only"""
    print_test_header("LARGE BATCH SIZE OPTIMIZATION")

    large_batch_sizes = [50, 100, 200, 500]
    test_batch_size_optimization(
        batch_sizes=large_batch_sizes,
        test_batches_per_size=2,
        warmup_batches=1
    )


if __name__ == "__main__":
    print("Running batch size optimization tests...\n")

    try:
        # Full optimization test
        test_batch_size_optimization()
        print("\n" + "=" * 80)

        print("BATCH SIZE OPTIMIZATION RESULTS")
        print("=" * 80)
        print(f" Optimization completed successfully!")

        print("\nCheck the detailed analysis above for:")
        print("  • Throughput comparisons across batch sizes")
        print("  • Performance consistency metrics")
        print("  • Hardware-specific recommendations")
        print("  • Estimated processing times for large datasets")

    except Exception as e:
        print(f" Batch optimization tests failed: {e}")
        exit(1)
