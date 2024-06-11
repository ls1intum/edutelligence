from itertools import islice, zip_longest

# https://docs.python.org/3/library/itertools.html#itertools-recipes

#TODO Move this to module athena, since this is just copied from ThemisML
def batched(iterable, n):
    """Batch data into lists of length n. The last batch may be shorter."""
    # batched('ABCDEFG', 3) --> ABC DEF G
    it = iter(iterable)
    while True:
        batch = list(islice(it, n))
        if not batch:
            return
        yield batch