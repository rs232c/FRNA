"""Quick test to see if admin panel is running"""
import requests
import time

time.sleep(2)
try:
    response = requests.get("http://localhost:5001/admin/login", timeout=5)
    print(f"✓ Admin panel is running! Status: {response.status_code}")
    print(f"  URL: http://localhost:5001/admin")
    print(f"  Login: admin / admin")
except Exception as e:
    print(f"✗ Admin panel not responding: {e}")
    print("  Make sure to run: python admin.py")



