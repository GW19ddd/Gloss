# Release downloads

Tag builds publish these assets alongside the npm tarball:

| Platform | Release asset | Contents |
| --- | --- | --- |
| Windows x64 | `Gloss.exe` and `Gloss-windows-x64.zip` | Portable desktop executable |
| Windows ARM64 | `Gloss-windows-arm64.zip` | Portable desktop executable |
| macOS Intel | `Gloss-macos-x64.tar.gz` | `Gloss` desktop executable |
| macOS Apple Silicon | `Gloss-macos-arm64.tar.gz` | `Gloss` desktop executable |
| Linux x64 | `Gloss-linux-x64.tar.gz` | `Gloss` desktop executable |
| Linux ARM64 | `Gloss-linux-arm64.tar.gz` | `Gloss` desktop executable |
| Source | `Gloss-source-<version>.tar.gz` | Source checkout for `npm run setup` / `npm start` |

Unpack `.zip` or `.tar.gz` files before running the executable. macOS users may
need to clear the quarantine attribute for an unsigned download:

```bash
xattr -dr com.apple.quarantine Gloss
```

The Windows desktop package uses Microsoft Edge WebView2. macOS and Linux use
the GUI backend selected by `pywebview`; Linux systems need the corresponding
desktop-webview libraries supplied by their distribution.
