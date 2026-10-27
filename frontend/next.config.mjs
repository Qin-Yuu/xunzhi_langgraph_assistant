/** Keep browser requests and the anonymous visitor cookie on the same origin. */
const config = {
  // A ReAct turn can include multiple model/search calls; outlast the API's 100s limit.
  experimental: { proxyTimeout: 120000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.BACKEND_URL || "http://127.0.0.1:8000"}/api/:path*` }];
  },
};
export default config;
