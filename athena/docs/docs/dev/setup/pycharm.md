---
title: PyCharm Setup
---

We recommend working with PyCharm for this project. You can however use
any IDE you like.

To enjoy the full IDE support, add the separate Python interpreters for
each Python package within this repository to PyCharm:

1.  Open the project in PyCharm

2.  Open the project settings (File → Settings)

3.  Go to Project → Project Interpreter

4.  Click on "Add Local Interpreter"

5.  Select "Poetry Environment" on the left → "Existing environment"

6.  Select the Python interpreter for the package you want to work on
    (e.g. `assessment_module_manager/.venv/bin/python`,
    `athena/.venv/bin/python`, `module_example/.venv/bin/python`, ...).
    You might have to click the `...` button to navigate to the correct
    Python binary file.

7.  Click "OK" and "Apply"

8.  Repeat steps 4-7 for each package you want to work on

9.  You can rename the interpreters to something more meaningful (e.g.
    "assessment_module_manager", "athena", "module_example", ...) by
    clicking on the interpreter selection input in PyCharm and choosing
    "Show all". In the window that opens, you can rename the
    interpreters after right-clicking on them.

![PyCharm interpreters window](./images/pycharm-interpreters.png)

When working within a package (= folder within the repository), choose
the correct interpreter for that package in the bottom right corner of
PyCharm. That way, you will get full IDE support for that package.
