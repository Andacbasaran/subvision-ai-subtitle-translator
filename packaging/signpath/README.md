# SignPath.io Free Open-Source Code Signing Guide

**SubVision AI** currently signs release executables with a self-signed SHA-256 Authenticode certificate + DigiCert RFC 3161 timestamp (`build_exe.py`). While Windows Defender reports **0 Threats**, Windows SmartScreen may still show an "Unknown Publisher" prompt for new downloads until binaries are signed by a trusted public CA.

[SignPath Foundation](https://signpath.org/) provides **free, trusted EV/OV code signing** for eligible open-source projects via GitHub Actions.

## Steps to Activate SignPath.io for SubVision AI

1. **Apply for the SignPath Open Source Program:**
   - Visit [https://signpath.org/terms](https://signpath.org/terms) and submit the repository `https://github.com/Andacbasaran/subvision-ai-subtitle-translator`.
   - Ensure `LICENSE` (MIT), `SECURITY.md`, and public CI builds (`.github/workflows/release-windows.yml`) are active (all already present).
2. **Create SignPath Project & Artifact Configuration:**
   - Organization slug: `subvision-ai`
   - Project slug: `subvision-ai`
   - Signing policy: `release-signing` (requires maintainer approval for release tags).
3. **Add GitHub Repository Secrets:**
   - `SIGNPATH_API_TOKEN`
   - `SIGNPATH_ORGANIZATION_ID`
4. **Add the SignPath GitHub Action Step to `.github/workflows/release-windows.yml`:**
   ```yaml
   - name: Submit artifacts to SignPath.io
     if: startsWith(github.ref, 'refs/tags/v') && secrets.SIGNPATH_API_TOKEN != ''
     uses: signpath/github-action-submit-signing-request@v1
     with:
       api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
       organization-id: ${{ secrets.SIGNPATH_ORGANIZATION_ID }}
       project-slug: subvision-ai
       artifact-configuration-slug: release-zip
       signing-policy-slug: release-signing
       github-artifact-id: ${{ steps.upload.outputs.artifact-id }}
       wait-for-completion: true
       output-artifact-directory: signed_out
   ```
5. **Publish Signed Binaries:** Upload the signed `.exe` / `.zip` files and regenerate `SHA256SUMS.txt` before publishing the GitHub Release.
