const ENCODER = new TextEncoder();

const SOURCES = {
  wetest: "https://www.wetest.vip/page/cloudflare/address_v4.html",
  uouin: "https://api.uouin.com/cloudflare.html",
  v2too: "https://ip.v2too.top",
  xyz: "https://ip.164746.xyz",
  vps789: "https://vps789.com/public/sum/cfIpApi",
  vvhan: "https://api.4ce.cn/api/bestCFIP",
  mrxn: "https://raw.githubusercontent.com/xingpingcn/enhanced-FaaS-in-China/refs/heads/main/Vercel.json"
};

const DATA_CACHE_KEY = "system_aggregated_data_v5";
const CACHE_TTL = 3600;
const STATS_SAMPLE_RATE = 0.05;

function parseBoolean(value) {
  const text = String(value ?? "").trim().toLowerCase();
  return text === "true" || text === "1" || text === "on" || text === "yes";
}

function parsePositiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (Number.isNaN(parsed) || parsed <= 0) return fallback;
  return parsed;
}

function toHex(buffer) {
  return Array.from(new Uint8Array(buffer))
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
}

async function hmacSha256Hex(secret, data) {
  const key = await crypto.subtle.importKey(
    "raw",
    ENCODER.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, ENCODER.encode(data));
  return toHex(sig);
}

async function sha256Hex(data) {
  const digest = await crypto.subtle.digest("SHA-256", ENCODER.encode(data));
  return toHex(digest);
}

function sortIPv4(ips) {
  return ips.sort((a, b) => {
    const aa = a.split(".").map((n) => Number.parseInt(n, 10));
    const bb = b.split(".").map((n) => Number.parseInt(n, 10));
    for (let i = 0; i < 4; i += 1) {
      if (aa[i] !== bb[i]) return aa[i] - bb[i];
    }
    return 0;
  });
}

function extractIPv4(rawText) {
  const ipRegex = /\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?\d\d?)\b/g;
  const found = rawText.match(ipRegex) || [];
  const set = new Set();
  for (const ipAddr of found) {
    if (ipAddr === "0.0.0.0" || ipAddr === "127.0.0.1") continue;
    set.add(ipAddr);
  }
  return sortIPv4([...set]);
}

function getClientIp(request) {
  const cf = request.headers.get("CF-Connecting-IP");
  if (cf) return cf.trim();
  const xff = request.headers.get("x-forwarded-for");
  if (!xff) return "";
  return xff.split(",")[0].trim();
}

