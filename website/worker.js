import INDEX_HTML from "./index.html";

const GITHUB_RAW_BASE = "https://raw.githubusercontent.com/Andacbasaran/subvision-ai-subtitle-translator/0e3045e1e18d3ce226f14df50619c4b5fea80f5d";

const STATIC_ROUTES = {
  "/downloads/SubVisionAI.exe": {
    upstream: `${GITHUB_RAW_BASE}/SubVisionAI.exe`,
    contentType: "application/vnd.microsoft.portable-executable",
    disposition: 'attachment; filename="SubVisionAI.exe"',
    cacheControl: "public, max-age=3600"
  },
  "/SubVisionAI.exe": {
    upstream: `${GITHUB_RAW_BASE}/SubVisionAI.exe`,
    contentType: "application/vnd.microsoft.portable-executable",
    disposition: 'attachment; filename="SubVisionAI.exe"',
    cacheControl: "public, max-age=3600"
  },
  "/assets/ui_preview.png": {
    upstream: `${GITHUB_RAW_BASE}/assets/ui_preview.png`,
    contentType: "image/png",
    cacheControl: "public, max-age=86400"
  },
  "/assets/benchmark_chart.png": {
    upstream: `${GITHUB_RAW_BASE}/assets/benchmark_chart.png`,
    contentType: "image/png",
    cacheControl: "public, max-age=86400"
  },
  "/assets/app_icon.png": {
    upstream: `${GITHUB_RAW_BASE}/assets/app_icon.png`,
    contentType: "image/png",
    cacheControl: "public, max-age=86400"
  },
  "/assets/app_icon.ico": {
    upstream: `${GITHUB_RAW_BASE}/assets/app_icon.ico`,
    contentType: "image/x-icon",
    cacheControl: "public, max-age=86400"
  },
  "/favicon.ico": {
    upstream: `${GITHUB_RAW_BASE}/assets/app_icon.ico`,
    contentType: "image/x-icon",
    cacheControl: "public, max-age=86400"
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
          "Cache-Control": "public, max-age=120"
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
        const upstreamResp = await fetch(route.upstream, {
          cf: {
            cacheEverything: true,
            cacheTtl: 86400
          }
        });

        if (!upstreamResp.ok) {
          console.error(JSON.stringify({
            message: "upstream_asset_fetch_failed",
            path: pathname,
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
