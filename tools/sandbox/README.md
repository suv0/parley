# Clean-install test in Windows Sandbox

Installs Utter on a bare Windows, with no Python and no winget, the way a first-time user would, and keeps the log.

1. Turn on Windows Sandbox: in an administrator PowerShell run
   `Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All`, then restart.
   (A company-managed PC may block this.)
2. Clone or unzip this repository to `C:\utter`, or change `HostFolder` in `utter-clean-install.wsb` to where
   this folder is.
3. Double-click `utter-clean-install.wsb`.

It installs Python 3.12 from python.org, downloads Utter from GitHub's ZIP, runs `install.ps1`, then `utter doctor`.
Everything it prints goes to `results\install.log` in this folder, and `results\done.txt` appears when it finishes.
