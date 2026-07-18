// frontend/lib/useChatStream.ts
'use client';

import { useCallback, useRef, useState } from 'react';
import type { ChatMessage, Report, ToolState } from './types';

let _idCounter = 0;
function nextId(): string {
  return `${Date.now()}-${++_idCounter}`;
}

export function useChatStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState('');
  const [toolStates, setToolStates] = useState<ToolState[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const clear = useCallback(() => {
    setMessages([]);
    setStreaming('');
    setToolStates([]);
    setReport(null);
    setIsStreaming(false);
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }, []);

  const send = useCallback(
    async (text: string, file?: File) => {
      // Add user message immediately
      const userMsg: ChatMessage = {
        id: nextId(),
        role: 'user',
        content: text,
      };
      setMessages((prev) => [...prev, userMsg]);
      setStreaming('');
      setToolStates([]);
      setReport(null);
      setIsStreaming(true);

      // Build FormData
      const formData = new FormData();
      const history = [
        ...messages.map((m) => ({ role: m.role, content: m.content })),
        { role: 'user' as const, content: text },
      ];
      formData.append('messages', JSON.stringify(history));
      if (file) {
        formData.append('file', file);
        console.log('[useChatStream] 发送文件:', file.name, file.size, 'bytes');
      } else {
        console.log('[useChatStream] 纯文本消息, 无文件');
      }

      // Abort any in-flight request
      if (abortRef.current) {
        abortRef.current.abort();
      }
      const controller = new AbortController();
      abortRef.current = controller;

      // Local variables track latest values during this stream session
      // (avoiding stale-closure issues with React state in the SSE loop)
      let localToolStates: ToolState[] = [];
      let localReport: Report | null = null;
      let fullText = '';  // outside try so catch/finally can flush partial text

      try {
        // 直连后端（绕过 Next.js 代理，支持大文件上传）
        const apiUrl = 'http://localhost:8000/api/chat';
        console.log('[useChatStream] 发起 fetch POST, hasFile=', !!file);
        const response = await fetch(apiUrl, {
          method: 'POST',
          body: formData,
          signal: controller.signal,
        });
        console.log('[useChatStream] fetch 返回:', response.status, response.statusText);

        if (!response.ok) {
          const errText = await response.text();
          setStreaming(`请求失败 (${response.status}): ${errText}`);
          setIsStreaming(false);
          return;
        }

        // Parse SSE stream
        const reader = response.body?.getReader();
        if (!reader) {
          setStreaming('无法读取响应流');
          setIsStreaming(false);
          return;
        }

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Parse complete SSE events from buffer
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // keep incomplete line in buffer

          let eventType = '';
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              const dataStr = line.slice(6);
              try {
                const data = JSON.parse(dataStr);
                switch (eventType) {
                  case 'delta':
                    fullText += data.content;
                    setStreaming(fullText);
                    break;
                  case 'tool_start':
                    localToolStates = [
                      ...localToolStates,
                      { name: data.tool, label: data.label, status: 'running' as const },
                    ];
                    setToolStates(localToolStates);
                    break;
                  case 'tool_progress':
                    localToolStates = localToolStates.map((t) =>
                      t.name === data.tool
                        ? { ...t, current: data.current, total: data.total }
                        : t
                    );
                    setToolStates(localToolStates);
                    break;
                  case 'tool_end':
                    localToolStates = localToolStates.map((t) =>
                      t.name === data.tool
                        ? {
                            ...t,
                            status: data.status as 'success' | 'error',
                            result: data.result,
                            error: data.error,
                          }
                        : t
                    );
                    setToolStates(localToolStates);
                    break;
                  case 'report':
                    localReport = data as Report;
                    setReport(localReport);
                    break;
                  case 'done':
                    // Finalize: commit streaming text + tool states + report
                    // as a completed assistant message.
                    if (fullText || localToolStates.length > 0 || localReport) {
                      const assistantMsg: ChatMessage = {
                        id: nextId(),
                        role: 'assistant',
                        content: fullText || '处理完成，请查看执行步骤和校验报告。',
                        toolStates: [...localToolStates],
                        report: localReport,
                      };
                      setMessages((prev) => [...prev, assistantMsg]);
                    }
                    setStreaming('');
                    setToolStates([]);
                    setReport(null);
                    setIsStreaming(false);
                    break;
                  case 'error':
                    // Flush any accumulated progress so the user
                    // sees what happened before the error surfaced.
                    if (fullText || localToolStates.length > 0 || localReport) {
                      const partialMsg: ChatMessage = {
                        id: nextId(),
                        role: 'assistant',
                        content: fullText || '工具执行过程中出现错误。',
                        toolStates: [...localToolStates],
                        report: localReport,
                      };
                      setMessages((prev) => [...prev, partialMsg]);
                    }
                    setMessages((prev) => [
                      ...prev,
                      {
                        id: nextId(),
                        role: 'assistant',
                        content: `⚠️ 处理出错：${data.error}`,
                      },
                    ]);
                    setStreaming('');
                    setToolStates([]);
                    setReport(null);
                    setIsStreaming(false);
                    break;
                }
              } catch {
                // Skip malformed JSON
              }
              eventType = '';
            }
          }
        }
      } catch (err: any) {
        if (err.name !== 'AbortError') {
          // Flush partial text on connection drop so user
          // sees whatever progress was made.
          const errorText = `连接错误: ${err.message}`;
          if (fullText) {
            setMessages((prev) => [
              ...prev,
              {
                id: nextId(),
                role: 'assistant',
                content: fullText,
                toolStates: [...localToolStates],
                report: localReport,
              },
              {
                id: nextId(),
                role: 'assistant',
                content: `⚠️ ${errorText}`,
              },
            ]);
            setStreaming('');
            setToolStates([]);
            setReport(null);
          } else {
            setStreaming(errorText);
          }
        }
        setIsStreaming(false);
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
      }
    },
    [messages]
  );

  return {
    messages,
    streaming,
    toolStates,
    report,
    isStreaming,
    send,
    clear,
  };
}
