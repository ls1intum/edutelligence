import contextvars

lms_url_context_var: contextvars.ContextVar = contextvars.ContextVar('lms_url')
repository_authorization_secret_context_var: contextvars.ContextVar = contextvars.ContextVar(
    'repository_authorization_secret')


def set_lms_url_context_var(lms_url: str):
    lms_url_context_var.set(lms_url)


def get_lms_url():
    return lms_url_context_var.get()


def set_repository_authorization_secret_context_var(repository_authorization_secret: str):
    repository_authorization_secret_context_var.set(repository_authorization_secret)


def get_repository_authorization_secret_context_var():
    return repository_authorization_secret_context_var.get()


def repository_authorization_secret_context_var_empty():
    return repository_authorization_secret_context_var.get(None) is None
