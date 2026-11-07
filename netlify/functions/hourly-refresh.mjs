// Netlify Scheduled Function: rebuilds the site every hour so data.json stays fresh.
// Needs the site env var BUILD_HOOK_URL (Netlify → Project configuration →
// Environment variables) set to the "hourly-news-refresh" build hook URL.
export default async () => {
  const hook = process.env.BUILD_HOOK_URL;
  if (!hook) {
    console.error("BUILD_HOOK_URL is not set");
    return new Response("BUILD_HOOK_URL not set", { status: 500 });
  }
  const res = await fetch(`${hook}?trigger_title=scheduled+hourly+refresh`, {
    method: "POST",
    body: "{}",
  });
  console.log(`build hook responded ${res.status}`);
  return new Response(`hook ${res.status}`, { status: res.ok ? 200 : 502 });
};

export const config = { schedule: "@hourly" };
