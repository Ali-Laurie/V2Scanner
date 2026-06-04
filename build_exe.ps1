# Build script for creating a single-file executable using PyInstaller
# Run this script in PowerShell (Windows).

# Install PyInstaller in the active Python environment
pip install --upgrade pyinstaller

# Build one-file windowed executable from Scan.py
pyinstaller --noconfirm --onefile --windowed --name "ScanV2Ray" \
  --add-data "About.md;." \
  --add-data "scanv2ray;scanv2ray" \
  --add-data "Core;Core" \
  Scan.py

# Output will be in the dist\ScanV2Ray.exe
Write-Host "Build finished. See dist\ScanV2Ray.exe"