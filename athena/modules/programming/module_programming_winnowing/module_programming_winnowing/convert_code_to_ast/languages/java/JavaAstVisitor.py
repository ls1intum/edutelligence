from antlr4 import *

from module_programming_winnowing.convert_code_to_ast.languages.java.JavaLexer import Java20Lexer
from module_programming_winnowing.convert_code_to_ast.languages.java.JavaParser import Java20Parser
from module_programming_winnowing.convert_code_to_ast.languages.java.JavaParserVisitor import Java20ParserVisitor


class RemoveVariableNames(Java20ParserVisitor):
    def visitVariableDeclaratorId(self, ctx):
        if ctx.Identifier():
            token = ctx.Identifier().symbol
            token.text = 'x'
        return self.visitChildren(ctx)


class CustomJavaVisitor(Java20ParserVisitor):
    def __init__(self):
        self.loop_count = 0
        self.if_count = 0
        self.method_count = 0

    def visitWhileStatement(self, ctx):
        self.loop_count += 1
        return self.visitChildren(ctx)

    def visitForStatement(self, ctx):
        self.loop_count += 1
        return self.visitChildren(ctx)

    def visitIfStatement(self, ctx):
        self.if_count += 1
        return self.visitChildren(ctx)

    def visitMethodDeclaration(self, ctx):
        self.method_count += 1
        return self.visitChildren(ctx)


def mutate(source_code):
    input_stream = InputStream(source_code)
    lexer = Java20Lexer(input_stream)
    stream = CommonTokenStream(lexer)
    parser = Java20Parser(stream)
    tree = parser.compilationUnit()

    # Transform the AST
    transformer = RemoveVariableNames()
    transformer.visit(tree)

    return tree


level0 = []
level1 = []
level2 = []


def find_levels(node, parser, level=0):
    if level == 0:
        level0.append(node.toStringTree(recog=parser))
    elif level == 1:
        level1.append(node.toStringTree(recog=parser))
    elif level == 2:
        level2.append(node.toStringTree(recog=parser))

    for child in node.getChildren():
        if isinstance(child, ParserRuleContext):
            find_levels(child, parser, level=level + 1)


def get_children(node, parser):
    if isinstance(node, TerminalNode):
        parent = node.getText()
        children = []
    else:
        parent = node.toStringTree(recog=parser)
        children = [child.toStringTree(recog=parser) if isinstance(child, ParserRuleContext) else child.getText() for
                    child in node.getChildren()]
    return parent, children


parents1 = []
parents2 = []
children1 = []
children2 = []


def get_parent_children_relation(root, parser, level=0):
    for child in root.getChildren():
        if isinstance(child, ParserRuleContext):
            p, c = get_children(child, parser)
            if level == 0:
                parents1.append(p)
                children1.append(c)
            elif level == 1:
                parents2.append(p)
                children2.append(c)
            get_parent_children_relation(child, parser, level + 1)


def analyze(source_code):
    input_tree = mutate(source_code)

    parser = Java20Parser(CommonTokenStream(Java20Lexer(InputStream(source_code))))

    visitor = CustomJavaVisitor()
    visitor.visit(input_tree)
    count_l = visitor.loop_count
    count_if = visitor.if_count
    count_f = visitor.method_count

    # Finden der Ebenen
    find_levels(input_tree, parser)

    # Eltern-Kind-Beziehungen finden
    get_parent_children_relation(input_tree, parser)

    counts = [count_l, count_if, count_f]
    levels = [level0, level1, level2]

    return counts, levels


if __name__ == "__main__":
    file_path = """
        public class HelloWorld {
        public static void main(String[] args) {
            System.out.println("Hello, wooorld!");
            int test = 5;
    }
    """
    counts, levels = analyze(file_path)
    print(counts, levels)