function jsonResponse(body, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json",
      ...extraHeaders
    }
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function buildTksPage(env) {
  const title = escapeHtml(env.TKS_TITLE || "Thanks");
  const descRaw = String(
    env.TKS_TEXT || "This page is powered by Cloudflare Workers."
  );
  const imageUrl = String(env.TKS_IMAGE_URL || "").trim();
  const safeImageUrl = escapeHtml(imageUrl);
  const paragraphs = descRaw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join("\n");

  const imageBlock = safeImageUrl
    ? `<img src="${safeImageUrl}" alt="tks-image" />`
    : `<div class="placeholder">Set TKS_IMAGE_URL to show your image.</div>`;

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title}</title>
  <style>
    :root {
      --bg: #f6f7fb;
      --card: #ffffff;
      --text: #1c2333;
      --muted: #6b7280;
      --line: #d9deea;
      --shadow: 0 10px 35px rgba(16, 24, 40, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(145deg, #eef2ff, #f8fafc);
      color: var(--text);
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 20px;
    }
    .card {
      width: min(760px, 96vw);
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .media {
      width: 100%;
      background: #f1f5f9;
      display: grid;
      place-items: center;
      min-height: 180px;
    }
    img {
      width: 100%;
      height: auto;
      display: block;
      max-height: 460px;
      object-fit: cover;
    }
    .placeholder {
      color: var(--muted);
      font-size: 14px;
      padding: 24px;
      text-align: center;
    }
    .content {
      padding: 24px;
    }
    h1 {
      margin: 0 0 12px;
      font-size: 28px;
      line-height: 1.2;
      letter-spacing: 0.2px;
    }
    p {
      margin: 0 0 10px;
      color: #3f4759;
      line-height: 1.6;
    }
    .footer {
      padding: 0 24px 20px;
      color: var(--muted);
      font-size: 12px;
    }
  </style>
</head>
<body>
  <main class="card">
    <section class="media">${imageBlock}</section>
    <section class="content">
      <h1>${title}</h1>
      ${paragraphs || "<p>No description.</p>"}
    </section>
    <div class="footer">Path: /tks</div>
  </main>
</body>
</html>`;
}

function isValidClientId(value) {
  return /^[A-Za-z0-9._:@-]{3,128}$/.test(value);
}

function isValidHwid(value) {
  return /^[A-Za-z0-9._:-]{8,128}$/.test(value);
}

function isValidNonce(value) {
  return /^[A-Za-z0-9_-]{8,128}$/.test(value);
}

function isValidToken(value) {
  return /^[a-fA-F0-9]{64}$/.test(value);
}

function isValidInviteCode(value) {
  return /^[A-Za-z0-9_-]{6,128}$/.test(value);
}

function parseRegisterPolicy(value) {
  const raw = String(value ?? "").trim().toLowerCase();
  if (raw === "admin" || raw === "invite" || raw === "open") return raw;
  return "open";
}

function scheduleOneTimeClientBurn(authContext, kv, ctx) {
  if (!kv || !ctx || !authContext || !authContext.principal) return;
  if (authContext.role !== "user") return;
  if (authContext.principal.one_time !== true) return;
  if (!authContext.principal.kvKey) return;
  ctx.waitUntil(kv.delete(authContext.principal.kvKey));
}

async function authorizeRequest(request, env, path) {
  const kv = env.KV;
  const disableAuth = parseBoolean(env.DISABLE_AUTH);
  if (disableAuth) {
    return {
      authorized: true,
      role: "bypass",
      hwid: request.headers.get("x-hwid") || "",
      clientId: "bypass",
      authMode: "bypass",
      principal: null
    };
  }

  const adminKey = env.SECRET_KEY;
  const legacyKey = request.headers.get("x-auth-key") || "";
  if (adminKey && legacyKey && legacyKey === adminKey) {
    return {
      authorized: true,
      role: "admin",
      hwid: request.headers.get("x-hwid") || "",
      clientId: "admin",
      authMode: "admin-key",
      principal: null
    };
  }

  if (!kv) {
    return { authorized: false, reason: "kv_not_bound" };
  }

  const clientId = request.headers.get("x-client-id") || "";
  const hwid = request.headers.get("x-hwid") || "";
  const tsRaw = request.headers.get("x-ts") || "";
  const nonce = request.headers.get("x-nonce") || "";
  const token = request.headers.get("x-token") || "";

  if (!clientId || !hwid || !tsRaw || !nonce || !token) {
    return { authorized: false, reason: "missing_signed_headers" };
  }
  if (!isValidClientId(clientId)) {
    return { authorized: false, reason: "bad_client_id" };
  }
  if (!isValidHwid(hwid)) {
    return { authorized: false, reason: "bad_hwid" };
  }
  if (!isValidNonce(nonce)) {
    return { authorized: false, reason: "bad_nonce" };
  }
  if (!isValidToken(token)) {
    return { authorized: false, reason: "bad_token_shape" };
  }

  const ts = Number.parseInt(tsRaw, 10);
  if (!Number.isFinite(ts)) {
    return { authorized: false, reason: "bad_timestamp" };
  }

  const nowSec = Math.floor(Date.now() / 1000);
  const authWindowSec = Math.max(10, Math.min(600, parsePositiveInt(env.AUTH_WINDOW_SEC, 90)));
  if (Math.abs(nowSec - ts) > authWindowSec) {
    return { authorized: false, reason: "timestamp_expired" };
  }

  const clientKvKey = `client:${clientId}`;
  const clientJson = await kv.get(clientKvKey);
  if (!clientJson) {
    return { authorized: false, reason: "client_not_found" };
  }

  let clientData;
  try {
    clientData = JSON.parse(clientJson);
  } catch (err) {
    return { authorized: false, reason: "client_json_invalid" };
  }

  if (clientData && clientData.disabled === true) {
    return { authorized: false, reason: "client_disabled" };
  }

  if (clientData && typeof clientData.expires_at === "string") {
    const exp = Date.parse(clientData.expires_at);
    if (!Number.isNaN(exp) && Date.now() > exp) {
      return { authorized: false, reason: "client_expired" };
    }
  }

  const clientSecret = clientData?.secret || clientData?.token_secret;
  if (!clientSecret || typeof clientSecret !== "string") {
    return { authorized: false, reason: "client_secret_missing" };
  }

  const boundHwid = clientData?.hwid || clientData?.bound_hwid;
  if (boundHwid && boundHwid !== hwid) {
    return { authorized: false, reason: "hwid_mismatch" };
  }

  const canonical = `${request.method.toUpperCase()}\n${path}\n${ts}\n${nonce}\n${hwid}`;
  const expectedToken = await hmacSha256Hex(clientSecret, canonical);
  if (expectedToken !== token.toLowerCase()) {
    return { authorized: false, reason: "token_invalid" };
  }

  const nonceKey = `auth:nonce:${clientId}:${ts}:${nonce}`;
  const tokenHash = await sha256Hex(token.toLowerCase());
  const burnKey = `auth:burn:${clientId}:${tokenHash}`;
  const [nonceUsed, tokenUsed] = await Promise.all([kv.get(nonceKey), kv.get(burnKey)]);
  if (nonceUsed || tokenUsed) {
    return { authorized: false, reason: "token_replayed" };
  }

  const replayTtl = authWindowSec + 60;
  await Promise.all([
    kv.put(nonceKey, nowSec.toString(), { expirationTtl: replayTtl }),
    kv.put(burnKey, nowSec.toString(), { expirationTtl: replayTtl })
  ]);

  return {
    authorized: true,
    role: clientData?.role || "user",
    hwid,
    clientId,
    authMode: "signed-v1",
    principal: {
      ...clientData,
      kvKey: clientKvKey
    }
  };
}

async function fetchAggregatedData() {
  const results = {};
  await Promise.all(
    Object.entries(SOURCES).map(async ([key, srcUrl]) => {
      const startedAt = Date.now();
      try {
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), 5000);
        const res = await fetch(srcUrl, { signal: controller.signal });
        clearTimeout(id);
        const text = (await res.text()).trim();
        const ips = extractIPv4(text);
        results[key] = {
          status: "ok",
          source: srcUrl,
          fetch_ms: Date.now() - startedAt,
          ip_count: ips.length,
          ips
        };
      } catch (err) {
        results[key] = {
          status: "error",
          source: srcUrl,
          fetch_ms: Date.now() - startedAt,
          error: "fetch"
        };
      }
    })
  );

  const okSources = Object.values(results).filter((item) => item.status === "ok");
  const failedSources = Object.values(results).filter((item) => item.status !== "ok");
  const globalSet = new Set(okSources.flatMap((item) => item.ips || []));
  const globalUniqueIps = sortIPv4([...globalSet]);

  return JSON.stringify(
    {
      timestamp: new Date().toISOString(),
      meta: {
        cache_key: DATA_CACHE_KEY,
        sources_total: Object.keys(SOURCES).length,
        sources_ok: okSources.length,
        sources_failed: failedSources.length,
        global_unique_ip_count: globalUniqueIps.length
      },
      global: {
        unique_ips: globalUniqueIps
      },
      data: results
    },
    null,
    2
  );
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const kv = env.KV;
    const authDebug = parseBoolean(env.AUTH_DEBUG);

    if (path === "/api/register-once" && request.method.toUpperCase() === "POST") {
      if (!kv) {
        return jsonResponse({ error: "KV not bound" }, 500);
      }

      const registerPolicy = parseRegisterPolicy(env.REGISTER_POLICY);
      const adminKey = env.SECRET_KEY;
      const incomingAdminKey = request.headers.get("x-auth-key") || "";

      let body;
      try {
        body = await request.json();
      } catch (err) {
        return jsonResponse({ error: "Invalid JSON body" }, 400);
      }

      if (registerPolicy === "admin") {
        if (!adminKey || incomingAdminKey !== adminKey) {
          return jsonResponse({ error: "Access Denied" }, 403);
        }
      } else if (registerPolicy === "invite") {
        const inviteCode = String(body?.invite_code || "").trim();
        if (!isValidInviteCode(inviteCode)) {
          return jsonResponse({ error: "Invalid invite_code" }, 400);
        }
        const inviteKey = `invite:${inviteCode}`;
        const inviteRaw = await kv.get(inviteKey);
        if (!inviteRaw) {
          return jsonResponse({ error: "Invite not found or used" }, 403);
        }
        await kv.delete(inviteKey);
      }

      const clientIdRaw = String(body?.client_id || "").trim();
      const secretRaw = String(body?.secret || "").trim();
      const hwidRaw = String(body?.hwid || "").trim();
      const role = String(body?.role || "user").trim() || "user";
      const oneTime = body?.one_time !== false;
      const ttlSec = Math.max(30, Math.min(1800, parsePositiveInt(body?.ttl_sec, 180)));

      const generatedClientId = `auto-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      const generatedSecret = toHex(crypto.getRandomValues(new Uint8Array(32)));
      const clientId = clientIdRaw || generatedClientId;
      const secret = secretRaw || generatedSecret;
      const hwid = hwidRaw;

      if (!isValidClientId(clientId)) {
        return jsonResponse({ error: "Invalid client_id" }, 400);
      }
      if (typeof secret !== "string" || secret.length < 32 || secret.length > 256) {
        return jsonResponse({ error: "Invalid secret length" }, 400);
      }
      if (!isValidHwid(hwid)) {
        return jsonResponse({ error: "Invalid hwid" }, 400);
      }

      const now = new Date();
      const expiresAt = new Date(now.getTime() + ttlSec * 1000).toISOString();
      const record = {
        secret,
        hwid,
        role,
        one_time: oneTime,
        created_at: now.toISOString(),
        expires_at: expiresAt
      };

      await kv.put(`client:${clientId}`, JSON.stringify(record), { expirationTtl: ttlSec + 120 });
      return jsonResponse({
        ok: true,
        register_policy: registerPolicy,
        client_id: clientId,
        secret,
        one_time: oneTime,
        expires_at: expiresAt
      });
    }

    const isProtectedRoute = path === "/" || path === "/api/data";
    let authContext = {
      authorized: true,
      role: "public",
      hwid: "",
      clientId: "public",
      authMode: "none",
      principal: null
    };

    if (isProtectedRoute) {
      authContext = await authorizeRequest(request, env, path);
      if (!authContext.authorized) {
        const body = { error: "Access Denied" };
        if (authDebug && authContext.reason) {
          body.reason = authContext.reason;
        }
        return jsonResponse(body, 403);
      }
    }

    if (path === "/") {
      return jsonResponse(
        {
          kv_bound: !!kv,
          cache_ttl: CACHE_TTL,
          auth_mode: authContext.authMode,
          auth_window_sec: Math.max(10, Math.min(600, parsePositiveInt(env.AUTH_WINDOW_SEC, 90))),
          sources: Object.keys(SOURCES)
        },
        200
      );
    }

    if (path === "/api/data") {
      const hwid = authContext.hwid || request.headers.get("x-hwid") || "";
      const ip = getClientIp(request);

      if (authContext.role === "user") {
        if (!ip || !hwid) {
          return jsonResponse({ error: "Missing ip or hwid" }, 400);
        }

        const rateKey = `rate:${authContext.clientId}:${ip}:${hwid}`;
        const last = await kv.get(rateKey);
        const now = Date.now();
        if (last) {
          const diff = now - Number.parseInt(last, 10);
          if (diff < 60000) {
            return jsonResponse({ error: "Too Many Requests" }, 429);
          }
        }
        ctx.waitUntil(kv.put(rateKey, now.toString(), { expirationTtl: 120 }));
      }

      if (
        authContext.role === "user" &&
        authContext.principal &&
        authContext.principal.one_time !== true &&
        kv &&
        Math.random() < STATS_SAMPLE_RATE
      ) {
        const updated = { ...authContext.principal };
        updated.usage = (updated.usage || 0) + (1 / STATS_SAMPLE_RATE);
        updated.last_active = new Date().toISOString();
        updated.last_ip = ip;
        updated.last_hwid = hwid;
        ctx.waitUntil(kv.put(updated.kvKey, JSON.stringify(updated)));
      }

      if (kv) {
        const cachedData = await kv.get(DATA_CACHE_KEY);
        if (cachedData) {
          scheduleOneTimeClientBurn(authContext, kv, ctx);
          return new Response(cachedData, {
            headers: {
              "content-type": "application/json",
              "Access-Control-Allow-Origin": "*",
              "X-Cache": "HIT",
              "X-Role": authContext.role,
              "X-Auth-Mode": authContext.authMode,
              "Cache-Control": "public, max-age=3600"
            }
          });
        }
      }

      const responseBody = await fetchAggregatedData();
      if (kv) {
        ctx.waitUntil(kv.put(DATA_CACHE_KEY, responseBody, { expirationTtl: CACHE_TTL }));
      }
      scheduleOneTimeClientBurn(authContext, kv, ctx);

      return new Response(responseBody, {
        headers: {
          "content-type": "application/json",
          "Access-Control-Allow-Origin": "*",
          "X-Cache": "MISS",
          "X-Role": authContext.role,
          "X-Auth-Mode": authContext.authMode,
          "Cache-Control": "public, max-age=3600"
        }
      });
    }

    if (path === "/tks") {
      return new Response(buildTksPage(env), {
        headers: {
          "content-type": "text/html; charset=utf-8",
          "Cache-Control": "no-store"
        }
      });
    }

    if (path.startsWith("/tg")) {
      const newPath = path.slice(3);
      const targetUrl = `https://api.telegram.org${newPath}${url.search}`;
      try {
        const res = await fetch(targetUrl, {
          method: request.method,
          headers: request.headers,
          body: request.body
        });
        return new Response(res.body, {
          status: res.status,
          headers: { "Access-Control-Allow-Origin": "*" }
        });
      } catch (err) {
        return new Response(err.message, { status: 500 });
      }
    }

    if (path.startsWith("/cf")) {
      const newPath = path.slice(3);
      const targetUrl = `https://api.cloudflare.com${newPath}${url.search}`;
      try {
        const res = await fetch(targetUrl, {
          method: request.method,
          headers: request.headers,
          body: request.body
        });
        return new Response(res.body, {
          status: res.status,
          headers: { "Access-Control-Allow-Origin": "*" }
        });
      } catch (err) {
        return new Response(err.message, { status: 500 });
      }
    }

    return new Response("404 Not Found", { status: 404 });
  }
};
