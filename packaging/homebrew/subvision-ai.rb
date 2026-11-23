# Homebrew Cask for SubVision AI (macOS Apple Silicon)
#
# After publishing a GitHub Release, replace `sha256` with the checksum for
# `SubVisionAI-v1.5.0-macOS-arm64.dmg` from the release's `SHA256SUMS.txt`.
#
# Install locally from this file:
#   brew install --cask ./packaging/homebrew/subvision-ai.rb
#
# Or publish in a personal tap repository (e.g. `Andacbasaran/homebrew-tap`
# under `Casks/subvision-ai.rb`) so users can install with:
#   brew tap Andacbasaran/tap
#   brew install --cask subvision-ai

cask "subvision-ai" do
  arch arm: "arm64"

  version "1.5.0"
  sha256 "REPLACE_WITH_SHA256_FROM_RELEASE_SHA256SUMS_TXT"

  url "https://github.com/Andacbasaran/subvision-ai-subtitle-translator/releases/download/v#{version}/SubVisionAI-v#{version}-macOS-#{arch}.dmg",
      verified: "github.com/Andacbasaran/subvision-ai-subtitle-translator/"
  name "SubVision AI"
  desc "Real-time, 100% offline English-to-Turkish on-screen & live-audio subtitle translator"
  homepage "https://subvisionai.andacbasaran.com/"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on arch: :arm64
  depends_on macos: ">= :ventura"

  app "SubVision AI.app"

  zap trash: [
    "~/Library/Application Support/SubVision AI",
    "~/Library/Caches/SubVision AI",
    "~/Library/Preferences/com.andacbasaran.subvisionai.plist",
    "~/Library/Saved Application State/com.andacbasaran.subvisionai.savedState",
  ]
end
