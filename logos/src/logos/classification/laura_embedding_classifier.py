from sentence_transformers import SentenceTransformer, util
import torch
import pickle
import os

class LauraEmbeddingClassifier:
    def __init__(self, model_name="all-MiniLM-L6-v2", db_path="laura_embeddings.pkl"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = SentenceTransformer(model_name, device=str(self.device))
        self.db_path = db_path
        self.model_db = self.load_db()

    def load_db(self):
        if os.path.exists(self.db_path):
            with open(self.db_path, "rb") as f:
                return pickle.load(f)
        return {}

    def save_db(self):
        with open(self.db_path, "wb") as f:
            pickle.dump(self.model_db, f)

    def encode_text(self, text: str, prefix="query:") -> torch.Tensor:
        full_text = f"{prefix} {text.strip()}"
        embedding = self.model.encode(full_text, convert_to_tensor=True, normalize_embeddings=True)
        return embedding

    def register_model(self, model_id: str, description: str):
        """Register or update a model with a 'passage:' embedding."""
        embedding = self.encode_text(description, prefix="passage:")
        self.model_db[model_id] = embedding
        self.save_db()

    def remove_model(self, model_id: str):
        if model_id in self.model_db:
            del self.model_db[model_id]
            self.save_db()

    def classify_prompt(self, prompt: str, top_k: int = 1):
        """Returns top-k most similar model IDs for a given prompt."""
        if not self.model_db:
            return []
        query_emb = self.encode_text(prompt, prefix="query:")
        model_ids = list(self.model_db.keys())
        model_matrix = torch.stack([self.model_db[mid] for mid in model_ids])
        sims = util.cos_sim(query_emb, model_matrix).squeeze(0)  # shape: (N,)
        top_indices = torch.topk(sims, k=top_k).indices.tolist()
        return [(model_ids[i], sims[i].item()) for i in top_indices]

    def update_feedback(self, prompt: str, correct_model_id: str, alpha: float = 0.05):
        """Adjusts the embedding of a model based on positive feedback using weighted average."""
        if correct_model_id not in self.model_db:
            return
        prompt_emb = self.encode_text(prompt, prefix="query:")
        existing_emb = self.model_db[correct_model_id]
        updated_emb = torch.nn.functional.normalize(
            (1 - alpha) * existing_emb + alpha * prompt_emb,
            p=2, dim=0
        )
        self.model_db[correct_model_id] = updated_emb
        self.save_db()

    def update_negative_feedback(self, prompt: str, wrong_model_id: str, alpha: float = 0.05):
        """Reduziert die Ähnlichkeit eines Modells mit einem Prompt durch negatives Feedback."""
        if wrong_model_id not in self.model_db:
            return
        prompt_emb = self.encode_text(prompt, prefix="query:")
        model_emb = self.model_db[wrong_model_id]
        updated_emb = torch.nn.functional.normalize(
            (1 + alpha) * model_emb - alpha * prompt_emb,
            p=2, dim=0
        )
        self.model_db[wrong_model_id] = updated_emb
        self.save_db()
