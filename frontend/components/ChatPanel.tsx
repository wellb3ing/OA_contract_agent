// frontend/components/ChatPanel.tsx
'use client';

import { useRef, useEffect, useState, useCallback, type FormEvent } from 'react';
import { useChatStream } from '@/lib/useChatStream';
import MessageBubble from './MessageBubble';
import FileUpload from './FileUpload';
import ToolProgress from './ToolProgress';
import ReportCard from './ReportCard';

export default function ChatPanel() {
  const { messages, streaming, toolStates, report, isStreaming, send, clear } =
    useChatStream();
  const [input, setInput] = useState('');
  const [file, setFile] = useState<File | undefined>(undefined);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages or streaming changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streaming, toolStates]);

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const text = input.trim();
      if (!text || isStreaming) return;
      send(text, file);
      setInput('');
      setFile(undefined);
    },
    [input, file, isStreaming, send]
  );

  const isEmpty = messages.length === 0 && !isStreaming;

  return (
    <div className="flex flex-col h-screen max-w-3xl mx-auto">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
        <h1 className="text-lg font-bold text-gray-800">🔍 合同审核助手</h1>
        {messages.length > 0 && (
          <button
            onClick={clear}
            className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            清空对话
          </button>
        )}
      </header>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 py-6 bg-gray-50">
        {isEmpty && (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <p className="text-4xl mb-4">📋</p>
            <p className="text-lg font-medium mb-2">合同审核助手</p>
            <p className="text-sm">
              输入合同 ID 或上传合同文件，我将帮您校验金额
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {/* Streaming assistant message (not yet committed to messages) */}
        {isStreaming && (
          <div className="flex justify-start mb-4">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 bg-white border border-gray-200 text-gray-800 rounded-bl-md shadow-sm">
              <div className="text-xs text-gray-400 mb-1">🤖 合同助手</div>
              {streaming ? (
                <div className="whitespace-pre-wrap break-words">
                  {streaming}
                </div>
              ) : (
                <span className="inline-block w-2 h-4 bg-gray-400 animate-pulse rounded-sm" />
              )}
              <ToolProgress tools={toolStates} />
              <ReportCard report={report} />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <form
        onSubmit={handleSubmit}
        className="flex items-end gap-2 px-4 py-3 border-t border-gray-200 bg-white"
      >
        <FileUpload
          onFileSelect={setFile}
          disabled={isStreaming}
        />
        <div className="flex-1 relative">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              file
                ? `已选择 ${file.name}，输入补充说明...`
                : '输入合同 ID 或描述，也可直接粘贴文件...'
            }
            disabled={isStreaming}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
          />
        </div>
        <button
          type="submit"
          disabled={isStreaming || !input.trim()}
          className="px-5 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors font-medium"
        >
          {isStreaming ? (
            <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
          ) : (
            '发送 ▶'
          )}
        </button>
      </form>
    </div>
  );
}
