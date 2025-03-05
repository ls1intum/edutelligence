# Generated from Python3Parser.g4 by ANTLR 4.13.1
from antlr4 import *

if "." in __name__:
    from .Python3Parser import Python3Parser
else:
    from Python3Parser import Python3Parser


# This class defines a complete generic visitor for a parse tree produced by Python3Parser.

class Python3ParserVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by Python3Parser#single_input.
    def visitSingle_input(self, ctx: Python3Parser.Single_inputContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#file_input.
    def visitFile_input(self, ctx: Python3Parser.File_inputContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#eval_input.
    def visitEval_input(self, ctx: Python3Parser.Eval_inputContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#decorator.
    def visitDecorator(self, ctx: Python3Parser.DecoratorContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#decorators.
    def visitDecorators(self, ctx: Python3Parser.DecoratorsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#decorated.
    def visitDecorated(self, ctx: Python3Parser.DecoratedContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#async_funcdef.
    def visitAsync_funcdef(self, ctx: Python3Parser.Async_funcdefContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#funcdef.
    def visitFuncdef(self, ctx: Python3Parser.FuncdefContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#parameters.
    def visitParameters(self, ctx: Python3Parser.ParametersContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#typedargslist.
    def visitTypedargslist(self, ctx: Python3Parser.TypedargslistContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#tfpdef.
    def visitTfpdef(self, ctx: Python3Parser.TfpdefContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#varargslist.
    def visitVarargslist(self, ctx: Python3Parser.VarargslistContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#vfpdef.
    def visitVfpdef(self, ctx: Python3Parser.VfpdefContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#stmt.
    def visitStmt(self, ctx: Python3Parser.StmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#simple_stmts.
    def visitSimple_stmts(self, ctx: Python3Parser.Simple_stmtsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#simple_stmt.
    def visitSimple_stmt(self, ctx: Python3Parser.Simple_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#expr_stmt.
    def visitExpr_stmt(self, ctx: Python3Parser.Expr_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#annassign.
    def visitAnnassign(self, ctx: Python3Parser.AnnassignContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#testlist_star_expr.
    def visitTestlist_star_expr(self, ctx: Python3Parser.Testlist_star_exprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#augassign.
    def visitAugassign(self, ctx: Python3Parser.AugassignContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#del_stmt.
    def visitDel_stmt(self, ctx: Python3Parser.Del_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#pass_stmt.
    def visitPass_stmt(self, ctx: Python3Parser.Pass_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#flow_stmt.
    def visitFlow_stmt(self, ctx: Python3Parser.Flow_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#break_stmt.
    def visitBreak_stmt(self, ctx: Python3Parser.Break_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#continue_stmt.
    def visitContinue_stmt(self, ctx: Python3Parser.Continue_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#return_stmt.
    def visitReturn_stmt(self, ctx: Python3Parser.Return_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#yield_stmt.
    def visitYield_stmt(self, ctx: Python3Parser.Yield_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#raise_stmt.
    def visitRaise_stmt(self, ctx: Python3Parser.Raise_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#import_stmt.
    def visitImport_stmt(self, ctx: Python3Parser.Import_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#import_name.
    def visitImport_name(self, ctx: Python3Parser.Import_nameContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#import_from.
    def visitImport_from(self, ctx: Python3Parser.Import_fromContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#import_as_name.
    def visitImport_as_name(self, ctx: Python3Parser.Import_as_nameContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#dotted_as_name.
    def visitDotted_as_name(self, ctx: Python3Parser.Dotted_as_nameContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#import_as_names.
    def visitImport_as_names(self, ctx: Python3Parser.Import_as_namesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#dotted_as_names.
    def visitDotted_as_names(self, ctx: Python3Parser.Dotted_as_namesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#dotted_name.
    def visitDotted_name(self, ctx: Python3Parser.Dotted_nameContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#global_stmt.
    def visitGlobal_stmt(self, ctx: Python3Parser.Global_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#nonlocal_stmt.
    def visitNonlocal_stmt(self, ctx: Python3Parser.Nonlocal_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#assert_stmt.
    def visitAssert_stmt(self, ctx: Python3Parser.Assert_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#compound_stmt.
    def visitCompound_stmt(self, ctx: Python3Parser.Compound_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#async_stmt.
    def visitAsync_stmt(self, ctx: Python3Parser.Async_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#if_stmt.
    def visitIf_stmt(self, ctx: Python3Parser.If_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#while_stmt.
    def visitWhile_stmt(self, ctx: Python3Parser.While_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#for_stmt.
    def visitFor_stmt(self, ctx: Python3Parser.For_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#try_stmt.
    def visitTry_stmt(self, ctx: Python3Parser.Try_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#with_stmt.
    def visitWith_stmt(self, ctx: Python3Parser.With_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#with_item.
    def visitWith_item(self, ctx: Python3Parser.With_itemContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#except_clause.
    def visitExcept_clause(self, ctx: Python3Parser.Except_clauseContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#block.
    def visitBlock(self, ctx: Python3Parser.BlockContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#match_stmt.
    def visitMatch_stmt(self, ctx: Python3Parser.Match_stmtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#subject_expr.
    def visitSubject_expr(self, ctx: Python3Parser.Subject_exprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#star_named_expressions.
    def visitStar_named_expressions(self, ctx: Python3Parser.Star_named_expressionsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#star_named_expression.
    def visitStar_named_expression(self, ctx: Python3Parser.Star_named_expressionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#case_block.
    def visitCase_block(self, ctx: Python3Parser.Case_blockContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#guard.
    def visitGuard(self, ctx: Python3Parser.GuardContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#patterns.
    def visitPatterns(self, ctx: Python3Parser.PatternsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#pattern.
    def visitPattern(self, ctx: Python3Parser.PatternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#as_pattern.
    def visitAs_pattern(self, ctx: Python3Parser.As_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#or_pattern.
    def visitOr_pattern(self, ctx: Python3Parser.Or_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#closed_pattern.
    def visitClosed_pattern(self, ctx: Python3Parser.Closed_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#literal_pattern.
    def visitLiteral_pattern(self, ctx: Python3Parser.Literal_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#literal_expr.
    def visitLiteral_expr(self, ctx: Python3Parser.Literal_exprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#complex_number.
    def visitComplex_number(self, ctx: Python3Parser.Complex_numberContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#signed_number.
    def visitSigned_number(self, ctx: Python3Parser.Signed_numberContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#signed_real_number.
    def visitSigned_real_number(self, ctx: Python3Parser.Signed_real_numberContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#real_number.
    def visitReal_number(self, ctx: Python3Parser.Real_numberContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#imaginary_number.
    def visitImaginary_number(self, ctx: Python3Parser.Imaginary_numberContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#capture_pattern.
    def visitCapture_pattern(self, ctx: Python3Parser.Capture_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#pattern_capture_target.
    def visitPattern_capture_target(self, ctx: Python3Parser.Pattern_capture_targetContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#wildcard_pattern.
    def visitWildcard_pattern(self, ctx: Python3Parser.Wildcard_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#value_pattern.
    def visitValue_pattern(self, ctx: Python3Parser.Value_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#attr.
    def visitAttr(self, ctx: Python3Parser.AttrContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#name_or_attr.
    def visitName_or_attr(self, ctx: Python3Parser.Name_or_attrContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#group_pattern.
    def visitGroup_pattern(self, ctx: Python3Parser.Group_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#sequence_pattern.
    def visitSequence_pattern(self, ctx: Python3Parser.Sequence_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#open_sequence_pattern.
    def visitOpen_sequence_pattern(self, ctx: Python3Parser.Open_sequence_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#maybe_sequence_pattern.
    def visitMaybe_sequence_pattern(self, ctx: Python3Parser.Maybe_sequence_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#maybe_star_pattern.
    def visitMaybe_star_pattern(self, ctx: Python3Parser.Maybe_star_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#star_pattern.
    def visitStar_pattern(self, ctx: Python3Parser.Star_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#mapping_pattern.
    def visitMapping_pattern(self, ctx: Python3Parser.Mapping_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#items_pattern.
    def visitItems_pattern(self, ctx: Python3Parser.Items_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#key_value_pattern.
    def visitKey_value_pattern(self, ctx: Python3Parser.Key_value_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#double_star_pattern.
    def visitDouble_star_pattern(self, ctx: Python3Parser.Double_star_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#class_pattern.
    def visitClass_pattern(self, ctx: Python3Parser.Class_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#positional_patterns.
    def visitPositional_patterns(self, ctx: Python3Parser.Positional_patternsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#keyword_patterns.
    def visitKeyword_patterns(self, ctx: Python3Parser.Keyword_patternsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#keyword_pattern.
    def visitKeyword_pattern(self, ctx: Python3Parser.Keyword_patternContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#test.
    def visitTest(self, ctx: Python3Parser.TestContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#test_nocond.
    def visitTest_nocond(self, ctx: Python3Parser.Test_nocondContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#lambdef.
    def visitLambdef(self, ctx: Python3Parser.LambdefContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#lambdef_nocond.
    def visitLambdef_nocond(self, ctx: Python3Parser.Lambdef_nocondContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#or_test.
    def visitOr_test(self, ctx: Python3Parser.Or_testContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#and_test.
    def visitAnd_test(self, ctx: Python3Parser.And_testContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#not_test.
    def visitNot_test(self, ctx: Python3Parser.Not_testContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#comparison.
    def visitComparison(self, ctx: Python3Parser.ComparisonContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#comp_op.
    def visitComp_op(self, ctx: Python3Parser.Comp_opContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#star_expr.
    def visitStar_expr(self, ctx: Python3Parser.Star_exprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#expr.
    def visitExpr(self, ctx: Python3Parser.ExprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#atom_expr.
    def visitAtom_expr(self, ctx: Python3Parser.Atom_exprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#atom.
    def visitAtom(self, ctx: Python3Parser.AtomContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#name.
    def visitName(self, ctx: Python3Parser.NameContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#testlist_comp.
    def visitTestlist_comp(self, ctx: Python3Parser.Testlist_compContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#trailer.
    def visitTrailer(self, ctx: Python3Parser.TrailerContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#subscriptlist.
    def visitSubscriptlist(self, ctx: Python3Parser.SubscriptlistContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#subscript_.
    def visitSubscript_(self, ctx: Python3Parser.Subscript_Context):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#sliceop.
    def visitSliceop(self, ctx: Python3Parser.SliceopContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#exprlist.
    def visitExprlist(self, ctx: Python3Parser.ExprlistContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#testlist.
    def visitTestlist(self, ctx: Python3Parser.TestlistContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#dictorsetmaker.
    def visitDictorsetmaker(self, ctx: Python3Parser.DictorsetmakerContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#classdef.
    def visitClassdef(self, ctx: Python3Parser.ClassdefContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#arglist.
    def visitArglist(self, ctx: Python3Parser.ArglistContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#argument.
    def visitArgument(self, ctx: Python3Parser.ArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#comp_iter.
    def visitComp_iter(self, ctx: Python3Parser.Comp_iterContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#comp_for.
    def visitComp_for(self, ctx: Python3Parser.Comp_forContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#comp_if.
    def visitComp_if(self, ctx: Python3Parser.Comp_ifContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#encoding_decl.
    def visitEncoding_decl(self, ctx: Python3Parser.Encoding_declContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#yield_expr.
    def visitYield_expr(self, ctx: Python3Parser.Yield_exprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#yield_arg.
    def visitYield_arg(self, ctx: Python3Parser.Yield_argContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by Python3Parser#strings.
    def visitStrings(self, ctx: Python3Parser.StringsContext):
        return self.visitChildren(ctx)


del Python3Parser
