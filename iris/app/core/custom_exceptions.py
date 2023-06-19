from fastapi import HTTPException, status


class BadDataException(HTTPException):
    def __init__(self, error_message: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[
                {
                    "loc": [],
                    "msg": error_message,
                    "type": "value_error.bad_data",
                }
            ],
        )
