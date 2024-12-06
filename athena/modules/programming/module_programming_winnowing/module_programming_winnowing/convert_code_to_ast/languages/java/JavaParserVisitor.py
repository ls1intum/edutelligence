# Generated from Java20Parser.g4 by ANTLR 4.13.1
from antlr4 import *

if "." in __name__:
    from module_programming_winnowing.convert_code_to_ast.languages.java.JavaParser import Java20Parser
else:
    from module_programming_winnowing.convert_code_to_ast.languages.java.JavaParser import Java20Parser


# This class defines a complete generic visitor for a parse tree produced by Java20Parser.

class Java20ParserVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by Java20Parser#start_.
    def visitStart_(self, ctx:Java20Parser.Start_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#literal.
    def visitLiteral(self, ctx:Java20Parser.LiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeIdentifier.
    def visitTypeIdentifier(self, ctx:Java20Parser.TypeIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unqualifiedMethodIdentifier.
    def visitUnqualifiedMethodIdentifier(self, ctx:Java20Parser.UnqualifiedMethodIdentifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#primitiveType.
    def visitPrimitiveType(self, ctx:Java20Parser.PrimitiveTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#numericType.
    def visitNumericType(self, ctx:Java20Parser.NumericTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#integralType.
    def visitIntegralType(self, ctx:Java20Parser.IntegralTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#floatingPointType.
    def visitFloatingPointType(self, ctx:Java20Parser.FloatingPointTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#referenceType.
    def visitReferenceType(self, ctx:Java20Parser.ReferenceTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#coit.
    def visitCoit(self, ctx:Java20Parser.CoitContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classOrInterfaceType.
    def visitClassOrInterfaceType(self, ctx:Java20Parser.ClassOrInterfaceTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classType.
    def visitClassType(self, ctx:Java20Parser.ClassTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceType.
    def visitInterfaceType(self, ctx:Java20Parser.InterfaceTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeVariable.
    def visitTypeVariable(self, ctx:Java20Parser.TypeVariableContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#arrayType.
    def visitArrayType(self, ctx:Java20Parser.ArrayTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#dims.
    def visitDims(self, ctx:Java20Parser.DimsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeParameter.
    def visitTypeParameter(self, ctx:Java20Parser.TypeParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeParameterModifier.
    def visitTypeParameterModifier(self, ctx:Java20Parser.TypeParameterModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeBound.
    def visitTypeBound(self, ctx:Java20Parser.TypeBoundContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#additionalBound.
    def visitAdditionalBound(self, ctx:Java20Parser.AdditionalBoundContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeArguments.
    def visitTypeArguments(self, ctx:Java20Parser.TypeArgumentsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeArgumentList.
    def visitTypeArgumentList(self, ctx:Java20Parser.TypeArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeArgument.
    def visitTypeArgument(self, ctx:Java20Parser.TypeArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#wildcard.
    def visitWildcard(self, ctx:Java20Parser.WildcardContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#wildcardBounds.
    def visitWildcardBounds(self, ctx:Java20Parser.WildcardBoundsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#moduleName.
    def visitModuleName(self, ctx:Java20Parser.ModuleNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#packageName.
    def visitPackageName(self, ctx:Java20Parser.PackageNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeName.
    def visitTypeName(self, ctx:Java20Parser.TypeNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#packageOrTypeName.
    def visitPackageOrTypeName(self, ctx:Java20Parser.PackageOrTypeNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#expressionName.
    def visitExpressionName(self, ctx:Java20Parser.ExpressionNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#methodName.
    def visitMethodName(self, ctx:Java20Parser.MethodNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#ambiguousName.
    def visitAmbiguousName(self, ctx:Java20Parser.AmbiguousNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#compilationUnit.
    def visitCompilationUnit(self, ctx:Java20Parser.CompilationUnitContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#ordinaryCompilationUnit.
    def visitOrdinaryCompilationUnit(self, ctx:Java20Parser.OrdinaryCompilationUnitContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#modularCompilationUnit.
    def visitModularCompilationUnit(self, ctx:Java20Parser.ModularCompilationUnitContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#packageDeclaration.
    def visitPackageDeclaration(self, ctx:Java20Parser.PackageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#packageModifier.
    def visitPackageModifier(self, ctx:Java20Parser.PackageModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#importDeclaration.
    def visitImportDeclaration(self, ctx:Java20Parser.ImportDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#singleTypeImportDeclaration.
    def visitSingleTypeImportDeclaration(self, ctx:Java20Parser.SingleTypeImportDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeImportOnDemandDeclaration.
    def visitTypeImportOnDemandDeclaration(self, ctx:Java20Parser.TypeImportOnDemandDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#singleStaticImportDeclaration.
    def visitSingleStaticImportDeclaration(self, ctx:Java20Parser.SingleStaticImportDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#staticImportOnDemandDeclaration.
    def visitStaticImportOnDemandDeclaration(self, ctx:Java20Parser.StaticImportOnDemandDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#topLevelClassOrInterfaceDeclaration.
    def visitTopLevelClassOrInterfaceDeclaration(self, ctx:Java20Parser.TopLevelClassOrInterfaceDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#moduleDeclaration.
    def visitModuleDeclaration(self, ctx:Java20Parser.ModuleDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#moduleDirective.
    def visitModuleDirective(self, ctx:Java20Parser.ModuleDirectiveContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#requiresModifier.
    def visitRequiresModifier(self, ctx:Java20Parser.RequiresModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classDeclaration.
    def visitClassDeclaration(self, ctx:Java20Parser.ClassDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#normalClassDeclaration.
    def visitNormalClassDeclaration(self, ctx:Java20Parser.NormalClassDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classModifier.
    def visitClassModifier(self, ctx:Java20Parser.ClassModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeParameters.
    def visitTypeParameters(self, ctx:Java20Parser.TypeParametersContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeParameterList.
    def visitTypeParameterList(self, ctx:Java20Parser.TypeParameterListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classExtends.
    def visitClassExtends(self, ctx:Java20Parser.ClassExtendsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classImplements.
    def visitClassImplements(self, ctx:Java20Parser.ClassImplementsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceTypeList.
    def visitInterfaceTypeList(self, ctx:Java20Parser.InterfaceTypeListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classPermits.
    def visitClassPermits(self, ctx:Java20Parser.ClassPermitsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classBody.
    def visitClassBody(self, ctx:Java20Parser.ClassBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classBodyDeclaration.
    def visitClassBodyDeclaration(self, ctx:Java20Parser.ClassBodyDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classMemberDeclaration.
    def visitClassMemberDeclaration(self, ctx:Java20Parser.ClassMemberDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#fieldDeclaration.
    def visitFieldDeclaration(self, ctx:Java20Parser.FieldDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#fieldModifier.
    def visitFieldModifier(self, ctx:Java20Parser.FieldModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableDeclaratorList.
    def visitVariableDeclaratorList(self, ctx:Java20Parser.VariableDeclaratorListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableDeclarator.
    def visitVariableDeclarator(self, ctx:Java20Parser.VariableDeclaratorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableDeclaratorId.
    def visitVariableDeclaratorId(self, ctx:Java20Parser.VariableDeclaratorIdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableInitializer.
    def visitVariableInitializer(self, ctx:Java20Parser.VariableInitializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unannType.
    def visitUnannType(self, ctx:Java20Parser.UnannTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unannPrimitiveType.
    def visitUnannPrimitiveType(self, ctx:Java20Parser.UnannPrimitiveTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unannReferenceType.
    def visitUnannReferenceType(self, ctx:Java20Parser.UnannReferenceTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unannClassOrInterfaceType.
    def visitUnannClassOrInterfaceType(self, ctx:Java20Parser.UnannClassOrInterfaceTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#uCOIT.
    def visitUCOIT(self, ctx:Java20Parser.UCOITContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unannClassType.
    def visitUnannClassType(self, ctx:Java20Parser.UnannClassTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unannInterfaceType.
    def visitUnannInterfaceType(self, ctx:Java20Parser.UnannInterfaceTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unannTypeVariable.
    def visitUnannTypeVariable(self, ctx:Java20Parser.UnannTypeVariableContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unannArrayType.
    def visitUnannArrayType(self, ctx:Java20Parser.UnannArrayTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#methodDeclaration.
    def visitMethodDeclaration(self, ctx:Java20Parser.MethodDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#methodModifier.
    def visitMethodModifier(self, ctx:Java20Parser.MethodModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#methodHeader.
    def visitMethodHeader(self, ctx:Java20Parser.MethodHeaderContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#result.
    def visitResult(self, ctx:Java20Parser.ResultContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#methodDeclarator.
    def visitMethodDeclarator(self, ctx:Java20Parser.MethodDeclaratorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#receiverParameter.
    def visitReceiverParameter(self, ctx:Java20Parser.ReceiverParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#formalParameterList.
    def visitFormalParameterList(self, ctx:Java20Parser.FormalParameterListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#formalParameter.
    def visitFormalParameter(self, ctx:Java20Parser.FormalParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableArityParameter.
    def visitVariableArityParameter(self, ctx:Java20Parser.VariableArityParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableModifier.
    def visitVariableModifier(self, ctx:Java20Parser.VariableModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#throwsT.
    def visitThrowsT(self, ctx:Java20Parser.ThrowsTContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#exceptionTypeList.
    def visitExceptionTypeList(self, ctx:Java20Parser.ExceptionTypeListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#exceptionType.
    def visitExceptionType(self, ctx:Java20Parser.ExceptionTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#methodBody.
    def visitMethodBody(self, ctx:Java20Parser.MethodBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#instanceInitializer.
    def visitInstanceInitializer(self, ctx:Java20Parser.InstanceInitializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#staticInitializer.
    def visitStaticInitializer(self, ctx:Java20Parser.StaticInitializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#constructorDeclaration.
    def visitConstructorDeclaration(self, ctx:Java20Parser.ConstructorDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#constructorModifier.
    def visitConstructorModifier(self, ctx:Java20Parser.ConstructorModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#constructorDeclarator.
    def visitConstructorDeclarator(self, ctx:Java20Parser.ConstructorDeclaratorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#simpleTypeName.
    def visitSimpleTypeName(self, ctx:Java20Parser.SimpleTypeNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#constructorBody.
    def visitConstructorBody(self, ctx:Java20Parser.ConstructorBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#explicitConstructorInvocation.
    def visitExplicitConstructorInvocation(self, ctx:Java20Parser.ExplicitConstructorInvocationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#enumDeclaration.
    def visitEnumDeclaration(self, ctx:Java20Parser.EnumDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#enumBody.
    def visitEnumBody(self, ctx:Java20Parser.EnumBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#enumConstantList.
    def visitEnumConstantList(self, ctx:Java20Parser.EnumConstantListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#enumConstant.
    def visitEnumConstant(self, ctx:Java20Parser.EnumConstantContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#enumConstantModifier.
    def visitEnumConstantModifier(self, ctx:Java20Parser.EnumConstantModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#enumBodyDeclarations.
    def visitEnumBodyDeclarations(self, ctx:Java20Parser.EnumBodyDeclarationsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#recordDeclaration.
    def visitRecordDeclaration(self, ctx:Java20Parser.RecordDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#recordHeader.
    def visitRecordHeader(self, ctx:Java20Parser.RecordHeaderContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#recordComponentList.
    def visitRecordComponentList(self, ctx:Java20Parser.RecordComponentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#recordComponent.
    def visitRecordComponent(self, ctx:Java20Parser.RecordComponentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableArityRecordComponent.
    def visitVariableArityRecordComponent(self, ctx:Java20Parser.VariableArityRecordComponentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#recordComponentModifier.
    def visitRecordComponentModifier(self, ctx:Java20Parser.RecordComponentModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#recordBody.
    def visitRecordBody(self, ctx:Java20Parser.RecordBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#recordBodyDeclaration.
    def visitRecordBodyDeclaration(self, ctx:Java20Parser.RecordBodyDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#compactConstructorDeclaration.
    def visitCompactConstructorDeclaration(self, ctx:Java20Parser.CompactConstructorDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceDeclaration.
    def visitInterfaceDeclaration(self, ctx:Java20Parser.InterfaceDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#normalInterfaceDeclaration.
    def visitNormalInterfaceDeclaration(self, ctx:Java20Parser.NormalInterfaceDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceModifier.
    def visitInterfaceModifier(self, ctx:Java20Parser.InterfaceModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceExtends.
    def visitInterfaceExtends(self, ctx:Java20Parser.InterfaceExtendsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfacePermits.
    def visitInterfacePermits(self, ctx:Java20Parser.InterfacePermitsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceBody.
    def visitInterfaceBody(self, ctx:Java20Parser.InterfaceBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceMemberDeclaration.
    def visitInterfaceMemberDeclaration(self, ctx:Java20Parser.InterfaceMemberDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#constantDeclaration.
    def visitConstantDeclaration(self, ctx:Java20Parser.ConstantDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#constantModifier.
    def visitConstantModifier(self, ctx:Java20Parser.ConstantModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceMethodDeclaration.
    def visitInterfaceMethodDeclaration(self, ctx:Java20Parser.InterfaceMethodDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#interfaceMethodModifier.
    def visitInterfaceMethodModifier(self, ctx:Java20Parser.InterfaceMethodModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#annotationInterfaceDeclaration.
    def visitAnnotationInterfaceDeclaration(self, ctx:Java20Parser.AnnotationInterfaceDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#annotationInterfaceBody.
    def visitAnnotationInterfaceBody(self, ctx:Java20Parser.AnnotationInterfaceBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#annotationInterfaceMemberDeclaration.
    def visitAnnotationInterfaceMemberDeclaration(self, ctx:Java20Parser.AnnotationInterfaceMemberDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#annotationInterfaceElementDeclaration.
    def visitAnnotationInterfaceElementDeclaration(self, ctx:Java20Parser.AnnotationInterfaceElementDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#annotationInterfaceElementModifier.
    def visitAnnotationInterfaceElementModifier(self, ctx:Java20Parser.AnnotationInterfaceElementModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#defaultValue.
    def visitDefaultValue(self, ctx:Java20Parser.DefaultValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#annotation.
    def visitAnnotation(self, ctx:Java20Parser.AnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#normalAnnotation.
    def visitNormalAnnotation(self, ctx:Java20Parser.NormalAnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#elementValuePairList.
    def visitElementValuePairList(self, ctx:Java20Parser.ElementValuePairListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#elementValuePair.
    def visitElementValuePair(self, ctx:Java20Parser.ElementValuePairContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#elementValue.
    def visitElementValue(self, ctx:Java20Parser.ElementValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#elementValueArrayInitializer.
    def visitElementValueArrayInitializer(self, ctx:Java20Parser.ElementValueArrayInitializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#elementValueList.
    def visitElementValueList(self, ctx:Java20Parser.ElementValueListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#markerAnnotation.
    def visitMarkerAnnotation(self, ctx:Java20Parser.MarkerAnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#singleElementAnnotation.
    def visitSingleElementAnnotation(self, ctx:Java20Parser.SingleElementAnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#arrayInitializer.
    def visitArrayInitializer(self, ctx:Java20Parser.ArrayInitializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableInitializerList.
    def visitVariableInitializerList(self, ctx:Java20Parser.VariableInitializerListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#block.
    def visitBlock(self, ctx:Java20Parser.BlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#blockStatements.
    def visitBlockStatements(self, ctx:Java20Parser.BlockStatementsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#blockStatement.
    def visitBlockStatement(self, ctx:Java20Parser.BlockStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#localClassOrInterfaceDeclaration.
    def visitLocalClassOrInterfaceDeclaration(self, ctx:Java20Parser.LocalClassOrInterfaceDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#localVariableDeclaration.
    def visitLocalVariableDeclaration(self, ctx:Java20Parser.LocalVariableDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#localVariableType.
    def visitLocalVariableType(self, ctx:Java20Parser.LocalVariableTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#localVariableDeclarationStatement.
    def visitLocalVariableDeclarationStatement(self, ctx:Java20Parser.LocalVariableDeclarationStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#statement.
    def visitStatement(self, ctx:Java20Parser.StatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#statementNoShortIf.
    def visitStatementNoShortIf(self, ctx:Java20Parser.StatementNoShortIfContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#statementWithoutTrailingSubstatement.
    def visitStatementWithoutTrailingSubstatement(self, ctx:Java20Parser.StatementWithoutTrailingSubstatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#emptyStatement_.
    def visitEmptyStatement_(self, ctx:Java20Parser.EmptyStatement_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#labeledStatement.
    def visitLabeledStatement(self, ctx:Java20Parser.LabeledStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#labeledStatementNoShortIf.
    def visitLabeledStatementNoShortIf(self, ctx:Java20Parser.LabeledStatementNoShortIfContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#expressionStatement.
    def visitExpressionStatement(self, ctx:Java20Parser.ExpressionStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#statementExpression.
    def visitStatementExpression(self, ctx:Java20Parser.StatementExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#ifThenStatement.
    def visitIfThenStatement(self, ctx:Java20Parser.IfThenStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#ifThenElseStatement.
    def visitIfThenElseStatement(self, ctx:Java20Parser.IfThenElseStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#ifThenElseStatementNoShortIf.
    def visitIfThenElseStatementNoShortIf(self, ctx:Java20Parser.IfThenElseStatementNoShortIfContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#assertStatement.
    def visitAssertStatement(self, ctx:Java20Parser.AssertStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#switchStatement.
    def visitSwitchStatement(self, ctx:Java20Parser.SwitchStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#switchBlock.
    def visitSwitchBlock(self, ctx:Java20Parser.SwitchBlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#switchRule.
    def visitSwitchRule(self, ctx:Java20Parser.SwitchRuleContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#switchBlockStatementGroup.
    def visitSwitchBlockStatementGroup(self, ctx:Java20Parser.SwitchBlockStatementGroupContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#switchLabel.
    def visitSwitchLabel(self, ctx:Java20Parser.SwitchLabelContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#caseConstant.
    def visitCaseConstant(self, ctx:Java20Parser.CaseConstantContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#whileStatement.
    def visitWhileStatement(self, ctx:Java20Parser.WhileStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#whileStatementNoShortIf.
    def visitWhileStatementNoShortIf(self, ctx:Java20Parser.WhileStatementNoShortIfContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#doStatement.
    def visitDoStatement(self, ctx:Java20Parser.DoStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#forStatement.
    def visitForStatement(self, ctx:Java20Parser.ForStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#forStatementNoShortIf.
    def visitForStatementNoShortIf(self, ctx:Java20Parser.ForStatementNoShortIfContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#basicForStatement.
    def visitBasicForStatement(self, ctx:Java20Parser.BasicForStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#basicForStatementNoShortIf.
    def visitBasicForStatementNoShortIf(self, ctx:Java20Parser.BasicForStatementNoShortIfContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#forInit.
    def visitForInit(self, ctx:Java20Parser.ForInitContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#forUpdate.
    def visitForUpdate(self, ctx:Java20Parser.ForUpdateContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#statementExpressionList.
    def visitStatementExpressionList(self, ctx:Java20Parser.StatementExpressionListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#enhancedForStatement.
    def visitEnhancedForStatement(self, ctx:Java20Parser.EnhancedForStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#enhancedForStatementNoShortIf.
    def visitEnhancedForStatementNoShortIf(self, ctx:Java20Parser.EnhancedForStatementNoShortIfContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#breakStatement.
    def visitBreakStatement(self, ctx:Java20Parser.BreakStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#continueStatement.
    def visitContinueStatement(self, ctx:Java20Parser.ContinueStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#returnStatement.
    def visitReturnStatement(self, ctx:Java20Parser.ReturnStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#throwStatement.
    def visitThrowStatement(self, ctx:Java20Parser.ThrowStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#synchronizedStatement.
    def visitSynchronizedStatement(self, ctx:Java20Parser.SynchronizedStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#tryStatement.
    def visitTryStatement(self, ctx:Java20Parser.TryStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#catches.
    def visitCatches(self, ctx:Java20Parser.CatchesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#catchClause.
    def visitCatchClause(self, ctx:Java20Parser.CatchClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#catchFormalParameter.
    def visitCatchFormalParameter(self, ctx:Java20Parser.CatchFormalParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#catchType.
    def visitCatchType(self, ctx:Java20Parser.CatchTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#finallyBlock.
    def visitFinallyBlock(self, ctx:Java20Parser.FinallyBlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#tryWithResourcesStatement.
    def visitTryWithResourcesStatement(self, ctx:Java20Parser.TryWithResourcesStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#resourceSpecification.
    def visitResourceSpecification(self, ctx:Java20Parser.ResourceSpecificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#resourceList.
    def visitResourceList(self, ctx:Java20Parser.ResourceListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#resource.
    def visitResource(self, ctx:Java20Parser.ResourceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#variableAccess.
    def visitVariableAccess(self, ctx:Java20Parser.VariableAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#yieldStatement.
    def visitYieldStatement(self, ctx:Java20Parser.YieldStatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#pattern.
    def visitPattern(self, ctx:Java20Parser.PatternContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typePattern.
    def visitTypePattern(self, ctx:Java20Parser.TypePatternContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#expression.
    def visitExpression(self, ctx:Java20Parser.ExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#primary.
    def visitPrimary(self, ctx:Java20Parser.PrimaryContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#primaryNoNewArray.
    def visitPrimaryNoNewArray(self, ctx:Java20Parser.PrimaryNoNewArrayContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#pNNA.
    def visitPNNA(self, ctx:Java20Parser.PNNAContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classLiteral.
    def visitClassLiteral(self, ctx:Java20Parser.ClassLiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classInstanceCreationExpression.
    def visitClassInstanceCreationExpression(self, ctx:Java20Parser.ClassInstanceCreationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unqualifiedClassInstanceCreationExpression.
    def visitUnqualifiedClassInstanceCreationExpression(self, ctx:Java20Parser.UnqualifiedClassInstanceCreationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#classOrInterfaceTypeToInstantiate.
    def visitClassOrInterfaceTypeToInstantiate(self, ctx:Java20Parser.ClassOrInterfaceTypeToInstantiateContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#typeArgumentsOrDiamond.
    def visitTypeArgumentsOrDiamond(self, ctx:Java20Parser.TypeArgumentsOrDiamondContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#arrayCreationExpression.
    def visitArrayCreationExpression(self, ctx:Java20Parser.ArrayCreationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#arrayCreationExpressionWithoutInitializer.
    def visitArrayCreationExpressionWithoutInitializer(self, ctx:Java20Parser.ArrayCreationExpressionWithoutInitializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#arrayCreationExpressionWithInitializer.
    def visitArrayCreationExpressionWithInitializer(self, ctx:Java20Parser.ArrayCreationExpressionWithInitializerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#dimExprs.
    def visitDimExprs(self, ctx:Java20Parser.DimExprsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#dimExpr.
    def visitDimExpr(self, ctx:Java20Parser.DimExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#arrayAccess.
    def visitArrayAccess(self, ctx:Java20Parser.ArrayAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#fieldAccess.
    def visitFieldAccess(self, ctx:Java20Parser.FieldAccessContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#methodInvocation.
    def visitMethodInvocation(self, ctx:Java20Parser.MethodInvocationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#argumentList.
    def visitArgumentList(self, ctx:Java20Parser.ArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#methodReference.
    def visitMethodReference(self, ctx:Java20Parser.MethodReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#postfixExpression.
    def visitPostfixExpression(self, ctx:Java20Parser.PostfixExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#pfE.
    def visitPfE(self, ctx:Java20Parser.PfEContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#postIncrementExpression.
    def visitPostIncrementExpression(self, ctx:Java20Parser.PostIncrementExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#postDecrementExpression.
    def visitPostDecrementExpression(self, ctx:Java20Parser.PostDecrementExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unaryExpression.
    def visitUnaryExpression(self, ctx:Java20Parser.UnaryExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#preIncrementExpression.
    def visitPreIncrementExpression(self, ctx:Java20Parser.PreIncrementExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#preDecrementExpression.
    def visitPreDecrementExpression(self, ctx:Java20Parser.PreDecrementExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#unaryExpressionNotPlusMinus.
    def visitUnaryExpressionNotPlusMinus(self, ctx:Java20Parser.UnaryExpressionNotPlusMinusContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#castExpression.
    def visitCastExpression(self, ctx:Java20Parser.CastExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#multiplicativeExpression.
    def visitMultiplicativeExpression(self, ctx:Java20Parser.MultiplicativeExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#additiveExpression.
    def visitAdditiveExpression(self, ctx:Java20Parser.AdditiveExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#shiftExpression.
    def visitShiftExpression(self, ctx:Java20Parser.ShiftExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#relationalExpression.
    def visitRelationalExpression(self, ctx:Java20Parser.RelationalExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#equalityExpression.
    def visitEqualityExpression(self, ctx:Java20Parser.EqualityExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#andExpression.
    def visitAndExpression(self, ctx:Java20Parser.AndExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#exclusiveOrExpression.
    def visitExclusiveOrExpression(self, ctx:Java20Parser.ExclusiveOrExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#inclusiveOrExpression.
    def visitInclusiveOrExpression(self, ctx:Java20Parser.InclusiveOrExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#conditionalAndExpression.
    def visitConditionalAndExpression(self, ctx:Java20Parser.ConditionalAndExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#conditionalOrExpression.
    def visitConditionalOrExpression(self, ctx:Java20Parser.ConditionalOrExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#conditionalExpression.
    def visitConditionalExpression(self, ctx:Java20Parser.ConditionalExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#assignmentExpression.
    def visitAssignmentExpression(self, ctx:Java20Parser.AssignmentExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#assignment.
    def visitAssignment(self, ctx:Java20Parser.AssignmentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#leftHandSide.
    def visitLeftHandSide(self, ctx:Java20Parser.LeftHandSideContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#assignmentOperator.
    def visitAssignmentOperator(self, ctx:Java20Parser.AssignmentOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#lambdaExpression.
    def visitLambdaExpression(self, ctx:Java20Parser.LambdaExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#lambdaParameters.
    def visitLambdaParameters(self, ctx:Java20Parser.LambdaParametersContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#lambdaParameterList.
    def visitLambdaParameterList(self, ctx:Java20Parser.LambdaParameterListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#lambdaParameter.
    def visitLambdaParameter(self, ctx:Java20Parser.LambdaParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#lambdaParameterType.
    def visitLambdaParameterType(self, ctx:Java20Parser.LambdaParameterTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#lambdaBody.
    def visitLambdaBody(self, ctx:Java20Parser.LambdaBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#switchExpression.
    def visitSwitchExpression(self, ctx:Java20Parser.SwitchExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by Java20Parser#constantExpression.
    def visitConstantExpression(self, ctx:Java20Parser.ConstantExpressionContext):
        return self.visitChildren(ctx)



del Java20Parser