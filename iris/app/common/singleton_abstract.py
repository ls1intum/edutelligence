from abc import ABCMeta


class SingletonABCMeta(ABCMeta):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            # Ensure the instance implements __call__ if the class is not abstract
            if not hasattr(instance, "_is_abstract") and not callable(
                getattr(instance, "__call__", None)
            ):
                raise NotImplementedError(
                    f"{cls.__name__} must implement the __call__ method."
                )
            cls._instances[cls] = instance
        return cls._instances[cls]
