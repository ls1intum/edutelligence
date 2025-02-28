from sentence_transformers import SentenceTransformer

sentence = ["This is an example sentence"]
model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
embeddings = model.encode(sentence)

# Sanity check
print(embeddings)