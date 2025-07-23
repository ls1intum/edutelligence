#!/usr/bin/env python
"""
Unified CLI tool for stepwise consistency check dataset variant creation.

For complete documentation, see:
- VARIANT_CREATION_GUIDE.md - Full workflow guide
- VARIANT_CREATION_QUICK_REFERENCE.md - Quick commands

Steps:
1. init                - Create initial variant structure and copy base files
2. finalize            - Generate git diff patch showing changes made
3. generate-annotation - Run consistency checker and create clean annotation file

Example usage:
  # Step 1: Initialize
  python playground/create_variant.py --exercise "ITP2425/H01E01-Lectures" init \\
    --category "VISIBILITY_MISMATCH" \\
    --description "Add private constructor while requiring public instantiation"

  # Step 2: Make changes manually or via AI agent using file editing tools

  # Step 3: Generate patch
  python playground/create_variant.py --exercise "ITP2425/H01E01-Lectures" finalize --variant "001"

  # Step 4: Create annotation
  python playground/create_variant.py --exercise "ITP2425/H01E01-Lectures" generate-annotation --variant "001"
"""

import sys
import json
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

# Add the project root to the path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.creation_steps.step8_review_and_refine.consistency_check.models import (
    StructuralConsistencyIssueCategory,
    SemanticConsistencyIssueCategory,
)

# All supported consistency issue categories
ALL_CATEGORIES = {
    "METHOD_RETURN_TYPE_MISMATCH": StructuralConsistencyIssueCategory.METHOD_RETURN_TYPE_MISMATCH,
    "METHOD_PARAMETER_MISMATCH": StructuralConsistencyIssueCategory.METHOD_PARAMETER_MISMATCH,
    "CONSTRUCTOR_PARAMETER_MISMATCH": StructuralConsistencyIssueCategory.CONSTRUCTOR_PARAMETER_MISMATCH,
    "ATTRIBUTE_TYPE_MISMATCH": StructuralConsistencyIssueCategory.ATTRIBUTE_TYPE_MISMATCH,
    "VISIBILITY_MISMATCH": StructuralConsistencyIssueCategory.VISIBILITY_MISMATCH,
    "IDENTIFIER_NAMING_INCONSISTENCY": SemanticConsistencyIssueCategory.IDENTIFIER_NAMING_INCONSISTENCY,
}


