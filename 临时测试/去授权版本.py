/**
 * 聚合代理 SaaS 终极版（已修复变量命名语法错误）
 * 修复点：将 env.KV-name 统一修改为 env.KV
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // ================= 配置区域 =================
    const ADMIN_KEY = env.SECRET_KEY;
    // 临时关闭鉴权：受保护路由全部放行
    const DISABLE_AUTH = true;
    const DATA_CACHE_KEY = "system_aggregated_data_v3";
    const CACHE_TTL = 3600;
    const STATS_SAMPLE_RATE = 0.05;

    // 注意：请确保 Cloudflare 控制台绑定的 KV 变量名就是 KV
    const MY_KV = env.KV;

    const SOURCES = {
      "wetest": "https://www.wetest.vip/page/cloudflare/address_v4.html",
      "uouin": "https://api.uouin.com/cloudflare.html",
      "v2too": "https://ip.v2too.top",
      "xyz": "https://ip.164746.xyz",
      "vps789": "https://vps789.com/public/sum/cfIpApi",
      "vvhan": "https://api.4ce.cn/api/bestCFIP",
      "mrxn": "https://raw.githubusercontent.com/xingpingcn/enhanced-FaaS-in-China/refs/heads/main/Vercel.json"
    };

    const clientKey = request.headers.get("x-auth-key") || url.searchParams.get("key");
    const isProtectedRoute = path === "/" || path === "/api/data" || path.startsWith("/tg") || path.startsWith("/cf");

    // 全局认证入口：DISABLE_AUTH 控制所有受保护路由
    let isAuthorized = DISABLE_AUTH;
    let userRole = DISABLE_AUTH ? "bypass" : "guest";
    let currentUserData = null;

    if (!DISABLE_AUTH) {
      if (ADMIN_KEY && clientKey === ADMIN_KEY) {
        isAuthorized = true;
        userRole = "admin";
      } else if (clientKey && MY_KV) {
        const userJson = await MY_KV.get(clientKey);
        if (userJson) {
          isAuthorized = true;
          userRole = "user";
          try {
            currentUserData = JSON.parse(userJson);
          } catch (e) {}
        }
      }
    }

    if (isProtectedRoute && !isAuthorized) {
      return new Response(JSON.stringify({ error: "Access Denied" }), {
        status: 403,
        headers: { "content-type": "application/json" }
      });
    }

    // 首页：仅返回状态信息
    if (path === "/") {
      const status = {
        kv_bound: !!MY_KV,
        cache_ttl: CACHE_TTL,
        sources: Object.keys(SOURCES)
      };
      return new Response(JSON.stringify(status, null, 2), {
        headers: { "content-type": "application/json" }
      });
    }

    // 数据接口：/api/data
    if (path === "/api/data") {
      const hwid = request.headers.get("x-hwid") || url.searchParams.get("hwid");
      const ip = request.headers.get("CF-Connecting-IP") || request.headers.get("x-forwarded-for");

      // 普通用户：IP + HWID 双重限频（每分钟一次）
      if (userRole === "user") {
        if (!ip || !hwid) {
          return new Response(JSON.stringify({ error: "Missing ip or hwid" }), {
            status: 400,
            headers: { "content-type": "application/json" }
          });
        }

        const rateKey = `rate_${ip}_${hwid}`;
        const last = await MY_KV.get(rateKey);
        const now = Date.now();

        if (last) {
          const diff = now - parseInt(last, 10);
          if (diff < 60000) {
            return new Response(JSON.stringify({ error: "Too Many Requests" }), {
              status: 429,
              headers: { "content-type": "application/json" }
            });
          }
        }

        ctx.waitUntil(MY_KV.put(rateKey, now.toString(), { expirationTtl: 120 }));
      }

      // 抽样统计
      if (userRole === "user" && currentUserData && MY_KV && Math.random() < STATS_SAMPLE_RATE) {
        currentUserData.usage = (currentUserData.usage || 0) + (1 / STATS_SAMPLE_RATE);
        currentUserData.last_active = new Date().toISOString();
        ctx.waitUntil(MY_KV.put(clientKey, JSON.stringify(currentUserData)));
      }

      // 一次性 token
      if (userRole === "user" && clientKey) {
        ctx.waitUntil(MY_KV.delete(clientKey));
      }

      // 读取缓存
      if (MY_KV) {
        const cachedData = await MY_KV.get(DATA_CACHE_KEY);
        if (cachedData) {
          return new Response(cachedData, {
            headers: {
              "content-type": "application/json",
              "Access-Control-Allow-Origin": "*",
              "X-Cache": "HIT",
              "X-Role": userRole,
              "Cache-Control": "public, max-age=3600"
            }
          });
        }
      }

      const sortIPv4 = (ips) =>
        ips.sort((a, b) => {
          const aa = a.split(".").map((n) => parseInt(n, 10));
          const bb = b.split(".").map((n) => parseInt(n, 10));
          for (let i = 0; i < 4; i += 1) {
            if (aa[i] !== bb[i]) return aa[i] - bb[i];
          }
          return 0;
        });

      const parseStructuredIPs = (rawText) => {
        const ipRegex = /\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?\d\d?)\b/g;
        const lines = rawText
          .split(/[\n\r<]+/)
          .map((l) => l.trim())
          .filter(Boolean);

        const ipSet = new Set();

        for (const line of lines) {
          const matches = line.match(ipRegex);
          if (!matches) continue;

          for (const ipAddr of new Set(matches)) {
            if (ipAddr === "0.0.0.0" || ipAddr === "127.0.0.1") continue;
            ipSet.add(ipAddr);
          }
        }

        const ips = sortIPv4([...ipSet]);
        return {
          ip_count: ips.length,
          ips
        };
      };

      // 聚合为结构化数据（可读、清晰）
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
            const structured = parseStructuredIPs(text);
            results[key] = {
              status: "ok",
              source: srcUrl,
              fetch_ms: Date.now() - startedAt,
              ...structured
            };
          } catch (e) {
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

      const responseBody = JSON.stringify(
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
      if (MY_KV) ctx.waitUntil(MY_KV.put(DATA_CACHE_KEY, responseBody, { expirationTtl: CACHE_TTL }));

      return new Response(responseBody, {
        headers: {
          "content-type": "application/json",
          "Access-Control-Allow-Origin": "*",
          "X-Cache": "MISS",
          "X-Role": userRole,
          "Cache-Control": "public, max-age=3600"
        }
      });
    }

    // Telegram Proxy
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
      } catch (e) {
        return new Response(e.message, { status: 500 });
      }
    }

    // Cloudflare Proxy
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
      } catch (e) {
        return new Response(e.message, { status: 500 });
      }
    }

    return new Response("404 Not Found", { status: 404 });
  }
};
