"""Four train-only recommenders with deterministic candidate ranking."""

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

ALGORITHMS = ("popularity", "content", "item_cf", "hybrid")


def minmax(scores, epsilon=1e-12):
    scores = np.asarray(scores, dtype=np.float64)
    if not np.isfinite(scores).all():
        raise ValueError("Non-finite recommendation scores")
    if not scores.size:
        return scores
    return (scores - scores.min()) / (scores.max() - scores.min() + epsilon)


@dataclass
class Ranking:
    item_ids: list
    scores: list
    algorithm: str
    fallback_reason: str = ""


class RecommenderBundle:
    def __init__(self, *, ngram_range=(1, 1), min_df=1, neighbors=50, alpha=0.5, epsilon=1e-12):
        if not 0 <= alpha <= 1 or neighbors < 1 or epsilon <= 0:
            raise ValueError("Invalid recommender parameters")
        self.ngram_range = tuple(ngram_range)
        self.min_df = min_df
        self.neighbors = neighbors
        self.alpha = alpha
        self.epsilon = epsilon

    def fit(self, catalog, train, positive_min=4):
        self.item_ids = sorted(row["item_id"] for row in catalog)
        if not self.item_ids or len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("Catalog must have unique nonempty item IDs")
        by_id = {row["item_id"]: row for row in catalog}
        self.item_index = {item: i for i, item in enumerate(self.item_ids)}
        self.vectorizer = TfidfVectorizer(
            ngram_range=self.ngram_range, min_df=self.min_df, dtype=np.float64, norm="l2"
        )
        self.item_vectors = self.vectorizer.fit_transform(
            [by_id[item]["content_text"] for item in self.item_ids]
        ).tocsr()
        self.histories = defaultdict(list)
        pairs = set()
        for row in train:
            if row["rating"] < positive_min or row["item_id"] not in self.item_index:
                raise ValueError("Train contains negative or unmapped item")
            pair = (row["user_id"], row["item_id"])
            if pair in pairs:
                raise ValueError("Duplicate train user-item")
            pairs.add(pair)
            self.histories[row["user_id"]].append(row["item_id"])
        self.histories = {user: sorted(items) for user, items in sorted(self.histories.items())}
        counts = Counter(item for _, item in pairs)
        self.popularity = np.array([counts[item] for item in self.item_ids], dtype=np.float64)
        users = {user: i for i, user in enumerate(sorted(self.histories))}
        rows = [users[user] for user, item in sorted(pairs)]
        columns = [self.item_index[item] for user, item in sorted(pairs)]
        matrix = sparse.csr_matrix(
            (np.ones(len(rows)), (rows, columns)), shape=(len(users), len(self.item_ids))
        )
        # Compute sparse item-item cosine once; remove self-similarity before truncating neighborhoods.
        similarities = cosine_similarity(matrix.T, dense_output=False).tocsr()
        similarities.setdiag(0)
        similarities.eliminate_zeros()
        values, indices, indptr = [], [], [0]
        for index in range(len(self.item_ids)):
            begin, end = similarities.indptr[index : index + 2]
            candidates = similarities.indices[begin:end]
            scores = similarities.data[begin:end]
            order = np.lexsort((candidates, -scores))[: self.neighbors]
            indices.extend(candidates[order])
            values.extend(scores[order])
            indptr.append(len(values))
        self.cf_neighbors = sparse.csr_matrix((values, indices, indptr), shape=similarities.shape)
        return self

    def indices(self, items):
        try:
            return np.array([self.item_index[item] for item in items], dtype=int)
        except KeyError as error:
            raise ValueError(f"Unknown candidate item: {error.args[0]}") from error

    def history_indices(self, history):
        return np.array(
            sorted({self.item_index[item] for item in history if item in self.item_index}),
            dtype=int,
        )

    def component_scores(self, history, candidate_ids, history_weights=None):
        return self.content_scores(
            history, candidate_ids, history_weights
        ), self.collaborative_scores(history, candidate_ids, history_weights)

    def content_scores(self, history, candidate_ids, history_weights=None):
        indices = self.indices(candidate_ids)
        known = self.history_indices(history)
        if not len(known):
            return np.zeros(len(indices))
        if history_weights is None:
            profile = sparse.csr_matrix(self.item_vectors[known].mean(axis=0))
        else:
            weights = self._weights(known, history_weights)
            profile = sparse.csr_matrix(weights.reshape(1, -1)) @ self.item_vectors[known]
        profile = normalize(profile, norm="l2")
        return (self.item_vectors[indices] @ profile.T).toarray().ravel()

    def collaborative_scores(self, history, candidate_ids, history_weights=None):
        indices = self.indices(candidate_ids)
        known = self.history_indices(history)
        if not len(known):
            return np.zeros(len(indices))
        if history_weights is None:
            return np.asarray(self.cf_neighbors[known][:, indices].sum(axis=0)).ravel() / len(known)
        weights = self._weights(known, history_weights)
        return (
            np.asarray(
                (
                    sparse.csr_matrix(weights.reshape(1, -1)) @ self.cf_neighbors[known][:, indices]
                ).toarray()
            ).ravel()
            / weights.sum()
        )

    def _weights(self, known, history_weights):
        weights = np.array([history_weights.get(self.item_ids[i], 1.0) for i in known], dtype=float)
        if not np.isfinite(weights).all() or np.any(weights <= 0):
            raise ValueError("History weights must be finite and positive")
        return weights

    def raw_scores(self, algorithm, history, candidate_ids, history_weights=None):
        if algorithm not in ALGORITHMS:
            raise ValueError("Unknown algorithm")
        indices = self.indices(candidate_ids)
        if algorithm == "popularity":
            return self.popularity[indices]
        if algorithm == "content":
            return self.content_scores(history, candidate_ids, history_weights)
        if algorithm == "item_cf":
            return self.collaborative_scores(history, candidate_ids, history_weights)
        content, collaborative = self.component_scores(history, candidate_ids, history_weights)
        return self.alpha * minmax(content, self.epsilon) + (1 - self.alpha) * minmax(
            collaborative, self.epsilon
        )

    def rank(self, algorithm, history, candidate_ids, k=10, history_weights=None):
        if k < 0 or len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Invalid K or duplicate candidates")
        scores = self.raw_scores(algorithm, history, candidate_ids, history_weights)
        reason = ""
        if algorithm != "popularity" and (
            not len(self.history_indices(history)) or not np.any(scores > 0)
        ):
            reason = "no_known_history" if not len(self.history_indices(history)) else "zero_scores"
            scores = self.raw_scores("popularity", history, candidate_ids)
        if not np.isfinite(scores).all():
            raise ValueError("Non-finite ranking")
        order = np.lexsort((np.asarray(candidate_ids, dtype=str), -scores))[:k]
        return Ranking(
            [candidate_ids[i] for i in order], [float(scores[i]) for i in order], algorithm, reason
        )

    def similar(self, item_id, candidate_ids, k=10):
        if item_id not in self.item_index:
            return self.rank("popularity", [], candidate_ids, k)
        candidates = [item for item in candidate_ids if item != item_id]
        scores = (
            (
                self.item_vectors[self.indices(candidates)]
                @ self.item_vectors[self.item_index[item_id]].T
            )
            .toarray()
            .ravel()
        )
        if scores.size and not np.any(scores > 0):
            fallback = self.rank("popularity", [], candidates, k)
            return Ranking(
                fallback.item_ids, fallback.scores, "content_similar", "zero_scores"
            )
        order = np.lexsort((np.asarray(candidates, dtype=str), -scores))[:k]
        return Ranking(
            [candidates[i] for i in order], [float(scores[i]) for i in order], "content_similar"
        )
