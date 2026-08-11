# Desktop release build

The packaged desktop application does not resolve npm dependencies. It is assembled from two checksum-controlled inputs:

1. A self-contained `amaura-backend` sidecar produced by `scripts/build_desktop_backend.py`.
2. An official macOS Electron release ZIP supplied with its expected SHA-256 digest.

```bash
python scripts/build_desktop_backend.py
python scripts/build_desktop_app.py \
  --electron-zip /secure/build-inputs/electron-v33.0.2-darwin-arm64.zip \
  --electron-sha256 <verified-64-character-sha256> \
  --dmg
```

For a signed release, set `AMAURA_CODESIGN_IDENTITY` to the Apple Developer ID Application identity. Submit the resulting DMG to Apple's notarisation service in the release workflow. The Electron archive digest must be obtained and reviewed independently before the build; the build script never trusts a filename or a live package-manager resolution.
