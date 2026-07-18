# 合同校验 Agent 对话前端设计文档

日期：2026-07-05

## 背景

当前 `contract_agent` 只支持 CLI 调用 (`python -m contract_agent.main --params '{"contract_id": "C001"}'`)，需要构建一个自然语言对话式前端界面，让用户通过聊天的形式来使用合同校验 Agent。

## 技术选型

| 层 | 选型 | 说明 |
|---|---|---|
| 前端 | Next.js (React) + Tailwind CSS | Vercel AI SDK 可辅助 SSE 流消费，部署方便 |
| 后端 | FastAPI（在现有 `contract_agent` 包内新增 `server.py`） | 复用现有 Tool 层，最小化新增代码 |
| 对话模式 | **自然语言自由对话** | DeepSeek Function Calling 驱动，LLM 自主决定调用工具的顺序和参数 |
| 响应方式 | **SSE 流式输出** | 工具执行进度实时推送，LLM 回答逐字流式 |
| 通信协议 | POST /api/chat → SSE Event Stream | 前端发送对话历史 + 可选文件，后端返回 SSE 事件流 |

## 架构概览

```
┌──────────────────────────────┐        SSE Stream          ┌───────────────────────────────┐
│   Next.js Frontend           │ ◄═══════════════════════►  │   FastAPI Backend             │
│                              │   POST /api/chat           │   (contract_agent/server.py)  │
│  ┌────────────────────────┐  │                            │                               │
│  │ ChatPanel              │  │   { messages[] }           │  ┌─────────────────────────┐  │
│  │  ├─ MessageBubble      │  │   + file (optional)        │  │ POST /api/chat          │  │
│  │  ├─ FileUpload         │  │                            │  │  ├─ function_calling.py │  │
│  │  ├─ ToolProgress       │  │                            │  │  │  DeepSeek FC 循环     │  │
│  │  └─ ReportCard          │  │                            │  │  ├─ 复用现有 6 个 Tool    │  │
│  └────────────────────────┘  │                            │  │  └─ SSE async generator │  │
│                              │                            │  └─────────────────────────┘  │
│  ┌────────────────────────┐  │                            │                               │
│  │ useChatStream hook     │  │                            │  contract_agent/tools/        │
│  │ (fetch ReadableStream) │  │                            │  (现有，不动)                  │
│  └────────────────────────┘  │                            └───────────────────────────────┘
└──────────────────────────────┘
```

**核心原则：** 后端新增代码量最小化，完全复用 `contract_agent/tools/` 下已有的 6 个 Tool。现有的 CLI 入口 `main.py` 保留不变。

## 后端设计

### 新增文件

```
contract_agent/
├── server.py             ← 新增：FastAPI app + POST /api/chat SSE 端点
├── function_calling.py   ← 新增：DeepSeek function calling 编排循环
├── agent.py              ← 现有，可 import 复用 TOOLS 列表
├── tools/                ← 现有，不动
├── config.py             ← 现有
├── config.yaml           ← 现有
└── requirements.txt      ← 补充 fastapi, uvicorn, python-multipart
```

### function_calling.py — 编排循环

把现有 6 个 LangChain Tool 转为 DeepSeek function calling schema 注册给 LLM。编排流程：

```python
async def run_function_calling_loop(messages: list, file_path: str | None) -> AsyncGenerator:
    """
    1. 如果用户上传了文件，在 system prompt 中说明 file_path
    2. while True:
       a. DeepSeek chat completion（带 functions 定义）
       b. 如果 LLM 返回 function_call → 
          yield SSE(tool_start)
          result = tool.func(args)  # 复用现有 Tool
          yield SSE(tool_end)
          messages.append(function_result)
       c. 如果 LLM 返回普通 text →
          逐 token stream yield SSE(delta)
          break
    3. yield SSE(report) 如果涉及校验
    4. yield SSE(done)
    """
```

