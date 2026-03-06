/**
 * 聚合代理 - 最终安全版
 * 特性：
 * 1. 密钥从环境变量读取 (env.SECRET_KEY)
 * 2. KV 缓存支持 (env.MY_KV)
 * 3. 鉴权开关 (ENABLE_AUTH)
 * 4. 支持 Telegram 与 Cloudflare API 代理转发
 */
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // ================= 🎛️ 控制面板 =================
    
    // 鉴权开关：true = 开启; false = 关闭 (调试用)
    // 即使开启，如果环境变量没配置 SECRET_KEY，脚本也会报错以保护安全
    const ENABLE_AUTH = true; 

    // 缓存时间 (秒)
    const CACHE_TTL = 600; 
    const CACHE_KEY = "all_sources_data_v1";

    // 🔗 源列表
    const SOURCES = {
      "wetest": "https://www.wetest.vip/page/cloudflare/address_v4.html",
      "uouin":  "https://api.uouin.com/cloudflare.html",
      "v2too":  "https://ip.v2too.top",
      "xyz":    "https://ip.164746.xyz",
      "vps789": "https://vps789.com/public/sum/cfIpApi",
      "vvhan":  "https://api.4ce.cn/api/bestCFIP",
      "mrxn":   "https://raw.githubusercontent.com/xingpingcn/enhanced-FaaS-in-China/refs/heads/main/Vercel.json"
    };

    const TG_PREFIX = "/tg";
    const CF_PREFIX = "/cf";  // <--- 新增：Cloudflare 转发前缀

    // ================= 🔐 1. 安全检查与鉴权 =================
    
    // 从环境变量获取密钥
    const SECRET_KEY = env.SECRET_KEY;

    // 安全自检：如果开启了鉴权但没配置环境变量，直接阻断，防止默认放行
    if (ENABLE_AUTH && !SECRET_KEY) {
      return new Response(JSON.stringify({
        error: "Server Configuration Error",
        message: "SECRET_KEY variable is not set in Cloudflare Settings."
      }), { status: 500, headers: { "content-type": "application/json" } });
    }

    // 鉴权逻辑
    if (ENABLE_AUTH) {
      const clientKey = request.headers.get("x-auth-key");
      if (clientKey !== SECRET_KEY) {
        return new Response(JSON.stringify({ 
          error: "Access Denied",
          message: "Authentication failed. Please check your x-auth-key."
        }), {
          status: 403,
          headers: { 
            "content-type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*"
          }
        });
      }
    }

    // ================= 📦 2. 聚合逻辑 (/all) + KV =================
    if (path === "/all") {
      let cachedData = null;
      let kvStatus = "Disabled/Not Bound";

      try {
        if (env.MY_KV) {
          cachedData = await env.MY_KV.get(CACHE_KEY);
          kvStatus = "Active";
        }
      } catch (e) {
        kvStatus = `Error: ${e.message}`;
      }

      if (cachedData) {
        return new Response(cachedData, {
          headers: { 
            "content-type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "X-Cache": "HIT",
            "X-KV-Status": kvStatus
          }
        });
      }

      // 实时抓取
      const results = {};
      const fetchPromises = Object.entries(SOURCES).map(async ([key, targetUrl]) => {
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 5000);

          const response = await fetch(targetUrl, {
            headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" },
            signal: controller.signal
          });
          
          clearTimeout(timeoutId);
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          results[key] = (await response.text()).trim();
        } catch (e) {
          results[key] = `Error: ${e.message}`;
        }
      });

      await Promise.all(fetchPromises);

      const responseBody = JSON.stringify({
        timestamp: new Date().toISOString(),
        auth_enabled: ENABLE_AUTH,
        kv_status: kvStatus,
        total_sources: Object.keys(SOURCES).length,
        data: results
      }, null, 2);

      try {
        if (env.MY_KV) {
          ctx.waitUntil(env.MY_KV.put(CACHE_KEY, responseBody, { expirationTtl: CACHE_TTL }));
        }
      } catch (e) { console.error("KV Write Error", e); }

      return new Response(responseBody, {
        headers: { 
          "content-type": "application/json; charset=utf-8",
          "Access-Control-Allow-Origin": "*",
          "X-Cache": "MISS"
        }
      });
    }

    // ================= ✈️ 3. TG 转发 =================
    if (path.startsWith(TG_PREFIX)) {
      const tgHost = "api.telegram.org";
      const newPath = path.slice(TG_PREFIX.length);
      const targetUrl = `https://${tgHost}${newPath}${url.search}`;
      return await proxyRequest(targetUrl, request);
    }

    // ================= ☁️ 4. Cloudflare API 转发 =================
    if (path.startsWith(CF_PREFIX)) {
      const cfHost = "api.cloudflare.com";
      const newPath = path.slice(CF_PREFIX.length);
      const targetUrl = `https://${cfHost}${newPath}${url.search}`;
      
      // 注意：发送给 Cloudflare API 的请求通常对域名(Host)要求严格，proxyRequest 会自动处理
      return await proxyRequest(targetUrl, request);
    }

    // ================= 🔗 5. 单源转发 =================
    const purePath = path.slice(1);
    if (SOURCES[purePath]) {
      return await proxyRequest(SOURCES[purePath], request);
    }

    // ================= 🏠 6. 首页 =================
    return new Response(`
      Worker Status: Online
      ---------------------
      Auth Mode: ${ENABLE_AUTH ? "🔒 ON" : "🔓 OFF"}
      Secret Key: ${SECRET_KEY ? "✅ Configured" : "❌ Missing"}
      KV Cache:  ${env.MY_KV ? "✅ Bound" : "⚠️ Not Bound"}
      Proxy Endpoints:
        - /tg/* -> api.telegram.org
        - /cf/* -> api.cloudflare.com
    `, { status: 200 });
  }
};

async function proxyRequest(targetUrl, request) {
  const targetUrlObj = new URL(targetUrl);
  const newReq = new Request(targetUrl, {
    method: request.method,
    headers: new Headers(request.headers),
    body: request.body,
    redirect: "follow"
  });
  
  // 必须重写 Host，否则目标服务器会识别为你自己的域名而报错
  newReq.headers.set("Host", targetUrlObj.hostname);
  newReq.headers.set("Referer", `${targetUrlObj.protocol}//${targetUrlObj.hostname}/`);
  
  try {
    const response = await fetch(newReq);
    const newResHeaders = new Headers(response.headers);
    // 允许跨域
    newResHeaders.set("Access-Control-Allow-Origin", "*");
    return new Response(response.body, { status: response.status, headers: newResHeaders });
  } catch (err) {
    return new Response(`Proxy Error: ${err.message}`, { status: 500 });
  }
}
