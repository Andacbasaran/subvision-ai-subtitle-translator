import INDEX_HTML from "./index.html";

const SITE_ORIGIN = "https://subvisionai.andacbasaran.com";
const GITHUB_REPO = "Andacbasaran/subvision-ai-subtitle-translator";
const GITHUB_BRANCH = "main";
const RELEASES_FALLBACK_URL = `https://github.com/${GITHUB_REPO}/releases/latest`;
const APP_VERSION = "1.6.0";

const SEO_META = {
  tr: {
    lang: "tr",
    ogLocale: "tr_TR",
    ogLocaleAlt: "en_US",
    title: "SubVision AI — Ekrandaki Her Altyazı. Anında Türkçe.",
    description:
      "Oyunlar, diziler, filmler ve canlı yayınlar için Windows, macOS Apple Silicon (MPS) ve Linux / Steam Deck destekli, ~88 ms gecikmeli, 0 MB VRAM ve %100 çevrimdışı açık kaynak çok dilli altyazı çevirici.",
    ogDescription:
      "Oyunlar ve videolar için Windows, macOS Apple Silicon ve Linux / Steam Deck'te 0 MB VRAM ve sıfır FPS kaybıyla çalışan açık kaynak kodlu anlık altyazı çevirici.",
    imageAlt: "SubVision AI Studio v1.6.0 — Gerçek Zamanlı Ekran Üstü Altyazı Çevirici Arayüzü"
  },
  en: {
    lang: "en",
    ogLocale: "en_US",
    ogLocaleAlt: "tr_TR",
    title: "SubVision AI — Real-Time Offline Subtitle Translator (EN → TR)",
    description:
      "Ultra-low-latency (~88 ms), 100% offline, 0 MB VRAM real-time multi-language subtitle translator for PC games, movies, and live streams on Windows, macOS Apple Silicon (MPS), and Linux / Steam Deck.",
    ogDescription:
      "Open-source real-time on-screen & live-audio subtitle translator with 0 MB VRAM and zero FPS drop for Windows, macOS Apple Silicon & Linux / Steam Deck.",
    imageAlt: "SubVision AI Studio v1.6.0 — Real-Time On-Screen Subtitle Translator Interface"
  }
};

let cachedCommitSha = null;
let cachedAtMs = 0;
const SHA_CACHE_TTL_MS = 60 * 1000;

let cachedReleaseAssets = null;
let cachedReleaseAtMs = 0;
const RELEASE_CACHE_TTL_MS = 5 * 60 * 1000;

function parseCookieLang(cookieHeader) {
  if (!cookieHeader) return null;
  const match = cookieHeader.match(/(?:^|;\s*)sv_lang=(tr|en)(?:;|$)/i);
  return match ? match[1].toLowerCase() : null;
}

function detectLangFromAcceptLanguage(header) {
  if (!header) return "en";
  const parts = header
    .split(",")
    .map((segment) => {
      const [rawTag, ...params] = segment.trim().split(";");
      const tag = (rawTag || "").trim().toLowerCase();
      let q = 1.0;
      for (const p of params) {
        const m = p.trim().match(/^q=([0-9.]+)$/i);
        if (m) {
          const parsed = Number.parseFloat(m[1]);
          if (!Number.isNaN(parsed)) q = parsed;
        }
      }
      return { tag, q };
    })
    .filter((item) => item.tag && item.q > 0)
    .sort((a, b) => b.q - a.q);

  for (const item of parts) {
    if (item.tag === "tr" || item.tag.startsWith("tr-")) return "tr";
    if (item.tag === "en" || item.tag.startsWith("en-")) return "en";
  }
  return "en";
}

function resolveRequestLang(request, url) {
  const pathname = url.pathname.replace(/\/+$/, "") || "/";
  if (pathname === "/tr") return { lang: "tr", canonicalPath: "/tr", isExplicitPath: true };
  if (pathname === "/en") return { lang: "en", canonicalPath: "/en", isExplicitPath: true };

  const queryLang = (url.searchParams.get("lang") || "").toLowerCase();
  if (queryLang === "tr" || queryLang === "en") {
    return { lang: queryLang, canonicalPath: `/${queryLang}`, isExplicitPath: false };
  }

  const cookieLang = parseCookieLang(request.headers.get("Cookie"));
  if (cookieLang === "tr" || cookieLang === "en") {
    return { lang: cookieLang, canonicalPath: "/", isExplicitPath: false };
  }

  const acceptLang = detectLangFromAcceptLanguage(request.headers.get("Accept-Language"));
  return { lang: acceptLang, canonicalPath: "/", isExplicitPath: false };
}

