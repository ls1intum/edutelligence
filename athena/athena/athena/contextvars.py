import contextvars

artemis_url_context_var: contextvars.ContextVar = contextvars.ContextVar('artemis_url')
repository_authorization_secret_context_var: contextvars.ContextVar = contextvars.ContextVar(
    'repository_authorization_secret')


def set_artemis_url_context_var(artemis_url: str):
    artemis_url_context_var.set(artemis_url)


def get_artemis_url():
    return artemis_url_context_var.get()


def set_repository_authorization_secret_context_var(repository_authorization_secret: str):
    repository_authorization_secret_context_var.set(repository_authorization_secret)


def get_repository_authorization_secret_context_var():
    return repository_authorization_secret_context_var.get()


def repository_authorization_secret_context_var_empty():
    return repository_authorization_secret_context_var.get(None) is None
