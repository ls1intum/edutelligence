from dependency_injector import containers, providers


class DependencyContainer(containers.DeclarativeContainer):
    """Central IoC container for Athena."""

    # add your providers / singletons here, e.g.:
    # config = providers.Configuration()
    # db_session = providers.Singleton(create_session)
    ...


# Create one global, reusable instance
_container = DependencyContainer()


def get_container() -> DependencyContainer:  # ← this is what depency.py expects
    """Return the singleton DependencyContainer."""
    return _container
