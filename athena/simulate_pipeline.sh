# Run tests for each module using its own virtual environment
for module in modules/programming/module_programming_llm modules/text/module_text_llm modules/modeling/module_modeling_llm; do
  if [ -d "$module/.venv" ]; then
    echo "Running tests for $module..."
    # Install pytest and coverage in the module's environment
    $module/.venv/bin/pip install pytest pytest-asyncio coverage
    # Run tests with coverage using the module's environment
    if ! $module/.venv/bin/python -m coverage run --rcfile=.coveragerc --data-file=".coverage.${module//\//_}" -m pytest tests/$module/mock --junitxml=test-results/${module//\//_}_mock.xml; then
      echo "Tests failed for $module"
      overall_success=false
    fi
    # Generate coverage report for this module
    $module/.venv/bin/python -m coverage xml --rcfile=.coveragerc --data-file=".coverage.${module//\//_}" -o test-results/${module//\//_}_coverage.xml
  else
    echo "Virtual environment not found for $module, skipping..."
  fi
done

# Exit with failure if any tests failed
if [ "$overall_success" = false ]; then
  echo "❌ Some tests failed!"
  exit 1
else
  echo "✅ All tests passed!"
fi

# Display coverage reports
echo "📊 Coverage Reports:"
echo "===================="
for module in modules/programming/module_programming_llm modules/text/module_text_llm modules/modeling/module_modeling_llm; do
  if [ -d "$module/.venv" ]; then
    echo "📈 $module:"
    $module/.venv/bin/python -m coverage report --rcfile=.coveragerc --data-file=".coverage.${module//\//_}" --show-missing || echo "No coverage data available"
    echo ""
  fi
done

# Test prospector linting
echo ""
echo "🔍 Testing Prospector Linting:"
echo "=============================="
if command -v poetry &> /dev/null; then
  cd athena
  export PYTHONPATH="$PWD:$PWD/llm_core"
  # Try prospector with explicit profile path
  poetry run prospector --profile .prospector.yaml athena/ 2>/dev/null || echo "Prospector linting completed with warnings/errors (this is expected in local environment)"
  # Alternative: try without profile if the above fails
  # poetry run prospector athena/ 2>/dev/null || echo "Prospector linting completed with warnings/errors"
  cd ..
else
  echo "Poetry not found, skipping prospector linting"
fi 