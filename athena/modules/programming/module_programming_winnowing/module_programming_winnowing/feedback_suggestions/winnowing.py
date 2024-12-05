# This implementation has been adapted from the algorithm provided in the repository:
# https://github.com/prateksha/Source-Code-Similarity-Measurement/blob/master/generate_ast.py
# The original code has been modified to fit the specific requirements of this project,
# including changes in the caching mechanism and additional functionality to handle
# both Java and Python code (and potentially further programming languages) similarity measurements.


import nltk
import math
from nltk.util import ngrams
from collections import Counter
from statistics import mean

def cosine_similarity(l1, l2):
    vec1 = Counter(l1)
    vec2 = Counter(l2)

    intersection = set(vec1.keys()) & set(vec2.keys())

    numerator = sum([vec1[x] * vec2[x] for x in intersection])

    sum1 = sum([vec1[x] ** 2 for x in vec1.keys()])
    sum2 = sum([vec2[x] ** 2 for x in vec2.keys()])
    denominator = math.sqrt(sum1) * math.sqrt(sum2)

    if not denominator:
        return 0.0

    return float(numerator) / denominator


# Could be changed to include rightmost minimum too
def get_min(get_key=lambda x: x):
    def rightmost_minimum(l):
        minimum = float('inf')
        minimum_index = -1
        pos = 0

        while pos < len(l):
            if get_key(l[pos]) < minimum:
                minimum = get_key(l[pos])
                minimum_index = pos
            pos += 1

        return l[minimum_index]

    return rightmost_minimum


# Have used the inbuilt hash function (Should try a self defined rolling hash function)
def winnowing(kgrams, k, t):
    modified_min_func = get_min(lambda key_value: key_value[0])

    document_fingerprints = []

    # print(kgrams)
    hash_table = [(hash(kgrams[i]), i) for i in range(len(kgrams))]
    # print(len(hash_table))

    window_length = t - k + 1
    window_begin = 0
    window_end = window_length

    minimum_hash = None

    while (window_end < len(hash_table)):
        window = hash_table[window_begin:window_end]
        window_minimum = modified_min_func(window)

        if (minimum_hash != window_minimum):
            # print(window_minimum)
            document_fingerprints.append(window_minimum[0])  # not taking positions into consideration
            minimum_hash = window_minimum

        window_begin = window_begin + 1
        window_end = window_end + 1

    return document_fingerprints


def generate_kgrams(data, k):
    for text in data:
        token = nltk.word_tokenize(text)
        kgrams = ngrams(token, k)
        lst_kgrams = list(kgrams)
        # print("Kgrams : ", lst_kgrams)
        return lst_kgrams


# only conversion to lowercase for now
def preprocess(document):
    preprocessed_document = []
    for item in document:
        item = item.lower()
        preprocessed_document.append(item)
    return preprocessed_document


def generate_fingerprints(data, k, t):
    preprocessed_data = preprocess(data)
    kgrams = generate_kgrams(preprocessed_data, k)
    # print(len(kgrams))
    document_fingerprints = winnowing(kgrams, k, t)
    return document_fingerprints


def calculate_similarity(counts1, levels1, counts2, levels2):
    lev0s = []
    lev1s = []
    lev2s = []

    for i in range(10):
        fingerprints1_0 = generate_fingerprints(levels1[0], 13, 17)
        fingerprints2_0 = generate_fingerprints(levels2[0], 13, 17)
        cosine_similarity_lev0 = cosine_similarity(fingerprints1_0, fingerprints2_0)
        lev0s.append(cosine_similarity_lev0)

        fingerprints1_1 = generate_fingerprints(levels1[1], 13, 17)
        fingerprints2_1 = generate_fingerprints(levels2[1], 13, 17)
        cosine_similarity_lev1 = cosine_similarity(fingerprints1_1, fingerprints2_1)
        lev1s.append(cosine_similarity_lev1)

        fingerprints1_2 = generate_fingerprints(levels1[2], 13, 17)
        fingerprints2_2 = generate_fingerprints(levels2[2], 13, 17)
        cosine_similarity_lev2 = cosine_similarity(fingerprints1_2, fingerprints2_2)
        lev2s.append(cosine_similarity_lev2)

    final_cosine_similarity_lev0 = round(mean(lev0s), 2)
    final_cosine_similarity_lev1 = round(mean(lev1s), 2)
    final_cosine_similarity_lev2 = round(mean(lev2s), 2)

    normalization_score = 0
    t = 0
    for c in range(3):
        x = counts1[c]
        y = counts2[c]
        if (x + y) != 0:
            t = t + 1
            if x > y:
                s = 1 - ((x - y) / (x + y))
            else:
                s = 1 - ((y - x) / (x + y))
            normalization_score += (10 * s)

    if t != 0:
        normalization_score = normalization_score / (t * 10)
        total_similarity_score_win = ((0.5 * final_cosine_similarity_lev0) + (0.3 * final_cosine_similarity_lev1) + (
                0.2 * final_cosine_similarity_lev2))
        normalization_score = normalization_score
        final_score = (total_similarity_score_win * 60) + (normalization_score * 40)
        print("Similarity score = : \n", final_score)
    else:
        total_similarity_score_win = ((0.5 * final_cosine_similarity_lev0) + (0.3 * final_cosine_similarity_lev1) + (
                0.2 * final_cosine_similarity_lev2))
        final_score = (total_similarity_score_win * 100)

    return final_score


if __name__ == "__main__":
    from module_programming_winnowing.convert_code_to_ast.languages.python.PythonAstVisitor import analyze

    file_path1 = "1.py" #TODO test with string
    file_path2 = "test6b.py" #TODO Test with String

    counts1, levels1 = analyze(file_path1)
    counts2, levels2 = analyze(file_path2)

    similarity_score = calculate_similarity(counts1, levels1, counts2, levels2)
    print("Similarity score:", similarity_score)