function escapeHtmlAttr(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderLocalizedHtml(lang, canonicalPath) {
  const meta = SEO_META[lang] || SEO_META.en;
  const canonicalUrl = `${SITE_ORIGIN}${canonicalPath === "/" ? "/" : canonicalPath}`;

  let html = INDEX_HTML;
  html = html.replace(/<html lang="[^"]*">/, `<html lang="${meta.lang}">`);
  html = html.replace(/<title>[^<]*<\/title>/, `<title>${escapeHtmlAttr(meta.title)}</title>`);
  html = html.replace(
    /<meta name="description" content="[^"]*" \/>/,
    `<meta name="description" content="${escapeHtmlAttr(meta.description)}" />`
  );
  html = html.replace(
    /<meta property="og:url" content="[^"]*" \/>/,
    `<meta property="og:url" content="${canonicalUrl}" />`
  );
  html = html.replace(
    /<meta property="og:locale" content="[^"]*" \/>/,
    `<meta property="og:locale" content="${meta.ogLocale}" />`
  );
  html = html.replace(
    /<meta property="og:locale:alternate" content="[^"]*" \/>/,
    `<meta property="og:locale:alternate" content="${meta.ogLocaleAlt}" />`
  );
  html = html.replace(
    /<meta property="og:title" content="[^"]*" \/>/,
    `<meta property="og:title" content="${escapeHtmlAttr(meta.title)}" />`
  );
  html = html.replace(
    /<meta property="og:description" content="[^"]*" \/>/,
    `<meta property="og:description" content="${escapeHtmlAttr(meta.ogDescription)}" />`
  );
  html = html.replace(
    /<meta property="og:image:alt" content="[^"]*" \/>/,
    `<meta property="og:image:alt" content="${escapeHtmlAttr(meta.imageAlt)}" />`
  );
  html = html.replace(
    /<meta name="twitter:title" content="[^"]*" \/>/,
    `<meta name="twitter:title" content="${escapeHtmlAttr(meta.title)}" />`
  );
  html = html.replace(
    /<meta name="twitter:description" content="[^"]*" \/>/,
    `<meta name="twitter:description" content="${escapeHtmlAttr(meta.ogDescription)}" />`
  );
  html = html.replace(
    /<meta name="twitter:image:alt" content="[^"]*" \/>/,
    `<meta name="twitter:image:alt" content="${escapeHtmlAttr(meta.imageAlt)}" />`
  );
  html = html.replace(
    /<link rel="canonical" href="[^"]*" \/>/,
    `<link rel="canonical" href="${canonicalUrl}" />`
  );
  html = html.replace(
    /window\.__INITIAL_LANG__\s*=\s*null;/,
    `window.__INITIAL_LANG__ = "${meta.lang}";`
  );
  return html;
}

function buildSitemapXml() {
  const today = new Date().toISOString().slice(0, 10);
  const urls = [
    { loc: `${SITE_ORIGIN}/`, priority: "1.0" },
    { loc: `${SITE_ORIGIN}/en`, priority: "0.9" },
    { loc: `${SITE_ORIGIN}/tr`, priority: "0.9" }
  ];
  const entries = urls
    .map(
      ({ loc, priority }) => `  <url>
    <loc>${loc}</loc>
    <lastmod>${today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>${priority}</priority>
    <xhtml:link rel="alternate" hreflang="en" href="${SITE_ORIGIN}/en" />
    <xhtml:link rel="alternate" hreflang="tr" href="${SITE_ORIGIN}/tr" />
    <xhtml:link rel="alternate" hreflang="x-default" href="${SITE_ORIGIN}/" />
  </url>`
    )
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
${entries}
</urlset>
`;
}

function buildGithubHeaders(env, accept) {
  const headers = {
    "Accept": accept,
    "User-Agent": "SubVisionAI-Cloudflare-Worker"
  };
  if (env?.GITHUB_TOKEN) {
    headers["Authorization"] = `Bearer ${env.GITHUB_TOKEN}`;
  }
  return headers;
}

async function getLatestReleaseAssetUrls(env) {
  const now = Date.now();
  if (cachedReleaseAssets && (now - cachedReleaseAtMs) < RELEASE_CACHE_TTL_MS) {
    return cachedReleaseAssets;
  }
  const releaseDownloadBase = `https://github.com/${GITHUB_REPO}/releases/download/v${APP_VERSION}`;
  const result = {
    windowsUrl: `${releaseDownloadBase}/SubVisionAI-Setup-v${APP_VERSION}-Windows-x64.exe`,
    macosUrl: `${releaseDownloadBase}/SubVisionAI-v${APP_VERSION}-macOS-arm64.dmg`,
    linuxUrl: `${releaseDownloadBase}/SubVisionAI-v${APP_VERSION}-Linux-x86_64.tar.gz`
  };
  try {
    const resp = await fetch(
      `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`,
      {
        headers: buildGithubHeaders(env, "application/vnd.github+json"),
        cf: {
          cacheEverything: true,
          cacheTtl: 300
        }
      }
    );
    if (resp.ok) {
      const release = await resp.json();
      const assets = Array.isArray(release?.assets) ? release.assets : [];
      const winAsset =
        assets.find((a) => /^SubVisionAI-Setup-.*\.exe$/i.test(a?.name || "")) ||
        assets.find((a) => /\.exe$/i.test(a?.name || ""));
      const macAsset =
        assets.find((a) => /SubVisionAI.*macOS.*\.dmg$/i.test(a?.name || "")) ||
        assets.find((a) => /\.dmg$/i.test(a?.name || ""));
      const linuxAsset =
        assets.find((a) => /SubVisionAI.*Linux.*\.tar\.gz$/i.test(a?.name || "")) ||
        assets.find((a) => /\.tar\.gz$/i.test(a?.name || ""));
      if (winAsset?.browser_download_url) {
        result.windowsUrl = winAsset.browser_download_url;
      }
      if (macAsset?.browser_download_url) {
        result.macosUrl = macAsset.browser_download_url;
      }
      if (linuxAsset?.browser_download_url) {
        result.linuxUrl = linuxAsset.browser_download_url;
      }
      cachedReleaseAssets = result;
      cachedReleaseAtMs = now;
    }
  } catch (_) {
    // Fallback to versioned GitHub Releases download URLs if API is unreachable
  }
  return result;
}

