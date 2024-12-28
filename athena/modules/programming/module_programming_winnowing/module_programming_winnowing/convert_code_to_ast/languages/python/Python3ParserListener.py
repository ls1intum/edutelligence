# Generated from Python3Parser.g4 by ANTLR 4.13.1
from antlr4 import *
if "." in __name__:
    from .Python3Parser import Python3Parser
else:
    from Python3Parser import Python3Parser

# This class defines a complete listener for a parse tree produced by Python3Parser.
class Python3ParserListener(ParseTreeListener):

    # Enter a parse tree produced by Python3Parser#single_input.
    def enterSingle_input(self, ctx:Python3Parser.Single_inputContext):
        pass

    # Exit a parse tree produced by Python3Parser#single_input.
    def exitSingle_input(self, ctx:Python3Parser.Single_inputContext):
        pass


    # Enter a parse tree produced by Python3Parser#file_input.
    def enterFile_input(self, ctx:Python3Parser.File_inputContext):
        pass

    # Exit a parse tree produced by Python3Parser#file_input.
    def exitFile_input(self, ctx:Python3Parser.File_inputContext):
        pass


    # Enter a parse tree produced by Python3Parser#eval_input.
    def enterEval_input(self, ctx:Python3Parser.Eval_inputContext):
        pass

    # Exit a parse tree produced by Python3Parser#eval_input.
    def exitEval_input(self, ctx:Python3Parser.Eval_inputContext):
        pass


    # Enter a parse tree produced by Python3Parser#decorator.
    def enterDecorator(self, ctx:Python3Parser.DecoratorContext):
        pass

    # Exit a parse tree produced by Python3Parser#decorator.
    def exitDecorator(self, ctx:Python3Parser.DecoratorContext):
        pass


    # Enter a parse tree produced by Python3Parser#decorators.
    def enterDecorators(self, ctx:Python3Parser.DecoratorsContext):
        pass

    # Exit a parse tree produced by Python3Parser#decorators.
    def exitDecorators(self, ctx:Python3Parser.DecoratorsContext):
        pass


    # Enter a parse tree produced by Python3Parser#decorated.
    def enterDecorated(self, ctx:Python3Parser.DecoratedContext):
        pass

    # Exit a parse tree produced by Python3Parser#decorated.
    def exitDecorated(self, ctx:Python3Parser.DecoratedContext):
        pass


    # Enter a parse tree produced by Python3Parser#async_funcdef.
    def enterAsync_funcdef(self, ctx:Python3Parser.Async_funcdefContext):
        pass

    # Exit a parse tree produced by Python3Parser#async_funcdef.
    def exitAsync_funcdef(self, ctx:Python3Parser.Async_funcdefContext):
        pass


    # Enter a parse tree produced by Python3Parser#funcdef.
    def enterFuncdef(self, ctx:Python3Parser.FuncdefContext):
        pass

    # Exit a parse tree produced by Python3Parser#funcdef.
    def exitFuncdef(self, ctx:Python3Parser.FuncdefContext):
        pass


    # Enter a parse tree produced by Python3Parser#parameters.
    def enterParameters(self, ctx:Python3Parser.ParametersContext):
        pass

    # Exit a parse tree produced by Python3Parser#parameters.
    def exitParameters(self, ctx:Python3Parser.ParametersContext):
        pass


    # Enter a parse tree produced by Python3Parser#typedargslist.
    def enterTypedargslist(self, ctx:Python3Parser.TypedargslistContext):
        pass

    # Exit a parse tree produced by Python3Parser#typedargslist.
    def exitTypedargslist(self, ctx:Python3Parser.TypedargslistContext):
        pass


    # Enter a parse tree produced by Python3Parser#tfpdef.
    def enterTfpdef(self, ctx:Python3Parser.TfpdefContext):
        pass

    # Exit a parse tree produced by Python3Parser#tfpdef.
    def exitTfpdef(self, ctx:Python3Parser.TfpdefContext):
        pass


    # Enter a parse tree produced by Python3Parser#varargslist.
    def enterVarargslist(self, ctx:Python3Parser.VarargslistContext):
        pass

    # Exit a parse tree produced by Python3Parser#varargslist.
    def exitVarargslist(self, ctx:Python3Parser.VarargslistContext):
        pass


    # Enter a parse tree produced by Python3Parser#vfpdef.
    def enterVfpdef(self, ctx:Python3Parser.VfpdefContext):
        pass

    # Exit a parse tree produced by Python3Parser#vfpdef.
    def exitVfpdef(self, ctx:Python3Parser.VfpdefContext):
        pass


    # Enter a parse tree produced by Python3Parser#stmt.
    def enterStmt(self, ctx:Python3Parser.StmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#stmt.
    def exitStmt(self, ctx:Python3Parser.StmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#simple_stmts.
    def enterSimple_stmts(self, ctx:Python3Parser.Simple_stmtsContext):
        pass

    # Exit a parse tree produced by Python3Parser#simple_stmts.
    def exitSimple_stmts(self, ctx:Python3Parser.Simple_stmtsContext):
        pass


    # Enter a parse tree produced by Python3Parser#simple_stmt.
    def enterSimple_stmt(self, ctx:Python3Parser.Simple_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#simple_stmt.
    def exitSimple_stmt(self, ctx:Python3Parser.Simple_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#expr_stmt.
    def enterExpr_stmt(self, ctx:Python3Parser.Expr_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#expr_stmt.
    def exitExpr_stmt(self, ctx:Python3Parser.Expr_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#annassign.
    def enterAnnassign(self, ctx:Python3Parser.AnnassignContext):
        pass

    # Exit a parse tree produced by Python3Parser#annassign.
    def exitAnnassign(self, ctx:Python3Parser.AnnassignContext):
        pass


    # Enter a parse tree produced by Python3Parser#testlist_star_expr.
    def enterTestlist_star_expr(self, ctx:Python3Parser.Testlist_star_exprContext):
        pass

    # Exit a parse tree produced by Python3Parser#testlist_star_expr.
    def exitTestlist_star_expr(self, ctx:Python3Parser.Testlist_star_exprContext):
        pass


    # Enter a parse tree produced by Python3Parser#augassign.
    def enterAugassign(self, ctx:Python3Parser.AugassignContext):
        pass

    # Exit a parse tree produced by Python3Parser#augassign.
    def exitAugassign(self, ctx:Python3Parser.AugassignContext):
        pass


    # Enter a parse tree produced by Python3Parser#del_stmt.
    def enterDel_stmt(self, ctx:Python3Parser.Del_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#del_stmt.
    def exitDel_stmt(self, ctx:Python3Parser.Del_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#pass_stmt.
    def enterPass_stmt(self, ctx:Python3Parser.Pass_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#pass_stmt.
    def exitPass_stmt(self, ctx:Python3Parser.Pass_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#flow_stmt.
    def enterFlow_stmt(self, ctx:Python3Parser.Flow_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#flow_stmt.
    def exitFlow_stmt(self, ctx:Python3Parser.Flow_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#break_stmt.
    def enterBreak_stmt(self, ctx:Python3Parser.Break_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#break_stmt.
    def exitBreak_stmt(self, ctx:Python3Parser.Break_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#continue_stmt.
    def enterContinue_stmt(self, ctx:Python3Parser.Continue_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#continue_stmt.
    def exitContinue_stmt(self, ctx:Python3Parser.Continue_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#return_stmt.
    def enterReturn_stmt(self, ctx:Python3Parser.Return_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#return_stmt.
    def exitReturn_stmt(self, ctx:Python3Parser.Return_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#yield_stmt.
    def enterYield_stmt(self, ctx:Python3Parser.Yield_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#yield_stmt.
    def exitYield_stmt(self, ctx:Python3Parser.Yield_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#raise_stmt.
    def enterRaise_stmt(self, ctx:Python3Parser.Raise_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#raise_stmt.
    def exitRaise_stmt(self, ctx:Python3Parser.Raise_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#import_stmt.
    def enterImport_stmt(self, ctx:Python3Parser.Import_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#import_stmt.
    def exitImport_stmt(self, ctx:Python3Parser.Import_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#import_name.
    def enterImport_name(self, ctx:Python3Parser.Import_nameContext):
        pass

    # Exit a parse tree produced by Python3Parser#import_name.
    def exitImport_name(self, ctx:Python3Parser.Import_nameContext):
        pass


    # Enter a parse tree produced by Python3Parser#import_from.
    def enterImport_from(self, ctx:Python3Parser.Import_fromContext):
        pass

    # Exit a parse tree produced by Python3Parser#import_from.
    def exitImport_from(self, ctx:Python3Parser.Import_fromContext):
        pass


    # Enter a parse tree produced by Python3Parser#import_as_name.
    def enterImport_as_name(self, ctx:Python3Parser.Import_as_nameContext):
        pass

    # Exit a parse tree produced by Python3Parser#import_as_name.
    def exitImport_as_name(self, ctx:Python3Parser.Import_as_nameContext):
        pass


    # Enter a parse tree produced by Python3Parser#dotted_as_name.
    def enterDotted_as_name(self, ctx:Python3Parser.Dotted_as_nameContext):
        pass

    # Exit a parse tree produced by Python3Parser#dotted_as_name.
    def exitDotted_as_name(self, ctx:Python3Parser.Dotted_as_nameContext):
        pass


    # Enter a parse tree produced by Python3Parser#import_as_names.
    def enterImport_as_names(self, ctx:Python3Parser.Import_as_namesContext):
        pass

    # Exit a parse tree produced by Python3Parser#import_as_names.
    def exitImport_as_names(self, ctx:Python3Parser.Import_as_namesContext):
        pass


    # Enter a parse tree produced by Python3Parser#dotted_as_names.
    def enterDotted_as_names(self, ctx:Python3Parser.Dotted_as_namesContext):
        pass

    # Exit a parse tree produced by Python3Parser#dotted_as_names.
    def exitDotted_as_names(self, ctx:Python3Parser.Dotted_as_namesContext):
        pass


    # Enter a parse tree produced by Python3Parser#dotted_name.
    def enterDotted_name(self, ctx:Python3Parser.Dotted_nameContext):
        pass

    # Exit a parse tree produced by Python3Parser#dotted_name.
    def exitDotted_name(self, ctx:Python3Parser.Dotted_nameContext):
        pass


    # Enter a parse tree produced by Python3Parser#global_stmt.
    def enterGlobal_stmt(self, ctx:Python3Parser.Global_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#global_stmt.
    def exitGlobal_stmt(self, ctx:Python3Parser.Global_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#nonlocal_stmt.
    def enterNonlocal_stmt(self, ctx:Python3Parser.Nonlocal_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#nonlocal_stmt.
    def exitNonlocal_stmt(self, ctx:Python3Parser.Nonlocal_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#assert_stmt.
    def enterAssert_stmt(self, ctx:Python3Parser.Assert_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#assert_stmt.
    def exitAssert_stmt(self, ctx:Python3Parser.Assert_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#compound_stmt.
    def enterCompound_stmt(self, ctx:Python3Parser.Compound_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#compound_stmt.
    def exitCompound_stmt(self, ctx:Python3Parser.Compound_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#async_stmt.
    def enterAsync_stmt(self, ctx:Python3Parser.Async_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#async_stmt.
    def exitAsync_stmt(self, ctx:Python3Parser.Async_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#if_stmt.
    def enterIf_stmt(self, ctx:Python3Parser.If_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#if_stmt.
    def exitIf_stmt(self, ctx:Python3Parser.If_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#while_stmt.
    def enterWhile_stmt(self, ctx:Python3Parser.While_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#while_stmt.
    def exitWhile_stmt(self, ctx:Python3Parser.While_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#for_stmt.
    def enterFor_stmt(self, ctx:Python3Parser.For_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#for_stmt.
    def exitFor_stmt(self, ctx:Python3Parser.For_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#try_stmt.
    def enterTry_stmt(self, ctx:Python3Parser.Try_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#try_stmt.
    def exitTry_stmt(self, ctx:Python3Parser.Try_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#with_stmt.
    def enterWith_stmt(self, ctx:Python3Parser.With_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#with_stmt.
    def exitWith_stmt(self, ctx:Python3Parser.With_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#with_item.
    def enterWith_item(self, ctx:Python3Parser.With_itemContext):
        pass

    # Exit a parse tree produced by Python3Parser#with_item.
    def exitWith_item(self, ctx:Python3Parser.With_itemContext):
        pass


    # Enter a parse tree produced by Python3Parser#except_clause.
    def enterExcept_clause(self, ctx:Python3Parser.Except_clauseContext):
        pass

    # Exit a parse tree produced by Python3Parser#except_clause.
    def exitExcept_clause(self, ctx:Python3Parser.Except_clauseContext):
        pass


    # Enter a parse tree produced by Python3Parser#block.
    def enterBlock(self, ctx:Python3Parser.BlockContext):
        pass

    # Exit a parse tree produced by Python3Parser#block.
    def exitBlock(self, ctx:Python3Parser.BlockContext):
        pass


    # Enter a parse tree produced by Python3Parser#match_stmt.
    def enterMatch_stmt(self, ctx:Python3Parser.Match_stmtContext):
        pass

    # Exit a parse tree produced by Python3Parser#match_stmt.
    def exitMatch_stmt(self, ctx:Python3Parser.Match_stmtContext):
        pass


    # Enter a parse tree produced by Python3Parser#subject_expr.
    def enterSubject_expr(self, ctx:Python3Parser.Subject_exprContext):
        pass

    # Exit a parse tree produced by Python3Parser#subject_expr.
    def exitSubject_expr(self, ctx:Python3Parser.Subject_exprContext):
        pass


    # Enter a parse tree produced by Python3Parser#star_named_expressions.
    def enterStar_named_expressions(self, ctx:Python3Parser.Star_named_expressionsContext):
        pass

    # Exit a parse tree produced by Python3Parser#star_named_expressions.
    def exitStar_named_expressions(self, ctx:Python3Parser.Star_named_expressionsContext):
        pass


    # Enter a parse tree produced by Python3Parser#star_named_expression.
    def enterStar_named_expression(self, ctx:Python3Parser.Star_named_expressionContext):
        pass

    # Exit a parse tree produced by Python3Parser#star_named_expression.
    def exitStar_named_expression(self, ctx:Python3Parser.Star_named_expressionContext):
        pass


    # Enter a parse tree produced by Python3Parser#case_block.
    def enterCase_block(self, ctx:Python3Parser.Case_blockContext):
        pass

    # Exit a parse tree produced by Python3Parser#case_block.
    def exitCase_block(self, ctx:Python3Parser.Case_blockContext):
        pass


    # Enter a parse tree produced by Python3Parser#guard.
    def enterGuard(self, ctx:Python3Parser.GuardContext):
        pass

    # Exit a parse tree produced by Python3Parser#guard.
    def exitGuard(self, ctx:Python3Parser.GuardContext):
        pass


    # Enter a parse tree produced by Python3Parser#patterns.
    def enterPatterns(self, ctx:Python3Parser.PatternsContext):
        pass

    # Exit a parse tree produced by Python3Parser#patterns.
    def exitPatterns(self, ctx:Python3Parser.PatternsContext):
        pass


    # Enter a parse tree produced by Python3Parser#pattern.
    def enterPattern(self, ctx:Python3Parser.PatternContext):
        pass

    # Exit a parse tree produced by Python3Parser#pattern.
    def exitPattern(self, ctx:Python3Parser.PatternContext):
        pass


    # Enter a parse tree produced by Python3Parser#as_pattern.
    def enterAs_pattern(self, ctx:Python3Parser.As_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#as_pattern.
    def exitAs_pattern(self, ctx:Python3Parser.As_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#or_pattern.
    def enterOr_pattern(self, ctx:Python3Parser.Or_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#or_pattern.
    def exitOr_pattern(self, ctx:Python3Parser.Or_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#closed_pattern.
    def enterClosed_pattern(self, ctx:Python3Parser.Closed_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#closed_pattern.
    def exitClosed_pattern(self, ctx:Python3Parser.Closed_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#literal_pattern.
    def enterLiteral_pattern(self, ctx:Python3Parser.Literal_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#literal_pattern.
    def exitLiteral_pattern(self, ctx:Python3Parser.Literal_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#literal_expr.
    def enterLiteral_expr(self, ctx:Python3Parser.Literal_exprContext):
        pass

    # Exit a parse tree produced by Python3Parser#literal_expr.
    def exitLiteral_expr(self, ctx:Python3Parser.Literal_exprContext):
        pass


    # Enter a parse tree produced by Python3Parser#complex_number.
    def enterComplex_number(self, ctx:Python3Parser.Complex_numberContext):
        pass

    # Exit a parse tree produced by Python3Parser#complex_number.
    def exitComplex_number(self, ctx:Python3Parser.Complex_numberContext):
        pass


    # Enter a parse tree produced by Python3Parser#signed_number.
    def enterSigned_number(self, ctx:Python3Parser.Signed_numberContext):
        pass

    # Exit a parse tree produced by Python3Parser#signed_number.
    def exitSigned_number(self, ctx:Python3Parser.Signed_numberContext):
        pass


    # Enter a parse tree produced by Python3Parser#signed_real_number.
    def enterSigned_real_number(self, ctx:Python3Parser.Signed_real_numberContext):
        pass

    # Exit a parse tree produced by Python3Parser#signed_real_number.
    def exitSigned_real_number(self, ctx:Python3Parser.Signed_real_numberContext):
        pass


    # Enter a parse tree produced by Python3Parser#real_number.
    def enterReal_number(self, ctx:Python3Parser.Real_numberContext):
        pass

    # Exit a parse tree produced by Python3Parser#real_number.
    def exitReal_number(self, ctx:Python3Parser.Real_numberContext):
        pass


    # Enter a parse tree produced by Python3Parser#imaginary_number.
    def enterImaginary_number(self, ctx:Python3Parser.Imaginary_numberContext):
        pass

    # Exit a parse tree produced by Python3Parser#imaginary_number.
    def exitImaginary_number(self, ctx:Python3Parser.Imaginary_numberContext):
        pass


    # Enter a parse tree produced by Python3Parser#capture_pattern.
    def enterCapture_pattern(self, ctx:Python3Parser.Capture_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#capture_pattern.
    def exitCapture_pattern(self, ctx:Python3Parser.Capture_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#pattern_capture_target.
    def enterPattern_capture_target(self, ctx:Python3Parser.Pattern_capture_targetContext):
        pass

    # Exit a parse tree produced by Python3Parser#pattern_capture_target.
    def exitPattern_capture_target(self, ctx:Python3Parser.Pattern_capture_targetContext):
        pass


    # Enter a parse tree produced by Python3Parser#wildcard_pattern.
    def enterWildcard_pattern(self, ctx:Python3Parser.Wildcard_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#wildcard_pattern.
    def exitWildcard_pattern(self, ctx:Python3Parser.Wildcard_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#value_pattern.
    def enterValue_pattern(self, ctx:Python3Parser.Value_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#value_pattern.
    def exitValue_pattern(self, ctx:Python3Parser.Value_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#attr.
    def enterAttr(self, ctx:Python3Parser.AttrContext):
        pass

    # Exit a parse tree produced by Python3Parser#attr.
    def exitAttr(self, ctx:Python3Parser.AttrContext):
        pass


    # Enter a parse tree produced by Python3Parser#name_or_attr.
    def enterName_or_attr(self, ctx:Python3Parser.Name_or_attrContext):
        pass

    # Exit a parse tree produced by Python3Parser#name_or_attr.
    def exitName_or_attr(self, ctx:Python3Parser.Name_or_attrContext):
        pass


    # Enter a parse tree produced by Python3Parser#group_pattern.
    def enterGroup_pattern(self, ctx:Python3Parser.Group_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#group_pattern.
    def exitGroup_pattern(self, ctx:Python3Parser.Group_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#sequence_pattern.
    def enterSequence_pattern(self, ctx:Python3Parser.Sequence_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#sequence_pattern.
    def exitSequence_pattern(self, ctx:Python3Parser.Sequence_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#open_sequence_pattern.
    def enterOpen_sequence_pattern(self, ctx:Python3Parser.Open_sequence_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#open_sequence_pattern.
    def exitOpen_sequence_pattern(self, ctx:Python3Parser.Open_sequence_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#maybe_sequence_pattern.
    def enterMaybe_sequence_pattern(self, ctx:Python3Parser.Maybe_sequence_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#maybe_sequence_pattern.
    def exitMaybe_sequence_pattern(self, ctx:Python3Parser.Maybe_sequence_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#maybe_star_pattern.
    def enterMaybe_star_pattern(self, ctx:Python3Parser.Maybe_star_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#maybe_star_pattern.
    def exitMaybe_star_pattern(self, ctx:Python3Parser.Maybe_star_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#star_pattern.
    def enterStar_pattern(self, ctx:Python3Parser.Star_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#star_pattern.
    def exitStar_pattern(self, ctx:Python3Parser.Star_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#mapping_pattern.
    def enterMapping_pattern(self, ctx:Python3Parser.Mapping_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#mapping_pattern.
    def exitMapping_pattern(self, ctx:Python3Parser.Mapping_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#items_pattern.
    def enterItems_pattern(self, ctx:Python3Parser.Items_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#items_pattern.
    def exitItems_pattern(self, ctx:Python3Parser.Items_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#key_value_pattern.
    def enterKey_value_pattern(self, ctx:Python3Parser.Key_value_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#key_value_pattern.
    def exitKey_value_pattern(self, ctx:Python3Parser.Key_value_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#double_star_pattern.
    def enterDouble_star_pattern(self, ctx:Python3Parser.Double_star_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#double_star_pattern.
    def exitDouble_star_pattern(self, ctx:Python3Parser.Double_star_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#class_pattern.
    def enterClass_pattern(self, ctx:Python3Parser.Class_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#class_pattern.
    def exitClass_pattern(self, ctx:Python3Parser.Class_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#positional_patterns.
    def enterPositional_patterns(self, ctx:Python3Parser.Positional_patternsContext):
        pass

    # Exit a parse tree produced by Python3Parser#positional_patterns.
    def exitPositional_patterns(self, ctx:Python3Parser.Positional_patternsContext):
        pass


    # Enter a parse tree produced by Python3Parser#keyword_patterns.
    def enterKeyword_patterns(self, ctx:Python3Parser.Keyword_patternsContext):
        pass

    # Exit a parse tree produced by Python3Parser#keyword_patterns.
    def exitKeyword_patterns(self, ctx:Python3Parser.Keyword_patternsContext):
        pass


    # Enter a parse tree produced by Python3Parser#keyword_pattern.
    def enterKeyword_pattern(self, ctx:Python3Parser.Keyword_patternContext):
        pass

    # Exit a parse tree produced by Python3Parser#keyword_pattern.
    def exitKeyword_pattern(self, ctx:Python3Parser.Keyword_patternContext):
        pass


    # Enter a parse tree produced by Python3Parser#test.
    def enterTest(self, ctx:Python3Parser.TestContext):
        pass

    # Exit a parse tree produced by Python3Parser#test.
    def exitTest(self, ctx:Python3Parser.TestContext):
        pass


    # Enter a parse tree produced by Python3Parser#test_nocond.
    def enterTest_nocond(self, ctx:Python3Parser.Test_nocondContext):
        pass

    # Exit a parse tree produced by Python3Parser#test_nocond.
    def exitTest_nocond(self, ctx:Python3Parser.Test_nocondContext):
        pass


    # Enter a parse tree produced by Python3Parser#lambdef.
    def enterLambdef(self, ctx:Python3Parser.LambdefContext):
        pass

    # Exit a parse tree produced by Python3Parser#lambdef.
    def exitLambdef(self, ctx:Python3Parser.LambdefContext):
        pass


    # Enter a parse tree produced by Python3Parser#lambdef_nocond.
    def enterLambdef_nocond(self, ctx:Python3Parser.Lambdef_nocondContext):
        pass

    # Exit a parse tree produced by Python3Parser#lambdef_nocond.
    def exitLambdef_nocond(self, ctx:Python3Parser.Lambdef_nocondContext):
        pass


    # Enter a parse tree produced by Python3Parser#or_test.
    def enterOr_test(self, ctx:Python3Parser.Or_testContext):
        pass

    # Exit a parse tree produced by Python3Parser#or_test.
    def exitOr_test(self, ctx:Python3Parser.Or_testContext):
        pass


    # Enter a parse tree produced by Python3Parser#and_test.
    def enterAnd_test(self, ctx:Python3Parser.And_testContext):
        pass

    # Exit a parse tree produced by Python3Parser#and_test.
    def exitAnd_test(self, ctx:Python3Parser.And_testContext):
        pass


    # Enter a parse tree produced by Python3Parser#not_test.
    def enterNot_test(self, ctx:Python3Parser.Not_testContext):
        pass

    # Exit a parse tree produced by Python3Parser#not_test.
    def exitNot_test(self, ctx:Python3Parser.Not_testContext):
        pass


    # Enter a parse tree produced by Python3Parser#comparison.
    def enterComparison(self, ctx:Python3Parser.ComparisonContext):
        pass

    # Exit a parse tree produced by Python3Parser#comparison.
    def exitComparison(self, ctx:Python3Parser.ComparisonContext):
        pass


    # Enter a parse tree produced by Python3Parser#comp_op.
    def enterComp_op(self, ctx:Python3Parser.Comp_opContext):
        pass

    # Exit a parse tree produced by Python3Parser#comp_op.
    def exitComp_op(self, ctx:Python3Parser.Comp_opContext):
        pass


    # Enter a parse tree produced by Python3Parser#star_expr.
    def enterStar_expr(self, ctx:Python3Parser.Star_exprContext):
        pass

    # Exit a parse tree produced by Python3Parser#star_expr.
    def exitStar_expr(self, ctx:Python3Parser.Star_exprContext):
        pass


    # Enter a parse tree produced by Python3Parser#expr.
    def enterExpr(self, ctx:Python3Parser.ExprContext):
        pass

    # Exit a parse tree produced by Python3Parser#expr.
    def exitExpr(self, ctx:Python3Parser.ExprContext):
        pass


    # Enter a parse tree produced by Python3Parser#atom_expr.
    def enterAtom_expr(self, ctx:Python3Parser.Atom_exprContext):
        pass

    # Exit a parse tree produced by Python3Parser#atom_expr.
    def exitAtom_expr(self, ctx:Python3Parser.Atom_exprContext):
        pass


    # Enter a parse tree produced by Python3Parser#atom.
    def enterAtom(self, ctx:Python3Parser.AtomContext):
        pass

    # Exit a parse tree produced by Python3Parser#atom.
    def exitAtom(self, ctx:Python3Parser.AtomContext):
        pass


    # Enter a parse tree produced by Python3Parser#name.
    def enterName(self, ctx:Python3Parser.NameContext):
        pass

    # Exit a parse tree produced by Python3Parser#name.
    def exitName(self, ctx:Python3Parser.NameContext):
        pass


    # Enter a parse tree produced by Python3Parser#testlist_comp.
    def enterTestlist_comp(self, ctx:Python3Parser.Testlist_compContext):
        pass

    # Exit a parse tree produced by Python3Parser#testlist_comp.
    def exitTestlist_comp(self, ctx:Python3Parser.Testlist_compContext):
        pass


    # Enter a parse tree produced by Python3Parser#trailer.
    def enterTrailer(self, ctx:Python3Parser.TrailerContext):
        pass

    # Exit a parse tree produced by Python3Parser#trailer.
    def exitTrailer(self, ctx:Python3Parser.TrailerContext):
        pass


    # Enter a parse tree produced by Python3Parser#subscriptlist.
    def enterSubscriptlist(self, ctx:Python3Parser.SubscriptlistContext):
        pass

    # Exit a parse tree produced by Python3Parser#subscriptlist.
    def exitSubscriptlist(self, ctx:Python3Parser.SubscriptlistContext):
        pass


    # Enter a parse tree produced by Python3Parser#subscript_.
    def enterSubscript_(self, ctx:Python3Parser.Subscript_Context):
        pass

    # Exit a parse tree produced by Python3Parser#subscript_.
    def exitSubscript_(self, ctx:Python3Parser.Subscript_Context):
        pass


    # Enter a parse tree produced by Python3Parser#sliceop.
    def enterSliceop(self, ctx:Python3Parser.SliceopContext):
        pass

    # Exit a parse tree produced by Python3Parser#sliceop.
    def exitSliceop(self, ctx:Python3Parser.SliceopContext):
        pass


    # Enter a parse tree produced by Python3Parser#exprlist.
    def enterExprlist(self, ctx:Python3Parser.ExprlistContext):
        pass

    # Exit a parse tree produced by Python3Parser#exprlist.
    def exitExprlist(self, ctx:Python3Parser.ExprlistContext):
        pass


    # Enter a parse tree produced by Python3Parser#testlist.
    def enterTestlist(self, ctx:Python3Parser.TestlistContext):
        pass

    # Exit a parse tree produced by Python3Parser#testlist.
    def exitTestlist(self, ctx:Python3Parser.TestlistContext):
        pass


    # Enter a parse tree produced by Python3Parser#dictorsetmaker.
    def enterDictorsetmaker(self, ctx:Python3Parser.DictorsetmakerContext):
        pass

    # Exit a parse tree produced by Python3Parser#dictorsetmaker.
    def exitDictorsetmaker(self, ctx:Python3Parser.DictorsetmakerContext):
        pass


    # Enter a parse tree produced by Python3Parser#classdef.
    def enterClassdef(self, ctx:Python3Parser.ClassdefContext):
        pass

    # Exit a parse tree produced by Python3Parser#classdef.
    def exitClassdef(self, ctx:Python3Parser.ClassdefContext):
        pass


    # Enter a parse tree produced by Python3Parser#arglist.
    def enterArglist(self, ctx:Python3Parser.ArglistContext):
        pass

    # Exit a parse tree produced by Python3Parser#arglist.
    def exitArglist(self, ctx:Python3Parser.ArglistContext):
        pass


    # Enter a parse tree produced by Python3Parser#argument.
    def enterArgument(self, ctx:Python3Parser.ArgumentContext):
        pass

    # Exit a parse tree produced by Python3Parser#argument.
    def exitArgument(self, ctx:Python3Parser.ArgumentContext):
        pass


    # Enter a parse tree produced by Python3Parser#comp_iter.
    def enterComp_iter(self, ctx:Python3Parser.Comp_iterContext):
        pass

    # Exit a parse tree produced by Python3Parser#comp_iter.
    def exitComp_iter(self, ctx:Python3Parser.Comp_iterContext):
        pass


    # Enter a parse tree produced by Python3Parser#comp_for.
    def enterComp_for(self, ctx:Python3Parser.Comp_forContext):
        pass

    # Exit a parse tree produced by Python3Parser#comp_for.
    def exitComp_for(self, ctx:Python3Parser.Comp_forContext):
        pass


    # Enter a parse tree produced by Python3Parser#comp_if.
    def enterComp_if(self, ctx:Python3Parser.Comp_ifContext):
        pass

    # Exit a parse tree produced by Python3Parser#comp_if.
    def exitComp_if(self, ctx:Python3Parser.Comp_ifContext):
        pass


    # Enter a parse tree produced by Python3Parser#encoding_decl.
    def enterEncoding_decl(self, ctx:Python3Parser.Encoding_declContext):
        pass

    # Exit a parse tree produced by Python3Parser#encoding_decl.
    def exitEncoding_decl(self, ctx:Python3Parser.Encoding_declContext):
        pass


    # Enter a parse tree produced by Python3Parser#yield_expr.
    def enterYield_expr(self, ctx:Python3Parser.Yield_exprContext):
        pass

    # Exit a parse tree produced by Python3Parser#yield_expr.
    def exitYield_expr(self, ctx:Python3Parser.Yield_exprContext):
        pass


    # Enter a parse tree produced by Python3Parser#yield_arg.
    def enterYield_arg(self, ctx:Python3Parser.Yield_argContext):
        pass

    # Exit a parse tree produced by Python3Parser#yield_arg.
    def exitYield_arg(self, ctx:Python3Parser.Yield_argContext):
        pass


    # Enter a parse tree produced by Python3Parser#strings.
    def enterStrings(self, ctx:Python3Parser.StringsContext):
        pass

    # Exit a parse tree produced by Python3Parser#strings.
    def exitStrings(self, ctx:Python3Parser.StringsContext):
        pass



del Python3Parser