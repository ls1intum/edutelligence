import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from transformers import pipeline


def generate_competency_relationship(medoids_emb, descriptions):
    """
    Generates relationships between competencies based on their embeddings and descriptions.
    
    Uses cosine similarity between embeddings and natural language inference to determine
    relationships between competency pairs: MATCH, REQUIRE,
    EXTEND, or NONE.

    Args:
        medoids_emb (np.ndarray): Matrix of shape (k, d) containing k competency embeddings of dimension d
        descriptions (list[str]): List of k competency descriptions in the same order as medoids

    Returns:
        np.ndarray: k x k matrix of relationships, with values "MATCH", "REQUIRE", "EXTEND", or "NONE" for each competency pair
    """
    
    # --- constants ---
    COS_NONE  = 0.35
    COS_MATCH = 0.75
    P_ENTAIL  = 0.80
    
    # --- text classification pipeline ---
    nli = pipeline("text-classification",
                   model="facebook/bart-large-mnli",
                   device=0)
    
    def entail_prob(p, h):
        logits = nli(f"{p} </s></s> {h}")
        score = logits[0]['score']
        return score

    S = cosine_similarity(medoids_emb)

    k = len(medoids_emb)
    relation = np.full((k, k), "NONE", dtype=object)

    for i in range(k):
        for j in range(k):
            if i == j:
                continue
            if S[i, j] < COS_NONE:
                continue  # NONE
    
            # MATCH
            if S[i, j] >= COS_MATCH:
                p_ij = entail_prob(descriptions[i], descriptions[j])
                p_ji = entail_prob(descriptions[j], descriptions[i])
                if p_ij >= P_ENTAIL and p_ji >= P_ENTAIL:
                    relation[i, j] = "MATCH"
                    continue
    
            # directional test
            p_ij = entail_prob(descriptions[i], descriptions[j])
            p_ji = entail_prob(descriptions[j], descriptions[i])
    
            if p_ij >= P_ENTAIL and p_ji < P_ENTAIL:
                relation[i, j] = "REQUIRE"
            elif p_ji >= P_ENTAIL and p_ij < P_ENTAIL:
                relation[i, j] = "EXTEND"

    # Sanity Check
    # for i in range(k):
    #     for j in range(k):
    #         if relation[i, j] != "NONE":
    #             print(f"{i} --{relation[i, j]}→ {j}")

    return relation