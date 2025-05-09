from antlr4 import CommonTokenStream, InputStream
from antlr4.tree.Tree import ParseTreeWalker
from module_programming_winnowing.convert_code_to_ast.languages.python.Python3Lexer import Python3Lexer
from module_programming_winnowing.convert_code_to_ast.languages.python.Python3Parser import Python3Parser
from module_programming_winnowing.convert_code_to_ast.languages.java import JavaLexer
from module_programming_winnowing.convert_code_to_ast.languages.java import JavaParser
from module_programming_winnowing.convert_code_to_ast.languages.python.Python3MethodParserListener import \
    MethodParserListener as PythonMethodParserListener
from module_programming_winnowing.convert_code_to_ast.languages.java.JavaMethodParserListener import \
    MethodParserListener as JavaMethodParserListener

# Grammars for programming languages have different parse rules
JAVA_PARSE_RULE = "compilationUnit"
PYTHON_PARSE_RULE = "file_input"

def parse_java_file(source_code: str):
    return parse_file(source_code, JavaLexer, JavaParser, JAVA_PARSE_RULE, JavaMethodParserListener)


def parse_python_file(source_code: str):
    return parse_file(source_code, Python3Lexer, Python3Parser, PYTHON_PARSE_RULE, PythonMethodParserListener)


def parse_file(source_code, lexer_class, parser_class, parse_rule, listener_class):
    input_stream = InputStream(source_code)
    lexer = lexer_class(input_stream)
    stream = CommonTokenStream(lexer)
    parser = parser_class(stream)
    tree = getattr(parser, parse_rule)()

    listener = listener_class(parser)
    walker = ParseTreeWalker()
    walker.walk(listener, tree)
    print(listener.methods)

    return listener.methods.copy()


def parse(source_code: str, programming_language: str):
    if programming_language == "java":
        return parse_java_file(source_code)
    if programming_language == "python":
        return parse_python_file(source_code)
    raise ValueError(f"Unsupported programming language: {programming_language}")


if __name__ == "__main__":
    # file_path2 = "../test_files/test_java_1.java"
    # parse_java_file(file_path2)

    code = """def process_numbers(numbers):
    total = 0
    for number in numbers:
        if number % 2 == 1:
            total += number
        else:
            total -= number
    if total > 0:
        print("Positive total:", total)
    else:
        print("Non-positive total:", total)"""
    code1 = parse_python_file(code)
    code2 = parse_python_file(code)
