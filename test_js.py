#!/usr/bin/env python3
import re

with open('admin/static/js/admin.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Check for function definitions
functions = ['showRuleManager', 'showSourceManager', 'showCategoryManager']
for func in functions:
    if f'function {func}' in content:
        print(f'SUCCESS: Function {func} is defined')
    else:
        print(f'ERROR: Function {func} is NOT defined')

# Check for syntax errors by looking for unmatched braces
open_braces = content.count('{')
close_braces = content.count('}')
print(f'Open braces: {open_braces}, Close braces: {close_braces}')
if open_braces == close_braces:
    print('SUCCESS: Braces are balanced')
else:
    print('ERROR: Braces are NOT balanced')

# Check for the specific line where the error occurs
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'showRuleManager' in line and 'onclick' in line:
        print(f'Found onclick on line {i+1}: {line.strip()}')

print('JS analysis complete')
