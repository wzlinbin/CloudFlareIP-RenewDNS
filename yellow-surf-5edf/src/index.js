export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 检查分号，且if后换行以保持清晰
    if (url.pathname === "/health") {
      return new Response("OK", { status: 200 });
    }

    // 演示for循环结构
    const tasks = ["process", "log"];
    for (let i = 0; i < tasks.length; i++) {
      console.log("Current task: " + tasks[i]);
    }

    return new Response("Hello from GitHub Actions!", {
      headers: { "content-type": "text/plain;charset=UTF-8" },
    });
  },
};