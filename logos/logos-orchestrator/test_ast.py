#!/usr/bin/env python3
import ast

code = """
@app.post("/test")
async def test_func():
    pass
"""

tree = ast.parse(code)
func = tree.body[0]
print(f"Function: {func.name}")
print(f"Decorators: {func.decorator_list}")
for dec in func.decorator_list:
    print(f"  - Type: {type(dec)}")
    if isinstance(dec, ast.Call):
        print(f"    Func: {dec.func}")
        if isinstance(dec.func, ast.Attribute):
            print(f"      Value: {dec.func.value.id if isinstance(dec.func.value, ast.Name) else dec.func.value}")
            print(f"      Attr: {dec.func.attr}")
