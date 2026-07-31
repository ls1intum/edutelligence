class TypeInferenceError(RuntimeError):
    pass


class InfiniteTypeError(TypeInferenceError):
    pass


class TypeMismatchError(TypeInferenceError):
    pass


class UnknownVariableError(TypeInferenceError):
    pass
