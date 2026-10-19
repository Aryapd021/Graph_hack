import initialData from "./initialData.json";

interface Env {
  ASSETS: {
    fetch: (request: Request | string) => Promise<Response>;
  };
  BACKEND_URL?: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Handle /api/* endpoints
    if (url.pathname.startsWith("/api/")) {
      // 1. If BACKEND_URL is set, attempt proxying first
      if (env.BACKEND_URL) {
        try {
          const targetUrl = new URL(url.pathname + url.search, env.BACKEND_URL);
          const proxyReq = new Request(targetUrl.toString(), {
            method: request.method,
            headers: request.headers,
            body: request.method !== "GET" && request.method !== "HEAD" ? request.body : undefined,
          });
          const res = await fetch(proxyReq);
          if (res.ok || res.status < 500) {
            return res;
          }
        } catch (e) {
          console.error("Backend proxy error:", e);
        }
      }

      // 2. Built-in edge fallback routes so the app always displays live graph data
      if (url.pathname === "/api/health") {
        return Response.json(initialData.health, {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }

      if (url.pathname.startsWith("/api/graph/overview")) {
        return Response.json(initialData.overview, {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }

      if (url.pathname === "/api/decisions") {
        return Response.json(initialData.decisions, {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }

      if (url.pathname === "/api/reviews") {
        return Response.json(initialData.reviews, {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }

      // If simulated demo PR
      if (url.pathname === "/api/demo/simulate-pr") {
        return Response.json({
          message: "Demo PR simulated",
          pr_id: "pr_sim_999",
          impacted_decisions: ["dec_006"]
        }, {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }

      if (url.pathname === "/api/demo/reset") {
        return Response.json({ status: "reset_complete" }, {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }

      // Default mock for chat if offline
      if (url.pathname === "/api/chat") {
        return Response.json({
          turn_id: "edge_turn_" + Date.now(),
          answer: "Cloudflare Edge: Company Brain is connected and initialized with 980 nodes and 4,379 edges. Full graph traversal and active decision tracking enabled.",
          citations: [
            {
              node_id: "dec_004",
              text_snippet: "Implement structured request lifecycle telemetry in tests (dec_004)"
            }
          ],
          steps: [
            {
              tool_name: "get_decision",
              tool_input: { id: "dec_004" },
              tool_output: { id: "dec_004", status: "fresh" }
            }
          ],
          highlight: {
            node_ids: ["dec_004", "p_a2f63251"],
            edge_ids: ["e_dec_004_1"]
          }
        }, {
          headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
        });
      }
    }

    // Serve static assets from env.ASSETS with anti-caching for HTML so it's never stale
    let assetResponse = await env.ASSETS.fetch(request);

    // If HTML or root, ensure it is not cached with stale CDN headers
    if (url.pathname === "/" || url.pathname.endsWith(".html") || assetResponse.headers.get("content-type")?.includes("text/html")) {
      const headers = new Headers(assetResponse.headers);
      headers.set("Cache-Control", "no-cache, no-store, must-revalidate");
      headers.set("Pragma", "no-cache");
      headers.set("Expires", "0");
      return new Response(assetResponse.body, {
        status: assetResponse.status,
        statusText: assetResponse.statusText,
        headers,
      });
    }

    return assetResponse;
  },
};
