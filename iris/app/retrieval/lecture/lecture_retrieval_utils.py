from typing import List


def merge_retrieved_chunks(
    basic_retrieved_lecture_chunks, hyde_retrieved_lecture_chunks
) -> List[dict]:
    """
    Merge the retrieved chunks from the basic and hyde retrieval methods. This function ensures that for any
    duplicate IDs, the properties from hyde_retrieved_lecture_chunks will overwrite those from
    basic_retrieved_lecture_chunks.
    """
    merged_chunks = {}
    for chunk in basic_retrieved_lecture_chunks:
        merged_chunks[chunk["id"]] = chunk["properties"]

    for chunk in hyde_retrieved_lecture_chunks:
        merged_chunks[chunk["id"]] = chunk["properties"]

    return [properties for uuid, properties in merged_chunks.items()]

