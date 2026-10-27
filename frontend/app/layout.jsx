import "./globals.css";

export const metadata = {
  title: "寻知 · 搜索问答助手",
  description: "带来源的联网问答，保存每一次探索。",
};

export default function RootLayout({ children }) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