async function getLatestGithubRawBase(env) {
  const now = Date.now();
  if (cachedCommitSha && (now - cachedAtMs) < SHA_CACHE_TTL_MS) {
    return `https://raw.githubusercontent.com/${GITHUB_REPO}/${cachedCommitSha}`;
  }
  try {
    const resp = await fetch(
      `https://api.github.com/repos/${GITHUB_REPO}/commits/${GITHUB_BRANCH}`,
      {
        headers: buildGithubHeaders(env, "application/vnd.github.VERSION.sha"),
        cf: {
          cacheEverything: true,
          cacheTtl: 60
        }
      }
    );
    if (resp.ok) {
      const sha = (await resp.text()).trim();
      if (/^[0-9a-f]{40}$/i.test(sha)) {
        cachedCommitSha = sha;
        cachedAtMs = now;
        return `https://raw.githubusercontent.com/${GITHUB_REPO}/${sha}`;
      }
    }
  } catch (_) {
    // Fallback to branch name if GitHub API is unreachable
  }
  return `https://raw.githubusercontent.com/${GITHUB_REPO}/${GITHUB_BRANCH}`;
}

const STATIC_ROUTES = {
  "/assets/ui_preview.png": {
    repoPath: "/assets/ui_preview.png",
    contentType: "image/png",
    cacheControl: "public, max-age=300, must-revalidate",
    edgeCacheTtl: 300
  },
  "/assets/ui_preview_history.png": {
    repoPath: "/assets/ui_preview_history.png",
    contentType: "image/png",
    cacheControl: "public, max-age=300, must-revalidate",
    edgeCacheTtl: 300
  },
  "/assets/ui_preview_settings.png": {
    repoPath: "/assets/ui_preview_settings.png",
    contentType: "image/png",
    cacheControl: "public, max-age=300, must-revalidate",
    edgeCacheTtl: 300
  },
  "/assets/benchmark_chart.png": {
    repoPath: "/assets/benchmark_chart.png",
    contentType: "image/png",
    cacheControl: "public, max-age=300, must-revalidate",
    edgeCacheTtl: 300
  },
  "/assets/app_icon.png": {
    repoPath: "/assets/app_icon.png",
    contentType: "image/png",
    cacheControl: "public, max-age=3600",
    edgeCacheTtl: 3600
  },
  "/assets/app_icon.ico": {
    repoPath: "/assets/app_icon.ico",
    contentType: "image/x-icon",
    cacheControl: "public, max-age=3600",
    edgeCacheTtl: 3600
  },
  "/favicon.ico": {
    repoPath: "/assets/app_icon.ico",
    contentType: "image/x-icon",
    cacheControl: "public, max-age=3600",
    edgeCacheTtl: 3600
  }
};

const HTML_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data:",
  "connect-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'self'"
].join("; ");

