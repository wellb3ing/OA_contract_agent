// frontend/components/ToolProgress.tsx
'use client';

import type { ToolState } from '@/lib/types';

interface Props {
  tools: ToolState[];
}

const STATUS_ICON: Record<string, string> = {
  running: '⏳',
  success: '✅',
  error: '❌',
};

export default function ToolProgress({ tools }: Props) {
  if (tools.length === 0) return null;

  const runningCount = tools.filter((t) => t.status === 'running').length;
  const errorCount = tools.filter((t) => t.status === 'error').length;
  const successCount = tools.filter((t) => t.status === 'success').length;

  return (
    <div className="my-3 p-3 bg-gray-50 rounded-lg border border-gray-200 text-sm">
      {/* Summary line */}
      <div className="flex items-center gap-2 mb-2 text-gray-500">
        {runningCount > 0 && (
          <span className="inline-block w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
        )}
        <span>
          {runningCount > 0
            ? `正在执行 (${successCount + errorCount}/${tools.length})...`
            : errorCount > 0
              ? `执行完成 (${errorCount} 个失败)`
              : '全部完成'}
        </span>
      </div>

      {/* Step list */}
      <div className="space-y-1">
        {tools.map((t) => (
          <div key={t.name} className="flex items-center gap-2">
            <span className="w-5 text-center">{STATUS_ICON[t.status]}</span>
            <span
              className={
                t.status === 'running'
                  ? 'text-blue-700 font-medium'
                  : t.status === 'error'
                    ? 'text-red-600'
                    : 'text-gray-600'
              }
            >
              {t.label}
              {t.current && t.total
                ? ` (${t.current}/${t.total} 页)`
                : ''}
            </span>
            {t.status === 'error' && t.error && (
              <span className="text-red-400 text-xs">{t.error}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
