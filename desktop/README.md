# Desktop app

`yantguard_desktop.py` starts the gateway in the background (on port 8000, or a free
port if 8000 is taken) and shows the dashboard in its own window (pywebview).

| Command | What it does |
|---|---|
| `scripts\run_desktop.bat` | Run the desktop app from source (installs `pywebview` on first run) |
| `scripts\run_desktop.bat --browser` | Same, but open the normal browser instead of the app window |
| `scripts\run_desktop.bat --admin` | Admin menu (users, keys, budgets, security rules) |
| `scripts\build_desktop.bat` | Build `dist\YantGuard\YantGuard.exe` with PyInstaller (`yantguard.spec`) |

The packaged app keeps its database, log and settings in `%LOCALAPPDATA%\YantGuard\data`
(from source it is still `data\`). Put `.env` (GEMINI_API_KEY / GROQ_API_KEY) next to
`YantGuard.exe` or in that folder. Log file: `yantguard.log` in the same folder.

Needs the Microsoft Edge WebView2 runtime (already part of Windows 10/11).
`YantGuard.exe --admin` opens the admin menu in a console window.

The first start asks you to create the administrator account in the window; after that you sign in
with it. Everything (users, keys, budgets, rules) can be managed in the **Manage** tab.