Tool → DeepSeek function schema 映射：
- `query_contract_url_tool` → `{"name": "query_contract_url", "parameters": {"contract_id": "string"}}`
- `download_contract_tool` → `{"name": "download_contract", "parameters": {"url": "string"}}`
- `prepare_images_tool` → `{"name": "prepare_images", "parameters": {"file_path": "string"}}`
- `ocr_images_tool` → `{"name": "ocr_images", "parameters": {"image_paths": "string[]"}}`
- `extract_amounts_tool` → `{"name": "extract_amounts", "parameters": {"ocr_text": "string"}}`
- `validate_amounts_tool` → `{"name": "validate_amounts", "parameters": {"amounts_json": "string"}}`

### server.py — SSE 端点

```python
@router.post("/api/chat")
async def chat(messages: list[ChatMessage], file: UploadFile | None = None):
    """
    接收对话历史和可选的文件上传。
    如果有 file，写入临时目录并在 system prompt 中注入路径。
    返回 SSE text/event-stream 响应。
    """
    return StreamingResponse(
        run_function_calling_loop(messages, file_path),
        media_type="text/event-stream",
    )
```

### System Prompt

```
你是一个合同审核助手。你可以：
- 根据用户提供的合同ID/合同名称等条件查询数据库获取合同文件URL
- 下载合同文件
- 对合同进行OCR识别
- 提取合同中的金额字段
- 按规则校验金额

如果用户上传了文件，直接跳过数据库查询，对文件进行OCR识别和校验。
如果用户只提供了合同ID或名称等描述信息，先用 query_contract_url 查询数据库获取文件URL，再下载处理。
完成后请根据校验结果生成一份可读的合同金额校验报告。
```

## SSE 事件协议

| 事件类型 | 触发时机 | data 内容 | 前端渲染 |
|----------|----------|-----------|----------|
| `delta` | LLM 逐字输出 | `{"content": "text"}` | 打字机追加文本 |
| `tool_start` | 工具开始执行 | `{"tool": "name", "label": "中文描述"}` | 显示进度卡片 ⏳ |
| `tool_progress` | 长任务进度（可选） | `{"tool": "name", "current": 2, "total": 5}` | 更新进度条 |
| `tool_end` | 工具执行完成 | `{"tool": "name", "status": "success", "result": "..."}` | ✓/✗ |
| `report` | 校验完成时 | `{"passed": bool, "amounts": {...}, "results": [...]}` | ReportCard |
| `done` | 流结束 | `{}` | 停止旋转动画 |
| `error` | 异常 | `{"error": "..."}` | 显示错误提示 |

## 前端设计

### 目录结构

```
frontend/
├── package.json
├── next.config.js
├── tailwind.config.ts
├── app/
│   ├── layout.tsx          ← 根布局，网站标题
│   ├── page.tsx            ← 唯一页面，组合 ChatPanel
│   └── globals.css         ← Tailwind 基础样式
├── components/
│   ├── ChatPanel.tsx       ← 消息列表 + 输入区域
│   ├── MessageBubble.tsx   ← 单条消息气泡（用户右侧/AI 左侧）
│   ├── ToolProgress.tsx    ← 工具执行进度卡片
│   ├── ReportCard.tsx      ← 校验报告卡片
│   └── FileUpload.tsx      ← 文件上传（📎 按钮 + 拖拽）
└── lib/
    └── useChatStream.ts    ← SSE 流消费 hook
```

### 核心 Hook: useChatStream

```
状态：
  messages: Message[]       — 对话历史
  streaming: string         — 当前正在流式接收的 AI 文本
  toolStates: Map           — { [toolName]: { status, label, result } }
  report: Report | null     — 最终校验报告
  isStreaming: boolean      — 是否正在接收

方法：
  send(text: string, file?: File)  — 发起对话请求
  clear()                          — 清空对话

内部流程：
  1. fetch POST /api/chat, body: FormData(messages JSON + optional file)
  2. 设置 responseType: stream, 用 ReadableStream.getReader() 逐块读取
  3. 按行解析 SSE: "event: xxx\ndata: {...}\n\n"
  4. 分发到各事件处理器更新对应状态
```

### 页面布局

