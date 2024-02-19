from pydantic import BaseModel


class Course(BaseModel):
    title: str
    description: str

    def __str__(self):
        return f'Course(title="{self.title}", description="{self.description}")'
