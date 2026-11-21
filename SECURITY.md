# Security Policy

## Supported Versions

| Version | Supported |
| :--- | :---: |
| `1.4.x` (Latest) | ✅ |
| `1.3.x` | ⚠️ Security fixes only |
| `< 1.3.0` | ❌ |

## Privacy & Offline-First Architecture

- **Default Mode (100% Offline):** SubVision AI runs RapidOCR (ONNX CPU) and CTranslate2 INT8 completely locally on your machine. No screenshots, subtitles, or telemetry leave your computer.
- **Optional Context Backends:** If you explicitly enable an external API (Gemini, DeepL, OpenAI-compatible) in Settings, only the recognized subtitle text and the last 3 lines of dialogue context are sent directly to your configured endpoint using your own API key. API keys are stored locally in `user_settings.json` and never transmitted anywhere else.
- **Optional Update Checker:** Queries the public GitHub Releases API (`api.github.com`) only to compare version tags. Can be disabled anytime in *Settings → Update Checker*.

## Binary Integrity & Code Signing

- Every official GitHub Release includes a `SHA256SUMS.txt` file so you can verify download integrity before running:
  ```powershell
  Get-FileHash .\SubVisionAI-Setup-v1.4.0-Windows-x64.exe -Algorithm SHA256
  ```
- Releases are scanned with Microsoft Windows Defender (`MpCmdRun.exe -Scan -ScanType 3`, 0 threats) and signed with SHA-256 Authenticode + DigiCert RFC 3161 timestamping.
- **SignPath.io Open-Source Signing Roadmap:** See [packaging/signpath/README.md](packaging/signpath/README.md) for our integration setup with SignPath.io's free Open Source Code Signing program to eliminate Windows SmartScreen warnings completely.

## Reporting a Vulnerability

If you discover a security vulnerability, **please do not open a public issue**. Instead:

1. Use **GitHub Private Vulnerability Reporting** (*Security → Advisories → Report a vulnerability*) on this repository, or
2. Contact the maintainer directly via the profile email listed on [github.com/Andacbasaran](https://github.com/Andacbasaran).

We aim to acknowledge reports within **48 hours** and release a fix as quickly as possible.
