# Building Skyrim Tracker Extreme (Windows 10/11, x64)

## What to install (once)

1. **Rust** - https://rustup.rs - download `rustup-init.exe` (x64) and run it.
   If Visual Studio is not installed yet, the installer offers to install the
   C++ build tools it needs ("Quick install via the Visual Studio Community
   installer") - accept, then press Enter for the default Rust install.
   - To keep Rust off drive C:, before running `rustup-init.exe` add two user
     environment variables (Start - "Edit environment variables for your account"):
     `RUSTUP_HOME = D:\Rust\rustup` and `CARGO_HOME = D:\Rust\cargo`.
   - To place Visual Studio on another drive, install it yourself first:
     https://visualstudio.microsoft.com/downloads/ - Visual Studio Community,
     workload **Desktop development with C++**, tab "Installation locations".
     About 1-2 GB still goes to C: (shared components), that cannot be changed.
2. **WebView2 Runtime** - already part of Windows 10/11 (Microsoft Edge).
   Only if it is missing: https://developer.microsoft.com/microsoft-edge/webview2/
   (Evergreen Bootstrapper).

No Node.js, no Tauri CLI and no Python are needed.

## Build

Double-click `build.bat`. The first build downloads the libraries it needs
(internet required). Keep the project folder on an SSD: the build writes
several GB of small files into `target\`.

The result:

    dist\Skyrim Tracker Extreme\Skyrim Tracker Extreme.exe
    dist\Skyrim Tracker Extreme v2.1.0.zip   (the release archive, version from tauri.conf.json)
