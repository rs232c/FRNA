#!/usr/bin/env python3
"""
Legacy admin server entry point - redirects to unified server
"""
import sys
import os

# Redirect to the unified server
print("This entry point is deprecated. Use 'python server.py' instead.")
print("Redirecting to unified server...")
os.system(f"{sys.executable} server.py")