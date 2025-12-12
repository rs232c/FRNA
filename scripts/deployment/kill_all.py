#!/usr/bin/env python3
"""
FRNA Process Killer Script
Kills all Python processes and related FRNA processes
"""

import subprocess
import sys
import os
import platform
import time

def run_command(cmd, shell=False):
    """Run a command and return the result"""
    try:
        result = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=10)
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)

def kill_processes_windows():
    """Kill processes on Windows"""
    print("[PYTHON] Killing Python processes...")

    # Kill all Python processes
    returncode, stdout, stderr = run_command(["taskkill", "/F", "/IM", "python.exe", "/T"])
    if returncode == 0:
        print("[SUCCESS] Killed Python processes")
        if stdout.strip():
            print(f"Output: {stdout.strip()}")
    else:
        print(f"[WARNING] No Python processes found or error: {stderr.strip()}")

    # Kill any remaining python processes by name variations
    python_variants = ["python3.exe", "pythonw.exe", "py.exe"]
    for variant in python_variants:
        returncode, stdout, stderr = run_command(["taskkill", "/F", "/IM", variant, "/T"])
        if returncode == 0:
            print(f"[SUCCESS] Killed {variant} processes")

    # Kill any Flask development servers (if running)
    try:
        # Try to kill by port 8000 (where admin server runs)
        returncode, stdout, stderr = run_command(["netstat", "-ano"], shell=True)
        if returncode == 0 and "8000" in stdout:
            print("[SEARCH] Found process using port 8000, attempting to kill...")
            # Parse netstat output to find PID
            lines = stdout.split('\n')
            for line in lines:
                if ':8000' in line and 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        print(f"[TARGET] Killing process {pid} on port 8000")
                        run_command(["taskkill", "/F", "/PID", pid])

    except Exception as e:
        print(f"[WARNING] Could not check port 8000: {e}")

    print("[SUCCESS] Process cleanup complete!")

def kill_processes_unix():
    """Kill processes on Unix-like systems (Linux/Mac)"""
    print("[PYTHON] Killing Python processes...")

    # Kill all Python processes
    returncode, stdout, stderr = run_command(["pkill", "-f", "python"])
    if returncode == 0:
        print("[SUCCESS] Killed Python processes")
    else:
        print(f"[WARNING] No Python processes found or error: {stderr.strip()}")

    # Also try killall if available
    returncode, stdout, stderr = run_command(["killall", "python"])
    if returncode == 0:
        print("[SUCCESS] Killed additional Python processes with killall")

    # Kill any processes on port 8000
    try:
        returncode, stdout, stderr = run_command(["lsof", "-ti:8000"])
        if returncode == 0 and stdout.strip():
            pids = stdout.strip().split('\n')
            for pid in pids:
                print(f"[TARGET] Killing process {pid} on port 8000")
                run_command(["kill", "-9", pid])
    except Exception as e:
        print(f"[WARNING] Could not check port 8000: {e}")

    print("[SUCCESS] Process cleanup complete!")

def main():
    """Main function"""
    print("=" * 50)
    print("FRNA Process Killer")
    print("=" * 50)
    print("This will kill ALL Python processes on your system!")
    print("Make sure to save any important work first.")
    print()

    # Confirm with user
    if len(sys.argv) > 1 and sys.argv[1] == "--yes":
        confirm = "y"
    else:
        try:
            confirm = input("Are you sure you want to continue? (y/N): ").lower().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[CANCELLED] Operation cancelled")
            return

    if confirm not in ['y', 'yes']:
        print("[CANCELLED] Operation cancelled")
        return

    # Detect platform and run appropriate function
    system = platform.system().lower()

    if system == "windows":
        kill_processes_windows()
    elif system in ["linux", "darwin"]:
        kill_processes_unix()
    else:
        print(f"[ERROR] Unsupported platform: {system}")
        return

    print("\n" + "=" * 50)
    print("[SUCCESS] All processes killed successfully!")
    print("You can now restart the FRNA server safely.")
    print("=" * 50)

if __name__ == "__main__":
    main()