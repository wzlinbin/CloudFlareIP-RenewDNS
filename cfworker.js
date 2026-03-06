/**
 * 聚合代理 - 视觉增强与双端反馈版
 * 特性：
 * 1. 顶部图标 + 底部文字双重 GitHub 引导。
 * 2. 完美保留 /tg 和 /cf 代理转发逻辑。
 * 3. 自动联动 SOURCES 配置与 UI 渲染。
 */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // 🔗 源列表：修改此处，页面和聚合逻辑会自动联动
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
    const CF_PREFIX = "/cf";
    const GITHUB_URL = "https://github.com/wzlinbin/CloudFlareIP-RenewDNS";

    // ================= ✈️ 1. 专项转发功能 (TG / CF) =================
    if (path.startsWith(TG_PREFIX)) {
      const targetUrl = `https://api.telegram.org${path.slice(TG_PREFIX.length)}${url.search}`;
      return await proxyRequest(targetUrl, request);
    }

    if (path.startsWith(CF_PREFIX)) {
      const targetUrl = `https://api.cloudflare.com${path.slice(CF_PREFIX.length)}${url.search}`;
      return await proxyRequest(targetUrl, request);
    }

    // ================= 🧼 2. 数据清洗与分类器 =================
    const cleanAndClassify = (rawText) => {
      const ipRegex = /\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b/g;
      const lines = rawText.split(/[\n\r<]+/).map(l => l.trim());
      const classified = { "电信": [], "联通": [], "移动": [], "其他": [] };
      const allMatches = [];

      lines.forEach(line => {
        const found = line.match(ipRegex);
        if (found) {
          found.forEach(ip => {
            if (ip === "0.0.0.0" || ip === "127.0.0.1") return;
            allMatches.push(ip);
            if (line.includes("电信")) classified["电信"].push(ip);
            else if (line.includes("联通")) classified["联通"].push(ip);
            else if (line.includes("移动")) classified["移动"].push(ip);
            else classified["其他"].push(ip);
          });
        }
      });

      for (let key in classified) {
        classified[key] = [...new Set(classified[key])];
      }

      return {
        groups: classified,
        raw_count: allMatches.length,
        clean_count: [...new Set(allMatches)].length
      };
    };

    // ================= 📦 3. 根路径聚合逻辑 (/) =================
    if (path === "/" || path === "") {
      const results = {};
      const errors = {};
      const startTime = Date.now();

      const fetchPromises = Object.entries(SOURCES).map(async ([key, targetUrl]) => {
        try {
          const res = await fetch(targetUrl, {
            headers: { "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" },
            signal: AbortSignal.timeout(8000)
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          results[key] = cleanAndClassify(await res.text());
        } catch (e) {
          errors[key] = e.message;
        }
      });

      await Promise.all(fetchPromises);

      const allIps = Object.values(results).flatMap(r => Object.values(r.groups).flat());
      const globalUniqueIps = [...new Set(allIps)];

      const responseData = {
        status: "success",
        meta: { 
          timestamp: new Date().toISOString(), 
          duration_ms: Date.now() - startTime,
          global_stats: { unique_total: globalUniqueIps.length } 
        },
        global_list: globalUniqueIps,
        sources: results,
        errors: Object.keys(errors).length > 0 ? errors : undefined
      };

      const acceptHeader = request.headers.get("Accept") || "";
      if (acceptHeader.includes("text/html")) {
        return new Response(renderHTML(responseData, GITHUB_URL), { headers: { "content-type": "text/html; charset=utf-8" } });
      } else {
        return new Response(JSON.stringify(responseData, null, 2), { 
          headers: { "content-type": "application/json; charset=utf-8", "Access-Control-Allow-Origin": "*" } 
        });
      }
    }

    return new Response(JSON.stringify({ error: "Not Found" }), { status: 404 });
  }
};

/**
 * UI 渲染函数
 */
