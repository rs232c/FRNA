# FRNA Process Killers

Scripts to kill all Python processes and FRNA-related services.

## Files

### `kill_all.py` - Cross-platform Python Script
- **Platform:** Windows, Linux, Mac
- **Usage:**
  ```bash
  # Interactive mode (asks for confirmation)
  python kill_all.py

  # Non-interactive mode (auto-confirms)
  python kill_all.py --yes
  ```
- **Features:**
  - Kills all Python processes
  - Detects processes using port 8000 (FRNA admin server)
  - Cross-platform (Windows uses `taskkill`, Unix uses `pkill`/`killall`)

### `kill_python.bat` - Windows Batch Script
- **Platform:** Windows only
- **Usage:** Double-click `kill_python.bat` or run from command prompt
- **Features:**
  - Kills all Python processes (`python.exe`, `python3.exe`, `pythonw.exe`, `py.exe`)
  - Simple confirmation prompt
  - Shows success/failure for each process type

## What Gets Killed

- All running Python processes (`python.exe`, `python3.exe`, `pythonw.exe`, `py.exe`)
- Any processes listening on port 8000 (FRNA admin server)
- Flask development servers
- Any background Python scripts

## Safety Notes

⚠️ **WARNING:** These scripts kill ALL Python processes on your system!

- Save any important work in Python editors/IDEs first
- Close any Python applications you want to keep running
- These scripts are for development cleanup only

## Usage Scenarios

1. **FRNA server won't start:** Kill existing processes first
2. **Multiple Python processes running:** Clean up background processes
3. **Port 8000 conflicts:** Kill processes using the admin port
4. **Development cleanup:** Reset before restarting services

## After Killing

Once processes are killed, you can safely restart FRNA:

```bash
python server.py         # Start unified server (admin + website)
python main.py           # Start aggregator
```

## Legacy Commands (Deprecated)

For backward compatibility, these still work but use the unified server:

```bash
python admin.py          # Redirects to server.py
```

## Troubleshooting

- If scripts don't work, try running as administrator (Windows)
- On Linux/Mac, you might need `sudo` for some kill operations
- Check Task Manager (Windows) or `ps aux` (Unix) to verify processes are killed