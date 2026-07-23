# Release downloads

Tag builds publish these assets alongside the npm tarball:

| Platform | Release asset | Contents |
| --- | --- | --- |
| Windows x64 (Intel / AMD) | `Gloss-windows-x64.exe` and `Gloss.exe` | Standalone desktop application |
| Windows ARM64 | `Gloss-windows-x64.exe` | Runs through Windows x64 emulation; no native ARM64 binary yet |
| Windows x86 (32-bit) | Not supported | Use a 64-bit Windows installation |
| Linux / macOS | `gloss-local-<version>.tgz` | Run the local browser app through npm or Bun |
| Source | `Gloss-source-<version>.tar.gz` | Source checkout for `npm run setup` / `npm start` |

The Windows executables are portable: download the matching `.exe` and open it
directly—no archive extraction, terminal, or browser tab is needed. `Gloss.exe`
is kept as an x64 compatibility download. The desktop app uses Microsoft Edge
WebView2, which is included with current Windows 10 and Windows 11 releases.
