from dataclasses import dataclass


@dataclass
class MethodNode:
    line_start: int
    line_end: int
    source_code: str
    name: str

    def __str__(self):
        return f"MethodNode({self.name}, lines {self.line_start} to {self.line_end})"
