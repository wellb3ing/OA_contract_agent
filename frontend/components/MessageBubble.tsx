// frontend/components/MessageBubble.tsx
'use client';

import type { ChatMessage } from '@/lib/types';
import ToolProgress from './ToolProgress';
import ReportCard from './ReportCard';

interface Props {
  message: ChatMessage;
  /** If this is the last assistant message and we're still streaming */
  isStreaming?: boolean;
}

export default function MessageBubble({ message, isStreaming }: Props) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-blue-500 text-white rounded-br-md'
            : 'bg-white border border-gray-200 text-gray-800 rounded-bl-md shadow-sm'
        }`}
      >
        {/* Avatar + role label */}
        <div
          className={`text-xs mb-1 ${isUser ? 'text-blue-100' : 'text-gray-400'}`}
        >
          {isUser ? '👤 你' : '🤖 合同助手'}
        </div>

        {/* Text content */}
        <div className="whitespace-pre-wrap break-words">
          {message.content}
        </div>

        {/* Streaming cursor */}
        {isStreaming && !message.content && (
          <span className="inline-block w-2 h-4 bg-gray-400 animate-pulse rounded-sm ml-0.5" />
        )}

        {/* Tool progress (assistant only) */}
        {!isUser && message.toolStates && message.toolStates.length > 0 && (
          <ToolProgress tools={message.toolStates} />
        )}

        {/* Report card (assistant only) */}
        {!isUser && message.report && <ReportCard report={message.report} />}
      </div>
    </div>
  );
}