function withSecurityHeaders(headersInit = {}, { isHtml = false } = {}) {
  const headers = new Headers(headersInit);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  headers.set("X-Frame-Options", "SAMEORIGIN");
  headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()");
  headers.set("Cross-Origin-Opener-Policy", "same-origin");
  if (isHtml) {
    headers.set("Content-Security-Policy", HTML_CSP);
  }
  return headers;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    const normalizedPath = pathname.replace(/\/+$/, "") || "/";
    const isHead = request.method === "HEAD";

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", {
        status: 405,
        headers: withSecurityHeaders({
          "Allow": "GET, HEAD",
          "Content-Type": "text/plain; charset=utf-8"
        })
      });
    }

    try {
      console.log(JSON.stringify({
        message: "incoming_request",
        method: request.method,
        path: pathname,
        version: APP_VERSION
      }));

      if (
        normalizedPath === "/" ||
        normalizedPath === "/index.html" ||
        normalizedPath === "/tr" ||
        normalizedPath === "/en"
      ) {
        const { lang, canonicalPath, isExplicitPath } = resolveRequestLang(request, url);
        const html = renderLocalizedHtml(lang, canonicalPath);
        const headers = withSecurityHeaders(
          {
            "Content-Type": "text/html; charset=utf-8",
            "Content-Language": lang,
            "Cache-Control": isExplicitPath
              ? "public, max-age=120, must-revalidate"
              : "private, max-age=60, must-revalidate"
          },
          { isHtml: true }
        );
        if (!isExplicitPath) {
          headers.set("Vary", "Accept-Language, Cookie");
        }
        return new Response(isHead ? null : html, { status: 200, headers });
      }

      if (pathname === "/robots.txt") {
        const headers = withSecurityHeaders({
          "Content-Type": "text/plain; charset=utf-8",
          "Cache-Control": "public, max-age=86400"
        });
        return new Response(
          isHead ? null : `User-agent: *\nAllow: /\nSitemap: ${SITE_ORIGIN}/sitemap.xml\n`,
          { status: 200, headers }
        );
      }

      if (pathname === "/sitemap.xml") {
        const headers = withSecurityHeaders({
          "Content-Type": "application/xml; charset=utf-8",
          "Cache-Control": "public, max-age=3600"
        });
        return new Response(isHead ? null : buildSitemapXml(), { status: 200, headers });
      }

      if (pathname === "/downloads/SubVisionAI.exe" || pathname === "/SubVisionAI.exe") {
        const { windowsUrl } = await getLatestReleaseAssetUrls(env);
        return Response.redirect(windowsUrl || RELEASES_FALLBACK_URL, 302);
      }

      if (pathname === "/downloads/SubVisionAI-macOS.dmg") {
        const { macosUrl } = await getLatestReleaseAssetUrls(env);
        return Response.redirect(macosUrl || RELEASES_FALLBACK_URL, 302);
      }

      if (pathname === "/downloads/SubVisionAI-Linux.tar.gz") {
        const { linuxUrl } = await getLatestReleaseAssetUrls(env);
        return Response.redirect(linuxUrl || RELEASES_FALLBACK_URL, 302);
      }

      const route = STATIC_ROUTES[pathname];
      if (route) {
        const rawBase = await getLatestGithubRawBase(env);
        const upstreamUrl = `${rawBase}${route.repoPath}`;
        const upstreamResp = await fetch(upstreamUrl, {
          cf: {
            cacheEverything: true,
            cacheTtl: route.edgeCacheTtl || 300
          }
        });

        if (!upstreamResp.ok) {
          console.error(JSON.stringify({
            message: "upstream_asset_fetch_failed",
            path: pathname,
            upstreamUrl,
            status: upstreamResp.status
          }));
          return Response.json(
            { error: "Asset temporarily unavailable", status: upstreamResp.status },
            { status: 502, headers: withSecurityHeaders() }
          );
        }

        const headers = withSecurityHeaders({
          "Content-Type": route.contentType,
          "Cache-Control": route.cacheControl
        });
        if (route.disposition) {
          headers.set("Content-Disposition", route.disposition);
        }
        const contentLength = upstreamResp.headers.get("content-length");
        if (contentLength) {
          headers.set("Content-Length", contentLength);
        }

        return new Response(isHead ? null : upstreamResp.body, {
          status: isHead ? 200 : upstreamResp.status,
          headers
        });
      }

      return new Response(isHead ? null : "Not Found", {
        status: 404,
        headers: withSecurityHeaders({
          "Content-Type": "text/plain; charset=utf-8",
          "Cache-Control": "no-store"
        })
      });
    } catch (error) {
      const errMessage = error instanceof Error ? error.message : String(error);
      console.error(JSON.stringify({
        message: "unhandled_worker_error",
        path: pathname,
        error: errMessage
      }));
      return Response.json(
        { error: "Internal server error" },
        { status: 500, headers: withSecurityHeaders() }
      );
    }
  }
};