function renderHTML(data, githubUrl) {
  const ispColors = { "电信": "text-blue-400 bg-blue-900/30", "联通": "text-orange-400 bg-orange-900/30", "移动": "text-green-400 bg-green-900/30", "其他": "text-gray-400 bg-gray-900/30" };

  const sourceCards = Object.entries(data.sources).map(([name, info]) => {
    let ispSections = Object.entries(info.groups)
      .filter(([_, ips]) => ips.length > 0)
      .map(([isp, ips]) => `
        <div class="mb-3">
          <div class="text-[10px] font-bold mb-1 ${ispColors[isp] || ''} px-2 py-0.5 rounded w-max">${isp}</div>
          <div class="flex flex-wrap gap-1.5">
            ${ips.map(ip => `<code class="text-[10px] bg-gray-900 px-1 py-0.5 rounded text-gray-300 border border-gray-700">${ip}</code>`).join('')}
          </div>
        </div>
      `).join('');

    return `
      <div class="bg-gray-800/80 backdrop-blur-sm rounded-2xl p-5 border border-gray-700 flex flex-col h-full shadow-lg">
        <div class="flex justify-between items-center mb-4 pb-2 border-b border-gray-700">
          <h3 class="text-white font-black uppercase tracking-tighter text-lg">${name}</h3>
          <span class="text-xs font-mono bg-indigo-600 text-white px-2 py-0.5 rounded shadow-inner">${info.clean_count}</span>
        </div>
        <div class="flex-1 overflow-y-auto pr-1 scrollbar-thin">
          ${ispSections || '<p class="text-gray-500 text-xs italic">No data found</p>'}
        </div>
      </div>
    `;
  }).join('');

  return `
  <!DOCTYPE html>
  <html>
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CF IP Aggregator Hub</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
      body { background: #0f172a; color: #f1f5f9; font-family: ui-sans-serif, system-ui, sans-serif; }
      .scrollbar-thin::-webkit-scrollbar { width: 3px; }
      .scrollbar-thin::-webkit-scrollbar-thumb { background: #475569; border-radius: 6px; }
    </style>
  </head>
  <body class="p-4 md:p-10">
    <div class="max-w-7xl mx-auto">
      <header class="flex flex-col md:flex-row justify-between items-center gap-6 mb-12">
        <div class="flex items-center gap-4">
          <div>
            <h1 class="text-4xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400">CF IP Hub</h1>
            <p class="text-slate-400 text-sm mt-1 font-medium italic opacity-80">Cloudflare 优选 IP 实时聚合清洗</p>
          </div>
          <a href="${githubUrl}" target="_blank" title="提交Bug或建议" class="text-slate-500 hover:text-white transition-colors">
            <svg class="w-7 h-7" fill="currentColor" viewBox="0 0 24 24"><path fill-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.987 1.029-2.683-.103-.253-.446-1.272.098-2.647 0 0 .84-.269 2.75 1.025A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.294 2.747-1.025 2.747-1.025.546 1.375.202 2.394.1 2.647.64.696 1.027 1.59 1.027 2.683 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clip-rule="evenodd"></path></svg>
          </a>
        </div>
        <button onclick="copyAll()" class="bg-indigo-600 hover:bg-indigo-500 px-8 py-3 rounded-xl font-bold transition-all shadow-xl shadow-indigo-900/40 transform active:scale-95">复制全球去重列表</button>
      </header>

      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        ${sourceCards}
      </div>

      <footer class="mt-20 py-8 border-t border-slate-800 flex flex-col md:flex-row justify-between items-center gap-4 text-[10px] text-slate-500 font-bold uppercase tracking-widest">
        <span>Updated: ${new Date(data.meta.timestamp).toLocaleString()}</span>
        <a href="${githubUrl}" target="_blank" class="text-indigo-400 hover:text-indigo-300 transition-colors border-b border-indigo-900/50 pb-0.5">提交反馈与建议</a>
        <div class="flex gap-4">
          <span>Latency: ${data.meta.duration_ms}ms</span>
          <span>Status: 200 OK</span>
        </div>
      </footer>
    </div>
    <script>
      function copyAll() {
        const ips = ${JSON.stringify(data.global_list)};
        navigator.clipboard.writeText(ips.join('\\n')).then(() => alert('成功复制 ' + ips.length + ' 个唯一 IP'));
      }
    </script>
  </body>
  </html>
  `;
}

/**
 * 代理核心逻辑
 */
async function proxyRequest(targetUrl, request) {
  const targetUrlObj = new URL(targetUrl);
  const newReq = new Request(targetUrl, {
    method: request.method,
    headers: new Headers(request.headers),
    body: (request.method === "GET" || request.method === "HEAD") ? null : request.body,
    redirect: "follow"
  });
  
  newReq.headers.set("Host", targetUrlObj.hostname);
  newReq.headers.set("Referer", targetUrlObj.origin + "/");
  
  try {
    const response = await fetch(newReq);
    const newResHeaders = new Headers(response.headers);
    newResHeaders.set("Access-Control-Allow-Origin", "*");
    return new Response(response.body, { status: response.status, headers: newResHeaders });
  } catch (err) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500, headers: { "content-type": "application/json" } });
  }
}