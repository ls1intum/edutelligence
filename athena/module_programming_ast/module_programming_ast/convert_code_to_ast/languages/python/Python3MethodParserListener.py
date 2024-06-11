from antlr4 import ParseTreeListener

from module_programming_ast.convert_code_to_ast.languages.python.Python3Parser import Python3Parser
from module_programming_ast.convert_code_to_ast.languages.python.Python3ParserListener import Python3ParserListener
from dataclasses import dataclass


@dataclass
class MethodNode:
    def __init__(self, line_start, line_end, source_code, name, ast_string):
        self.line_start = line_start
        self.line_end = line_end
        self.source_code = source_code
        self.name = name
        self.ast_string = ast_string


class MethodParserListener(Python3ParserListener):
    def __init__(self, parser):
        self.methods = []
        self.parser = parser

    def enterFuncdef(self, ctx: Python3Parser.FuncdefContext):
        # Initialize the method name as None
        method_name = None

        # Iterate over the children of the context to find the method name
        for child in ctx.children:
            if isinstance(child, Python3Parser.NameContext):
                method_name = child.getText()
                break

        # If method name is not found, set it to "Unknown"
        if method_name is None:
            method_name = "Unknown"

        ast_string = ctx.toStringTree(recog=self.parser)

        # Create a MethodNode for the method
        method_node = MethodNode(
            line_start=ctx.start.line,
            line_end=ctx.stop.line,
            source_code=ctx.start.source[1].getText(ctx.start.start, ctx.stop.stop),
            name=method_name,
            ast_string=ast_string
        )

        self.methods.append(method_node)

    def enterIdentifier(self, ctx):
        if self.methods and self.methods[-1].name is None:
            self.methods[-1].name = ctx.getText()
