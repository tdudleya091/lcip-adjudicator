# PyInstaller build recipe, shared by Linux and Windows. Run: pyinstaller lcip.spec
# Output: dist/LCIP/ (a folder containing the LCIP or LCIP.exe launcher plus its libraries).
a = Analysis(
    ["main.py"],
    datas=[("web", "web"), ("data", "data")],
    hiddenimports=["webview"],
    # Linux GTK hook would otherwise copy every installed icon theme (over 1 GB)
    hooksconfig={"gi": {"icons": ["Adwaita"], "themes": ["Adwaita"], "languages": ["en_US"]}},
    # optional imports pywebview/stdlib can reach that this app never uses
    excludes=["numpy", "PIL", "cryptography", "uvloop", "yaml", "tkinter", "matplotlib", "pandas", "torch", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LCIP", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="LCIP")
