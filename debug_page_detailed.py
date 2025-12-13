import requests
import re

# Login first
session = requests.Session()
login_response = session.post('http://127.0.0.1:8000/admin/login', data={'username': '02720', 'password': 'zip123'})

# Get categories page
response = session.get('http://127.0.0.1:8000/admin/02720?tab=categories')

content = response.text

# Find all instances of display: none and show context
print("Checking 'display: none' instances:")
display_none_matches = re.finditer(r'display:\s*none', content)
for i, match in enumerate(display_none_matches, 1):
    start = max(0, match.start() - 100)
    end = min(len(content), match.end() + 100)
    context = content[start:end]
    print(f"\n{i}. Around position {match.start()}:")
    print(repr(context))

# Check if the main content areas have display: none
main_elements = ['categoriesTab', 'categoryStats', 'keywordManagement']
for element_id in main_elements:
    pattern = f'id="{element_id}"[^>]*style="[^"]*display:\s*none'
    if re.search(pattern, content):
        print(f"\nWARNING: {element_id} has display: none in style attribute!")
    else:
        print(f"\nOK: {element_id} does not have display: none")

# Check if there are any CSS rules that might hide the content
if '#categoriesTab { display: none' in content:
    print("\nWARNING: Found CSS rule hiding #categoriesTab")

if '.tab-content { display: none' in content:
    print("\nWARNING: Found CSS rule hiding .tab-content")

# Check if the tab system is working (look for active class)
if 'tab-content active' in content:
    print("\nOK: Found active tab-content")
else:
    print("\nWARNING: No active tab-content found - tabs may not be working")

# Check for JavaScript that might be failing
if 'DOMContentLoaded' in content:
    print("\nOK: DOMContentLoaded event listener found")
else:
    print("\nWARNING: No DOMContentLoaded event listener found")
