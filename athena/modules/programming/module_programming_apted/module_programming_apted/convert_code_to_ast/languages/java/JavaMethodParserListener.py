# Generated from JavaParser.g4 by ANTLR 4.11.1
from dataclasses import dataclass
from antlr4 import *

from module_programming_apted.convert_code_to_ast.languages.java.JavaParser import JavaParser


@dataclass
class MethodNode:
    line_start: int
    line_end: int
    source_code: str
    name: str
    ast: any
    ast_string: str

    def __str__(self):
        return f"MethodNode({self.name}, lines {self.line_start} to {self.line_end})"


def _extract_method_name(ctx):
    # Navigate through the methodHeader context to find the method name
    if hasattr(ctx, 'methodHeader'):
        method_header = ctx.methodHeader()
        if method_header:
            method_declarator = method_header.methodDeclarator()
            if method_declarator and hasattr(method_declarator, 'Identifier'):
                return method_declarator.Identifier().getText()
            elif method_declarator and hasattr(method_declarator, 'identifier'):
                return method_declarator.identifier().getText()
            else:
                # Traverse the children to find the identifier
                for child in method_declarator.children:
                    if isinstance(child, TerminalNode) and child.symbol.type == JavaParser.Identifier:
                        return child.getText()
    return "Unknown"


class MethodParserListener(ParseTreeListener):
    def __init__(self, parser):
        self.methods = []
        self.parser = parser

    def enterMethodDeclaration(self, ctx):
        self._enter_method(ctx)

    def enterConstructorDeclaration(self, ctx):
        self._enter_method(ctx)

    def enterGenericMethodDeclaration(self, ctx):
        self._enter_method(ctx)

    def enterGenericConstructorDeclaration(self, ctx):
        self._enter_method(ctx)

    def _enter_method(self, ctx):
        ast_string = ctx.toStringTree(recog=self.parser)
        method_name = _extract_method_name(ctx)

        me = MethodNode(
            line_start=ctx.start.line,
            line_end=ctx.stop.line,
            source_code=ctx.start.source[1].getText(ctx.start.start, ctx.stop.stop),
            name=method_name,
            ast=ctx,
            ast_string=ast_string
        )
        self.methods.append(me)
        print("Method found:", method_name)

    def enterIdentifier(self, ctx: ParserRuleContext):
        if self.methods and self.methods[-1].name is None:
            self.methods[-1].name = ctx.getText()
