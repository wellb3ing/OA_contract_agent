import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '合同审核助手',
  description: '智能合同金额校验 Agent',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