class VariantManager:
    """Manages the lifecycle of consistency check variants."""

    def __init__(self, exercise_path: str):
        self.exercise_path = exercise_path
        self.base_path = Path(__file__).parent.parent / "data" / exercise_path

        if not self.base_path.exists():
            raise FileNotFoundError(f"Exercise not found: {exercise_path}")

    def get_next_variant_number(self) -> str:
        """Get the next sequential variant number."""
        variants_dir = self.base_path / "variants"
        if not variants_dir.exists():
            return "001"

        existing_variants = [
            d.name for d in variants_dir.iterdir() if d.is_dir() and d.name.isdigit()
        ]
        if not existing_variants:
            return "001"

        max_num = max(int(variant) for variant in existing_variants)
        return f"{max_num + 1:03d}"

    def get_variant_path(self, variant_id: str) -> Path:
        """Get path to specific variant."""
        return self.base_path / "variants" / variant_id

    def init_variant(
        self, category: str, description: str, variant_id: str = None
    ) -> str:
        """Step 1: Initialize variant structure and copy base files."""
        if variant_id is None:
            variant_id = self.get_next_variant_number()

        variant_path = self.get_variant_path(variant_id)

        if variant_path.exists():
            raise ValueError(f"Variant {variant_id} already exists")

        print(
            f"🚀 Initializing variant {variant_id} for exercise: {self.exercise_path}"
        )
        print(f"📂 Category: {category}")
        print(f"📝 Description: {description}")

        # Copy base exercise files
        variant_path.mkdir(parents=True, exist_ok=True)
        required_items = ["problem-statement.md", "solution", "template", "tests"]

        for item in required_items:
            source_item = self.base_path / item
            target_item = variant_path / item

            if source_item.exists():
                if source_item.is_file():
                    shutil.copy2(source_item, target_item)
                    print(f"  ✓ Copied file: {item}")
                elif source_item.is_dir():
                    shutil.copytree(source_item, target_item, dirs_exist_ok=True)
                    print(f"  ✓ Copied directory: {item}")
            else:
                print(f"  ⚠️  Warning: {item} not found in base exercise")

        # Create simple description file - just the description text
        description_file = variant_path / f"{variant_id}.{category}.md"
        with open(description_file, "w", encoding="utf-8") as f:
            f.write(f"{description}\n")
        print(f"  ✓ Created description: {description_file.name}")

        print(f"✅ Variant {variant_id} initialized at: {variant_path}")
        print("💡 Next: Make your changes, then run finalize")
        return variant_id

    def create_git_diff(self, variant_id: str) -> Path:
        """Create a git diff patch showing changes between base and variant."""
        variant_path = self.get_variant_path(variant_id)
        patch_file = variant_path / f"{variant_id}.patch"

        try:
            with tempfile.TemporaryDirectory() as temp_dir_str:
                temp_dir = Path(temp_dir_str)

                # Copy base and variant files to temp locations
                base_temp = temp_dir / "base"
                variant_temp = temp_dir / "variant"

                # Copy only the main files we care about
                items_to_copy = [
                    "problem-statement.md",
                    "solution",
                    "template",
                    "tests",
                ]

                # Copy base files
                base_temp.mkdir()
                for item in items_to_copy:
                    src_item = self.base_path / item
                    dst_item = base_temp / item
                    if src_item.exists():
                        if src_item.is_file():
                            shutil.copy2(src_item, dst_item)
                        elif src_item.is_dir():
                            shutil.copytree(src_item, dst_item)

                # Copy variant files
                variant_temp.mkdir()
                for item in items_to_copy:
                    src_item = variant_path / item
                    dst_item = variant_temp / item
                    if src_item.exists():
                        if src_item.is_file():
                            shutil.copy2(src_item, dst_item)
                        elif src_item.is_dir():
                            shutil.copytree(src_item, dst_item)

                # Create git diff using system diff command
                try:
                    result = subprocess.run(
                        ["diff", "-ruN", str(base_temp), str(variant_temp)],
                        capture_output=True,
                        text=True,
                    )

                    # diff returns 1 when files differ, which is what we want
                    if result.stdout:
                        diff_content = result.stdout
                        # Clean up the diff to show relative paths
                        diff_content = diff_content.replace(str(base_temp), "a")
                        diff_content = diff_content.replace(str(variant_temp), "b")

                        with open(patch_file, "w", encoding="utf-8") as f:
                            f.write(diff_content)

                        print(
                            f"  ✓ Generated git diff with {len(diff_content.splitlines())} lines"
                        )
                        return patch_file

                except subprocess.CalledProcessError:
                    pass

                # Fallback: create empty patch file
                with open(patch_file, "w", encoding="utf-8") as f:
                    f.write(f"# No differences found for variant {variant_id}\n")
                    f.write(f"# Exercise: {self.exercise_path}\n")

                return patch_file

        except Exception as e:
            print(f"  ❌ Error creating git diff: {e}")
            # Create error placeholder
            with open(patch_file, "w", encoding="utf-8") as f:
                f.write(f"# Error generating diff for variant {variant_id}\n")
                f.write(f"# Error: {e}\n")
            return patch_file

    def finalize_variant(self, variant_id: str) -> Path:
        """Step 2: Generate git diff patch showing changes made."""
        variant_path = self.get_variant_path(variant_id)

        if not variant_path.exists():
            raise ValueError(f"Variant {variant_id} does not exist. Run init first.")

        print(f"🏁 Finalizing variant {variant_id}...")

        # Create git diff patch
        print("1️⃣ Creating git diff patch...")
        patch_file = self.create_git_diff(variant_id)
        print(f"  ✓ Patch file created: {patch_file.name}")

        print(f"✅ Variant {variant_id} finalized")
        print(
            f'💡 Next: python playground/create_variant.py --exercise "{self.exercise_path}" generate-annotation \
-v {variant_id}'
        )
        return patch_file

    def generate_annotation(self, variant_id: str) -> Path:
        """Step 3: Run consistency checker and create clean annotation file."""
        variant_path = self.get_variant_path(variant_id)

        if not variant_path.exists():
            raise ValueError(f"Variant {variant_id} does not exist. Run init first.")

        print(f"🔍 Generating annotation for variant {variant_id}...")

        # Run consistency checker for the specific variant
        print("1️⃣ Running consistency checker...")
        try:
            eval_script = Path(__file__).parent / "eval_consistency_checker.py"

            cmd = [
                sys.executable,
                str(eval_script),
                "--exercise",
                self.exercise_path,
                "--variant",
                variant_id,
            ]

            result = subprocess.run(
                cmd, cwd=Path(__file__).parent.parent, capture_output=True, text=True
            )

            if result.returncode == 0:
                print("  ✓ Consistency checker completed")

                # The new script directly saves results to the variant's outputs directory
                # Find the most recent result file
                outputs_dir = variant_path / "outputs"
                if outputs_dir.exists():
                    result_files = list(outputs_dir.glob("*_result.json"))
                    if result_files:
                        # Get the most recent result file
                        latest_result_file = max(result_files, key=lambda f: f.stat().st_mtime)
                        
                        with open(latest_result_file, "r", encoding="utf-8") as f:
                            eval_data = json.load(f)

                        # Create clean annotation file - mirror the consistency checker output
                        json_file = variant_path / f"{variant_id}.json"
                        clean_annotation = {
                            "exercise_path": eval_data["exercise_path"],
                            "programming_language": eval_data["programming_language"],
                            "issues": eval_data["response"]["issues"],
                        }

                        with open(json_file, "w", encoding="utf-8") as f:
                            json.dump(clean_annotation, f, indent=2, ensure_ascii=False)

                        print(
                            f"  ✓ Generated annotation with {len(clean_annotation['issues'])} detected issues"
                        )

                        # Show what was detected
                        for issue in clean_annotation["issues"]:
                            print(
                                f"    - {issue['category']} ({issue['severity']}): {issue['description'][:80]}..."
                            )

                        print(f"✅ Annotation generated: {json_file}")
                        return json_file
                    else:
                        raise RuntimeError("No result files found in outputs directory")
                else:
                    raise RuntimeError("Outputs directory not found - evaluation may have failed")
            else:
                raise RuntimeError(f"Consistency checker failed: {result.stderr}")

        except Exception as e:
            print(f"  ❌ Error running consistency checker: {e}")
            raise


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Unified CLI tool for stepwise consistency check variant creation"
    )

    # Common arguments
    parser.add_argument(
        "--exercise",
        "-e",
        required=True,
        help="Exercise path (e.g., ITP2425/H01E01-Lectures)",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize variant structure")
    init_parser.add_argument(
        "--category",
        "-c",
        required=True,
        choices=list(ALL_CATEGORIES.keys()),
        help="Consistency issue category",
    )
    init_parser.add_argument(
        "--description",
        "-d",
        required=True,
        help="Description of the consistency issue to inject",
    )
    init_parser.add_argument("--variant", "-v", help="Specific variant ID (optional)")

    # Finalize command
    finalize_parser = subparsers.add_parser("finalize", help="Generate git diff patch")
    finalize_parser.add_argument("--variant", "-v", required=True, help="Variant ID")

    # Generate annotation command
    generate_parser = subparsers.add_parser(
        "generate-annotation", help="Run consistency checker and create annotation"
    )
    generate_parser.add_argument("--variant", "-v", required=True, help="Variant ID")

    args = parser.parse_args()

    # Handle command structure
    if not args.command:
        parser.print_help()
        return 1

    try:
        manager = VariantManager(args.exercise)

        if args.command == "init":
            variant_id = manager.init_variant(
                args.category, args.description, args.variant
            )
            print(f"\n🎯 Created variant {variant_id}")
            print(f"📝 Make your changes in: {manager.get_variant_path(variant_id)}")
            print(
                f'🔄 Then run: python playground/create_variant.py --exercise "{args.exercise}" finalize -v {variant_id}'
            )

        elif args.command == "finalize":
            patch_file = manager.finalize_variant(args.variant)
            print(f"\n🎯 Generated patch: {patch_file}")

        elif args.command == "generate-annotation":
            json_file = manager.generate_annotation(args.variant)
            print(f"\n🎯 Generated annotation: {json_file}")

    except Exception as e:
        print(f"❌ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
