import contextvars

artemis_url_context_var = contextvars.ContextVar('artemis_url')


def set_artemis_url_context_var(artemis_url: str):
    artemis_url_context_var.set(artemis_url)


def get_artemis_url():
    return artemis_url_context_var.get()