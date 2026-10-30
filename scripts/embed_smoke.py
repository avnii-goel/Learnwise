#!/usr/bin/env python3
"""Offline embedding smoke test for LearnWise.

Loads the REAL FastEmbed ONNX model, embeds two semantically related sentences
and one unrelated sentence, and verifies vector dimensionality and cosine similarity ranking.

Usage:
    python scripts/embed_smoke.py
"""

import os
import sys

# Ensure backend directory is in sys.path
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Force real FastEmbed embedder for this smoke test
os.environ["EMBEDDER_BACKEND"] = "real"

from app.recommender.embedding import FastEmbedEmbedder


def cosine_similarity(u: list[float], v: list[float]) -> float:
    """Computes cosine similarity between two L2-normalized vectors."""
    return sum(a * b for a, b in zip(u, v))


def main():
    print("\n=== LearnWise Embedding Engine Smoke Test ===")
    embedder = FastEmbedEmbedder()
    print(f"Loading FastEmbed Model: {embedder.model_name}")
    print(f"Cache Directory        : {embedder.cache_dir}")

    s1 = "TCP uses a three-way handshake to open a connection."
    s2 = "How does the TCP connection setup handshake work?"
    s3 = "A binary search tree keeps keys in sorted order."

    print("\nTarget Sentences:")
    print(f"  [1] (Related)   : \"{s1}\"")
    print(f"  [2] (Related)   : \"{s2}\"")
    print(f"  [3] (Unrelated) : \"{s3}\"")

    vectors = embedder.embed([s1, s2, s3])

    dim_1, dim_2, dim_3 = len(vectors[0]), len(vectors[1]), len(vectors[2])
    print(f"\nVector Dimensions: [1]={dim_1}, [2]={dim_2}, [3]={dim_3}")
    assert dim_1 == 384 and dim_2 == 384 and dim_3 == 384, (
        f"Expected 384 dimensions, got {dim_1}, {dim_2}, {dim_3}"
    )

    sim_1_2 = cosine_similarity(vectors[0], vectors[1])
    sim_1_3 = cosine_similarity(vectors[0], vectors[2])
    sim_2_3 = cosine_similarity(vectors[1], vectors[2])

    print("\nCosine Similarities:")
    print(f"  sim(1, 2) [Related: TCP Handshake vs Setup]  : {sim_1_2:.4f}")
    print(f"  sim(1, 3) [Unrelated: TCP vs Binary Tree]    : {sim_1_3:.4f}")
    print(f"  sim(2, 3) [Unrelated: Setup vs Binary Tree]  : {sim_2_3:.4f}")

    assert sim_1_2 > sim_1_3, f"Expected sim(1,2) > sim(1,3), got {sim_1_2} <= {sim_1_3}"
    assert sim_1_2 > sim_2_3, f"Expected sim(1,2) > sim(2,3), got {sim_1_2} <= {sim_2_3}"

    print("\nVerification Passed: Semantic similarity ranks related sentences strictly higher.")
    print("=============================================\n")


if __name__ == "__main__":
    main()

