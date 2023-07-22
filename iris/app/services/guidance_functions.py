def truncate(history: list[any], max_length: int):
    if max_length == 0:
        return []

    if max_length > 0:
        return history[:max_length]

    return history[max_length:]
