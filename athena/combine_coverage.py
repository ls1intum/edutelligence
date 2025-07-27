#!/usr/bin/env python3
"""
Script to combine duplicate coverage entries and calculate averages.
This script processes coverage XML files and merges duplicate packages.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
import sys
import os
import time

def parse_coverage_xml(xml_file):
    """Parse a coverage XML file and return package data."""
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    packages = {}
    for package in root.findall('.//package'):
        name = package.get('name', '')
        line_rate = float(package.get('line-rate', 0))
        branch_rate = float(package.get('branch-rate', 0))
        complexity = float(package.get('complexity', 0))
        
        packages[name] = {
            'line_rate': line_rate,
            'branch_rate': branch_rate,
            'complexity': complexity,
            'classes': []
        }
        
        # Collect class information
        for cls in package.findall('.//class'):
            class_name = cls.get('name', '')
            class_filename = cls.get('filename', '')
            class_line_rate = float(cls.get('line-rate', 0))
            class_branch_rate = float(cls.get('branch-rate', 0))
            class_complexity = float(cls.get('complexity', 0))
            
            # Extract detailed line information
            lines = []
            for line_elem in cls.findall('.//line'):
                line_number = int(line_elem.get('number', 0))
                hits = int(line_elem.get('hits', 0))
                lines.append({'number': line_number, 'hits': hits})
            
            # Extract detailed branch information
            branches = []
            for branch_elem in cls.findall('.//branch'):
                line_number = int(branch_elem.get('number', 0))
                hits = int(branch_elem.get('hits', 0))
                branches.append({'number': line_number, 'hits': hits})
            
            packages[name]['classes'].append({
                'name': class_name,
                'filename': class_filename,
                'line_rate': class_line_rate,
                'branch_rate': class_branch_rate,
                'complexity': class_complexity,
                'lines': lines,
                'branches': branches
            })
    
    return packages

def combine_packages(all_packages):
    """Combine duplicate packages and calculate averages."""
    combined = defaultdict(list)
    
    # Group packages by name
    for packages in all_packages:
        for name, data in packages.items():
            combined[name].append(data)
    
    # Calculate averages for each package
    result = {}
    for name, package_list in combined.items():
        if len(package_list) == 1:
            # No duplicates, keep as is
            result[name] = package_list[0]
        else:
            # Calculate averages
            avg_line_rate = sum(p['line_rate'] for p in package_list) / len(package_list)
            avg_branch_rate = sum(p['branch_rate'] for p in package_list) / len(package_list)
            avg_complexity = sum(p['complexity'] for p in package_list) / len(package_list)
            
            # Merge classes (take unique ones based on filename)
            all_classes = []
            seen_filenames = set()
            for package in package_list:
                for cls in package['classes']:
                    if cls['filename'] not in seen_filenames:
                        all_classes.append(cls)
                        seen_filenames.add(cls['filename'])
            
            result[name] = {
                'line_rate': avg_line_rate,
                'branch_rate': avg_branch_rate,
                'complexity': avg_complexity,
                'classes': all_classes
            }
    
    return result

def create_combined_xml(combined_packages, output_file):
    """Create a new XML file with combined coverage data."""
    # Calculate totals for root attributes
    total_lines_valid = 0
    total_lines_covered = 0
    total_branches_valid = 0
    total_branches_covered = 0
    total_complexity = 0
    
    # Collect all classes to calculate totals
    all_classes = []
    for package_data in combined_packages.values():
        all_classes.extend(package_data['classes'])
    
    # Calculate totals from all classes
    for cls in all_classes:
        # Extract line and branch info from class data
        # Assuming class data has line and branch information
        if 'lines' in cls:
            total_lines_valid += len(cls['lines'])
            total_lines_covered += sum(1 for line in cls['lines'] if line.get('hits', 0) > 0)
        if 'branches' in cls:
            total_branches_valid += len(cls['branches'])
            total_branches_covered += sum(1 for branch in cls['branches'] if branch.get('hits', 0) > 0)
        total_complexity += cls.get('complexity', 0)
    
    # Calculate rates
    line_rate = total_lines_covered / total_lines_valid if total_lines_valid > 0 else 0
    branch_rate = total_branches_covered / total_branches_valid if total_branches_valid > 0 else 0
    
    # Create the XML structure
    root = ET.Element('coverage')
    root.set('version', '1')
    root.set('timestamp', str(int(time.time())))
    root.set('lines-valid', str(total_lines_valid))
    root.set('lines-covered', str(total_lines_covered))
    root.set('line-rate', str(line_rate))
    root.set('branches-covered', str(total_branches_covered))
    root.set('branches-valid', str(total_branches_valid))
    root.set('branch-rate', str(branch_rate))
    root.set('complexity', str(total_complexity))
    
    packages_elem = ET.SubElement(root, 'packages')
    
    # Add packages
    for name, data in combined_packages.items():
        package_elem = ET.SubElement(packages_elem, 'package')
        package_elem.set('name', name)
        package_elem.set('line-rate', str(data['line_rate']))
        package_elem.set('branch-rate', str(data['branch_rate']))
        package_elem.set('complexity', str(data['complexity']))
        
        # Add classes
        for cls in data['classes']:
            class_elem = ET.SubElement(package_elem, 'class')
            class_elem.set('name', cls['name'])
            class_elem.set('filename', cls['filename'])
            class_elem.set('line-rate', str(cls['line_rate']))
            class_elem.set('branch-rate', str(cls['branch_rate']))
            class_elem.set('complexity', str(cls['complexity']))
            
            # Add methods element (required by Cobertura format)
            methods_elem = ET.SubElement(class_elem, 'methods')
            
            # Add lines element with detailed line information
            lines_elem = ET.SubElement(class_elem, 'lines')
            for line in cls.get('lines', []):
                line_elem = ET.SubElement(lines_elem, 'line')
                line_elem.set('number', str(line['number']))
                line_elem.set('hits', str(line['hits']))
            
            # Add branches element with detailed branch information
            if cls.get('branches'):
                branches_elem = ET.SubElement(class_elem, 'branches')
                for branch in cls['branches']:
                    branch_elem = ET.SubElement(branches_elem, 'branch')
                    branch_elem.set('number', str(branch['number']))
                    branch_elem.set('hits', str(branch['hits']))
    
    # Write the XML file
    tree = ET.ElementTree(root)
    tree.write(output_file, encoding='utf-8', xml_declaration=True)

def main():
    """Main function to combine coverage files."""
    if len(sys.argv) < 3:
        print("Usage: python combine_coverage.py [--summary] <output_file> <input_file1> [input_file2] ...")
        sys.exit(1)
    
    # Check for summary flag
    show_summary = False
    if sys.argv[1] == "--summary":
        show_summary = True
        sys.argv = sys.argv[1:]  # Remove the flag
    
    output_file = sys.argv[1]
    input_files = sys.argv[2:]
    
    print(f"Combining {len(input_files)} coverage files...")
    
    # Parse all input files
    all_packages = []
    for xml_file in input_files:
        if os.path.exists(xml_file):
            print(f"  Parsing {xml_file}...")
            packages = parse_coverage_xml(xml_file)
            all_packages.append(packages)
        else:
            print(f"  Warning: {xml_file} not found, skipping...")
    
    if not all_packages:
        print("No valid coverage files found!")
        sys.exit(1)
    
    # Combine packages
    print("Combining duplicate packages...")
    combined = combine_packages(all_packages)
    
    # Create output file
    print(f"Creating combined coverage file: {output_file}")
    create_combined_xml(combined, output_file)
    
    print(f"✅ Combined coverage saved to {output_file}")
    print(f"📊 Combined {len(combined)} unique packages")
    
    # Show summary if requested
    if show_summary:
        print("\n📊 Combined Coverage Summary:")
        print("=" * 50)
        total_lines = 0
        total_covered = 0
        total_branches = 0
        total_branch_covered = 0
        
        for name, data in sorted(combined.items()):
            line_rate = data['line_rate']
            branch_rate = data['branch_rate']
            
            # Calculate health indicator
            if line_rate >= 0.8 and branch_rate >= 0.8:
                health = "✓"
            elif line_rate >= 0.5 and branch_rate >= 0.5:
                health = "-"
            else:
                health = "✗"
            
            print(f"{name:<50} {line_rate:>6.1%} {branch_rate:>6.1%} {health}")
        
        print("=" * 50)
        print(f"Total packages: {len(combined)}")

if __name__ == "__main__":
    main() 