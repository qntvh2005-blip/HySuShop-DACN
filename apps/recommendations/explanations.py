"""Score evidence for one serving request, using its exact candidate set."""

from research.data.io import digest


def explain_ranking(bundle, ranking, history, candidates, weights, current_item_id=None):
    import numpy as np
    from research.models.recommenders import minmax

    effective_history = [current_item_id] if ranking.algorithm == "content_similar" else history
    known = bundle.history_indices(effective_history)
    scores = dict(zip(ranking.item_ids, ranking.scores))
    content, collaborative = bundle.component_scores(effective_history, candidates, weights)
    content_norm = minmax(content, bundle.epsilon)
    cf_norm = minmax(collaborative, bundle.epsilon)
    positions = {item: index for index, item in enumerate(candidates)}
    history_weights = np.array([weights.get(bundle.item_ids[index], 1.0) for index in known])
    evidence = []
    for item in ranking.item_ids:
        position = positions[item]
        index = bundle.item_index[item]
        content_links = (bundle.item_vectors[known] @ bundle.item_vectors[index].T).toarray().ravel()
        cf_links = bundle.cf_neighbors[known, index].toarray().ravel()
        influences = []
        for offset, source in enumerate(known):
            if content_links[offset] > 0 or cf_links[offset] > 0:
                influences.append({
                    "item_id": bundle.item_ids[source], "weight": float(history_weights[offset]),
                    "content_similarity": float(content_links[offset]),
                    "cf_similarity": float(cf_links[offset]),
                })
        influences.sort(key=lambda row: (
            -(row["cf_similarity"] * row["weight"]),
            -(row["content_similarity"] * row["weight"]), row["item_id"],
        ))
        evidence.append({
            "item_id": item, "score": float(scores[item]),
            "content_score": float(content[position]), "cf_score": float(collaborative[position]),
            "content_normalized": float(content_norm[position]), "cf_normalized": float(cf_norm[position]),
            "sources": influences[:5],
        })
    return {
        "alpha": bundle.alpha, "candidate_count": len(candidates),
        "candidate_sha256": digest(candidates), "history_weights": dict(weights),
        "current_item_id": current_item_id, "items": evidence,
    }
