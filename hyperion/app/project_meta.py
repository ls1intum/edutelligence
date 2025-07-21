import tomllib
from pydantic import BaseModel
from typing import Dict, List


class Author(BaseModel):
    name: str
    email: str


class ProjectMeta(BaseModel):
    name: str
    version: str
    description: str
    authors: List[Author]

    @property
    def title(self) -> str:
        """Format the project name as a title."""
        return self.name[0].upper() + self.name[1:]

    @property
    def contact(self) -> Dict[str, str]:
        """Get the first author as a contact."""
        if not self.authors:
            return {}
        return {"name": self.authors[0].name, "email": self.authors[0].email}

    @classmethod
    def load_from_pyproject(cls, file_path: str = "pyproject.toml") -> "ProjectMeta":
        """Load project metadata from pyproject.toml file."""
        with open(file_path, "rb") as f:
            meta_dict = tomllib.load(f)

        return cls(
            name=meta_dict["project"]["name"],
            version=meta_dict["project"]["version"],
            description=meta_dict["project"]["description"],
            authors=meta_dict["project"]["authors"],
        )


project_meta = ProjectMeta.load_from_pyproject()
