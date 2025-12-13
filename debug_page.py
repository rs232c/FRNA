import requests

# Login first
session = requests.Session()
login_response = session.post('http://127.0.0.1:8000/admin/login', data={'username': '02720', 'password': 'zip123'})

# Get categories page
response = session.get('http://127.0.0.1:8000/admin/02720?tab=categories')

print(f'Status: {response.status_code}')
print(f'Cache-Control header: {response.headers.get("Cache-Control", "Not set")}')
print(f'Content length: {len(response.text)}')

# Check if our CSS overrides are in the HTML
if 'background: #1a1a1a !important' in response.text:
    print('CSS override rules found in HTML')
else:
    print('CSS override rules NOT found in HTML')

# Check if our JavaScript debug logs are present
if 'debugLog(' in response.text:
    print('Debug logging JavaScript found')
else:
    print('Debug logging JavaScript NOT found')

# Check for any obvious issues
content = response.text
if 'display: none' in content:
    display_none_count = content.count('display: none')
    print(f'Found {display_none_count} instances of display: none')

if 'visibility: hidden' in content:
    visibility_hidden_count = content.count('visibility: hidden')
    print(f'Found {visibility_hidden_count} instances of visibility: hidden')

# Check if the page has the right structure
if '<!DOCTYPE html>' in content and '<html' in content and '</html>' in content:
    print('HTML structure appears valid')
else:
    print('HTML structure may be malformed')

# Check for JavaScript errors in the HTML (look for error patterns)
error_patterns = ['TypeError', 'ReferenceError', 'SyntaxError', 'Uncaught']
found_errors = []
for pattern in error_patterns:
    if pattern in content:
        found_errors.append(pattern)

if found_errors:
    print(f'Found potential error indicators in HTML: {found_errors}')
else:
    print('No obvious error indicators in HTML')
