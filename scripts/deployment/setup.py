"""
Setup script for Fall River News Aggregator
"""
import os
import subprocess
import sys

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import requests
        import bs4
        import feedparser
        import jinja2
        print("✓ Core dependencies found")
        return True
    except ImportError as e:
        print(f"✗ Missing dependency: {e}")
        return False

def install_dependencies():
    """Install required dependencies"""
    print("Installing dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✓ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError:
        print("✗ Failed to install dependencies")
        return False

def setup_environment():
    """Setup environment file"""
    if not os.path.exists(".env"):
        if os.path.exists(".env.example"):
            import shutil
            shutil.copy(".env.example", ".env")
            print("✓ Created .env file from .env.example")
            print("⚠ Please edit .env with your API credentials")
        else:
            print("⚠ .env.example not found")
    else:
        print("✓ .env file already exists")

def create_directories():
    """Create necessary directories"""
    directories = [
        "build",
        "build/css",
        "build/js"
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
    
    print("✓ Created necessary directories")

def main():
    """Main setup function"""
    print("=" * 60)
    print("Fall River News Aggregator - Setup")
    print("=" * 60)
    print()
    
    # Check dependencies
    if not check_dependencies():
        response = input("Install missing dependencies? (y/n): ")
        if response.lower() == 'y':
            if not install_dependencies():
                print("Setup failed. Please install dependencies manually.")
                return
        else:
            print("Please install dependencies manually: pip install -r requirements.txt")
            return
    
    # Setup environment
    setup_environment()
    
    # Create directories
    create_directories()
    
    print()
    print("=" * 60)
    print("Setup complete!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Edit .env file with your API credentials")
    print("2. Edit config.py to configure news sources and settings")
    print("3. Run: python main.py --once (to test)")
    print("4. Run: python main.py (to start continuous operation)")

if __name__ == "__main__":
    main()

