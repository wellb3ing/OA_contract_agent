// frontend/components/ReportCard.tsx
'use client';

import type { Report } from '@/lib/types';

interface Props {
  report: Report | null;
}

export default function ReportCard({ report }: Props) {
  // Nothing to show
  if (!report) return null;

  // Loading skeleton
  if (!report.results && !report.error) {
    return (
      <div className="my-3 p-4 border border-gray-200 rounded-lg animate-pulse">
        <div className="h-4 bg-gray-200 rounded w-1/3 mb-3" />
        <div className="h-3 bg-gray-100 rounded w-2/3 mb-2" />
        <div className="h-3 bg-gray-100 rounded w-1/2" />
      </div>
    );
  }

  // Determine border color
  const borderColor = report.passed === true
    ? 'border-green-400'
    : report.passed === false
      ? 'border-red-400'
      : 'border-yellow-400';

  const bgColor = report.passed === true
    ? 'bg-green-50'
    : report.passed === false
      ? 'bg-red-50'
      : 'bg-yellow-50';

  return (
    <div className={`my-3 p-4 rounded-lg border-2 ${borderColor} ${bgColor}`}>
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        {report.passed === true ? (
          <span className="text-green-600 font-bold">✅ 金额校验通过</span>
        ) : report.passed === false ? (
          <span className="text-red-600 font-bold">❌ 金额校验未通过</span>
        ) : (
          <span className="text-yellow-600 font-bold">⚠️ 无法判断</span>
        )}
      </div>

      {/* Amounts table */}
      {report.amounts && Object.keys(report.amounts).length > 0 && (
        <div className="mb-3">
          <h4 className="text-xs text-gray-500 uppercase mb-1">金额字段</h4>
          <table className="w-full text-sm">
            <tbody>
              {Object.entries(report.amounts).map(([key, value]) => (
                <tr key={key} className="border-b border-gray-200/50">
                  <td className="py-1 text-gray-600">{key}</td>
                  <td className="py-1 text-right font-mono">
                    {typeof value === 'number'
                      ? `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`
                      : value}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Rule results */}
      {report.results && report.results.length > 0 && (
        <div>
          <h4 className="text-xs text-gray-500 uppercase mb-1">校验规则</h4>
          <ul className="space-y-2">
            {report.results.map((r, i) => (
              <li key={i} className="text-sm">
                <div className="flex items-center gap-1">
                  <span>
                    {r.passed === true ? '✅' : r.passed === false ? '❌' : '⚠️'}
                  </span>
                  <span className="text-gray-700">{r.rule}</span>
                </div>
                {r.detail && (
                  <p className="text-xs text-gray-500 mt-0.5 ml-6">{r.detail}</p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Error fallback */}
      {report.error && (
        <p className="text-sm text-red-500">{report.error}</p>
      )}
    </div>
  );
}
