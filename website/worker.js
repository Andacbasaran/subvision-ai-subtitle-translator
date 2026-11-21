import INDEX_HTML from "./index.html";

const GITHUB_REPO = "Andacbasaran/subvision-ai-subtitle-translator";
const GITHUB_BRANCH = "main";

let cachedCommitSha = null;
let cachedAtMs = 0;
const SHA_CACHE_TTL_MS = 60 * 1000;

async function getLatestGithubRawBase() {
  const now = Date.now();
  if (cachedCommitSha && (now - cachedAtMs) < SHA_CACHE_TTL_MS) {
    return `https://raw.githubusercontent.com/${GITHUB_REPO}/${cachedCommitSha}`;
  }
  try {
    const resp = await fetch(
      `https://api.github.com/repos/${GITHUB_REPO}/commits/${GITHUB_BRANCH}`,
      {
        headers: {
          "Accept": "application/vnd.github.VERSION.sha",
          "User-Agent": "SubVisionAI-Cloudflare-Worker"
        },
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
  "/downloads/SubVisionAI.exe": {
    repoPath: "/SubVisionAI.exe",
    contentType: "application/vnd.microsoft.portable-executable",
    disposition: 'attachment; filename="SubVisionAI.exe"',
    cacheControl: "no-store, no-cache, must-revalidate, max-age=0",
    edgeCacheTtl: 60
  },
  "/SubVisionAI.exe": {
    repoPath: "/SubVisionAI.exe",
    contentType: "application/vnd.microsoft.portable-executable",
    disposition: 'attachment; filename="SubVisionAI.exe"',
    cacheControl: "no-store, no-cache, must-revalidate, max-age=0",
    edgeCacheTtl: 60
  },
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

function withSecurityHeaders(headersInit = {}) {
  const headers = new Headers(headersInit);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  headers.set("X-Frame-Options", "SAMEORIGIN");
  return headers;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname;

    try {
      console.log(JSON.stringify({
        message: "incoming_request",
        method: request.method,
        path: pathname
      }));

      if (pathname === "/" || pathname === "/index.html") {
        const headers = withSecurityHeaders({
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "public, max-age=60, must-revalidate"
        });
        return new Response(INDEX_HTML, { status: 200, headers });
      }

      if (pathname === "/robots.txt") {
        const headers = withSecurityHeaders({
          "Content-Type": "text/plain; charset=utf-8",
          "Cache-Control": "public, max-age=86400"
        });
        return new Response("User-agent: *\nAllow: /\n", { status: 200, headers });
      }

      const route = STATIC_ROUTES[pathname];
      if (route) {
        const rawBase = await getLatestGithubRawBase();
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

        return new Response(upstreamResp.body, {
          status: request.method === "HEAD" ? 200 : upstreamResp.status,
          headers
        });
      }

      return Response.redirect(`${url.origin}/`, 302);
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
