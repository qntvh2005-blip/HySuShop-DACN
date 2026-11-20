import math


def topk_metrics(ranked, relevant, k):
    if k < 1 or not relevant or len(ranked) != len(set(ranked)):
        raise ValueError("Positive K, nonempty relevance and unique ranking required")
    relevant = set(relevant)
    hits = [i + 1 for i, item in enumerate(ranked[:k]) if item in relevant]
    dcg = sum(1 / math.log2(rank + 1) for rank in hits)
    idcg = sum(1 / math.log2(rank + 1) for rank in range(1, min(k, len(relevant)) + 1))
    return {
        "precision": len(hits) / k,
        "recall": len(hits) / len(relevant),
        "hit_rate": float(bool(hits)),
        "ndcg": dcg / idcg,
    }
