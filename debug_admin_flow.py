"""
Debug the admin login flow
"""
import requests

session = requests.Session()

print('1. Logging in...')
login_response = session.post('http://localhost:8000/admin/login', data={'username': 'admin', 'password': 'admin123'}, allow_redirects=False)
print(f'Login status: {login_response.status_code}')
print(f'Login redirect: {login_response.headers.get("Location", "None")}')

if login_response.status_code == 302:
    redirect_url = login_response.headers.get('Location')

    print(f'2. Following login redirect to: {redirect_url}')
    admin_response = session.get(f'http://localhost:8000{redirect_url}', allow_redirects=False)
    print(f'Admin response status: {admin_response.status_code}')

    if admin_response.status_code == 302:
        final_url = admin_response.headers.get('Location')
        print(f'Admin redirect to: {final_url}')

        print(f'3. Following to final destination: {final_url}')
        final_response = session.get(f'http://localhost:8000{final_url}', allow_redirects=False)
        print(f'Final status: {final_response.status_code}')

        if final_response.status_code == 200:
            content = final_response.text
            if 'Settings' in content and 'Regenerate Website' in content:
                print('SUCCESS: Main admin settings page loaded!')
            elif '02720' in content:
                print('ISSUE: Showing 02720 content instead of main admin')
                print(f'Final URL: {final_url}')
                # Check if it has settings tab
                if 'tab=settings' in final_url:
                    print('It is showing settings tab, but for 02720 instead of main admin')
            else:
                print('UNKNOWN: Different content loaded')
                print(f'Final URL: {final_url}')
        else:
            print(f'ERROR: Final page failed with {final_response.status_code}')
else:
    print('Login failed')
