from dependency_injector import containers, providers

from .settings import Settings


class DependencyContainer(containers.DeclarativeContainer):
    settings = providers.Singleton(Settings)


# Create one global, reusable instance
_container = DependencyContainer()


def get_container() -> DependencyContainer:  # ← this is what depency.py expects
    """Return the singleton DependencyContainer."""
    return _container
