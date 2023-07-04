from antlr4 import InputStream, CommonTokenStream, ParseTreeWalker

from .languages.JavaLexer import JavaLexer
from .languages.JavaParser import JavaParser
from .method_parser_listener import MethodParserListener, JAVA_METHOD_DECLARATIONS


def _get_tree_for(source_code: str):
    input_stream = InputStream(source_code)
    lexer = JavaLexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = JavaParser(stream)
    return parser.compilationUnit()


def _get_methods_in_tree(tree):
    listener = MethodParserListener(JAVA_METHOD_DECLARATIONS)
    walker = ParseTreeWalker()
    walker.walk(listener, tree)
    return listener.methods.copy()


def extract_methods(source_code: str):
    tree = _get_tree_for(source_code)
    return _get_methods_in_tree(tree)


if __name__ == '__main__':
    from pprint import pprint
    from pathlib import Path

    with Path("test.java").open("r", encoding="utf-8") as f:
        code = f.read()
        print("Methods: ")
        pprint(list(map(str, extract_methods(code))))