```
┌─────────────────────────────────────────────────┐
│  🔍 合同审核助手                       [清空对话] │
│─────────────────────────────────────────────────│
│                                                 │
│  [消息列表 — 滚动区域]                            │
│                                                 │
│  ┌──────────────────────────────┐               │
│  │ 👤 User                       │               │
│  │ 帮我查一下合同 C001 的金额是否合规 │               │
│  └──────────────────────────────┘               │
│                                                 │
│  ┌─ ToolProgress ──────────────────────────┐    │
│  │ ✅ query_contract_url  ·  查询数据库      │    │
│  │ ✅ download_contract   ·  下载合同文件    │    │
│  │ ✅ prepare_images      ·  转换图片        │    │
│  │ ✅ ocr_images          ·  OCR识别 (3页)   │    │
│  │ ✅ extract_amounts     ·  提取金额        │    │
│  │ ⏳ validate_amounts    ·  校验金额...      │    │
│  └──────────────────────────────────────────┘    │
│                                                 │
│  ┌──────────────────────────────┐               │
│  │ 🤖 AI                         │               │
│  │ 合同 C001 校验完成，报告如下：   │               │
│  │                              │               │
│  │ ┌─ ReportCard ────────────┐  │               │
│  │ │ ✅ 金额校验通过           │  │               │
│  │ │                         │  │               │
│  │ │ 合同总价  ¥100,000.00    │  │               │
│  │ │ 不含税金额 ¥88,495.58    │  │               │
│  │ │ 税率 13%  税额 ¥11,504.42│  │               │
│  │ │                         │  │               │
│  │ │ 校验规则：                │  │               │
│  │ │ ✅ 花费金额 < 200 → 通过  │  │               │
│  │ └─────────────────────────┘  │               │
│  └──────────────────────────────┘               │
│                                                 │
│─────────────────────────────────────────────────│
│  📎  [输入你想查询的合同...]               ▶ 发送 │
└─────────────────────────────────────────────────┘
```

### 组件职责

| 组件 | 职责 |
|------|------|
| `ChatPanel` | 组合消息列表 + 输入区域；自动滚到底部；管理 `useChatStream` 状态 |
| `MessageBubble` | 单条消息：用户（右对齐，蓝色） / AI（左对齐，含 ToolProgress+ReportCard） |
| `ToolProgress` | 实时步骤追踪：⏳ running → ✓ success / ✗ error；多页 OCR 显示进度条 |
| `ReportCard` | 结构化渲染报告：passed 绿色边框 / failed 红色边框；金额表格；规则详情列表 |
| `FileUpload` | 📎 按钮触发文件选择，支持拖拽上传；预览缩略图 + 文件名 + 删除按钮 |

## 组件状态覆盖

每个组件覆盖以下状态：

| 组件 | 需要覆盖的状态 |
|------|--------------|
| `MessageBubble` | 用户消息 / AI 消息 / AI 消息流式中 / AI 消息完成 |
| `ToolProgress` | 运行中（spinner 动画）/ 成功（绿 ✓）/ 失败（红 ✗ + 错误信息）/ 进度条（多页 OCR） |
| `ReportCard` | 校验通过（绿边框）/ 校验失败（红边框）/ 无法判断（黄边框，缺少字段）/ 加载中（骨架屏） |
| `FileUpload` | 空状态（📎 按钮）/ 文件已选（缩略图 + 文件名）/ 上传中 / 错误（格式不支持或过大） |
| `ChatPanel` | 有消息 / 无消息（空状态引导语）/ 发送中（输入框禁用，按钮变旋转）/ 错误提示 |

## 部署方式

- **后端**：`uvicorn contract_agent.server:app --host 0.0.0.0 --port 8000`
- **前端**：`npm run dev`（开发）/ `npm run build && npm start`（生产）
- **Nginx 反向代理**（可选）：统一域名，前端 `/` → Next.js 3000，`/api/` → FastAPI 8000

## 已确认（不做）

- **不做登录认证**：内部工具，无需用户系统
- **不做历史持久化**：对话仅存前端内存，刷新即清空
