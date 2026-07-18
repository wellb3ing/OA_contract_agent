# 合同校验 Agent

基于 LangChain + DeepSeek 的 OA 合同金额自动化校验系统。支持**OA 审批节点自动触发**和 **Web 对话界面**两种使用方式。

## 架构概览

```
┌── 表单填写阶段 ──────────────────────────┐
│  OA 按钮 → ddcode+fileId → local_receiver │
│          下载文件 → OCR → 校验 → 存结果    │
└──────────────────────────────────────────┘
                    ↓
┌── 审批阶段 ──────────────────────────────┐
│  Java Action → requestId → local_receiver │
│   查最新校验结果 → 通过/不通过             │
│   不通过 → 调 OA REST API 退回流程        │
└──────────────────────────────────────────┘

Web 对话: 用户输入 requestId → LLM Function Calling → 查DB→下载→OCR→校验→报告
```

## 环境依赖

- Python 3.10+
- SQL Server（可通过 ODBC Driver 17 连接）
- poppler（PDF 转图片）
- Node.js 18+（前端）

### 安装

```bash
pip install -r requirements.txt
```

PDF 转图片需要 poppler：

- **Windows**：下载 [poppler-windows](https://github.com/oschwartz10612/poppler-windows/releases/latest)，解压后将 `Library\bin` 加入系统 PATH
- **macOS**：`brew install poppler`
- **Ubuntu/Debian**：`apt install poppler-utils`

SQL Server 连接需要 ODBC Driver：

- **Windows**：下载安装 [ODBC Driver 17 for SQL Server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

## 配置

编辑 `contract_agent/config.yaml`：

### 数据库

```yaml
database:
  type: "mssql"
  driver: "ODBC Driver 17 for SQL Server"
  server: "172.16.0.23"
  port: 1433
  user: "sa"
  password: "123456"
  db: "ecology"
```

`:request_id` 为 SQL 占位符，由 Agent 自动替换。

### 文件下载

支持两种下载方式：

```yaml
download:
  base_url: "http://172.16.0.18:8081/weaver/weaver.file.FileDownload"
  cookie: "JSESSIONID=xxx; ..."    # Cookie 鉴权（查DB后下载用）
```

| 方式 | 鉴权 | 适用场景 |
|------|------|---------|
| Cookie | `config.yaml` 中配置 | Web 对话、requestId 查 DB 下载 |
| DDCode | 表单按钮传入的一次性凭证 | OA 表单按钮推送 |

### OCR

```yaml
ocr:
  provider: "mcp"    # 可选: baidu / aliyun / tencent / mcp
  mcp:
    url: "http://mcpservergateway.market.alicloudapi.com/.../sse"
```

| provider | 说明 |
|----------|------|
| `mcp` | 通过 MCP SSE 协议连接远程 OCR 服务 |
| `baidu` | 百度智能云通用文字识别 |
| `aliyun` | 阿里云印刷体识别 |
| `tencent` | 腾讯云通用印刷体识别 |

### 校验规则

```yaml
validation:
  amount_threshold: 100          # 金额超过此值（元）时，触发签字检查
  required_signature: "孙小福康"  # 授权代表签字必须包含的关键字
  rules: []                      # 额外 LLM 辅助规则（可选）
```

核心校验（金额一致性、签字检查）由代码执行，不会因 LLM 理解偏差而误判。

### OA 退回

```yaml
oa:
  base_url: "http://172.16.0.18:8081"
  login_id: "30837"
  password: "123456"
  app_id: "YUNYI"
  reject_delay_seconds: 5        # 收到 requestId 后等 N 秒再退回
```

### LLM & 可观测性

```yaml
deepseek:
  api_key: "sk-xxx"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"

langsmith:
  api_key: "lsv2_pt_xxx"         # 留空则禁用 tracing
  project: "OA_contract_agent"
```

## 使用方式

### 方式一：OA 审批节点自动触发（推荐）

**1. 启动本地接收服务**

```bash
python contract_agent\local_receiver.py
```

```
本地接收服务启动: http://0.0.0.0:18888
等待 OA 推送...
  模式1: 表单按钮 → fileid+ddcode → 下载→校验→存结果
  模式2: 审批节点 → requestId → 查最新结果 → 不通过则退回
```

**2. OA 端配置**

- **表单阶段**：OA 表单按钮 JS，用户点击后 POST 到 Agent：
  ```json
  {"requestId": 917393, "files": [{"fileid": "5367222", "ddcode": "xxx", "filename": "合同.pdf"}]}
  ```
  Agent 自动下载 → OCR → 校验 → 存储结果。

- **审批阶段**：部署 `docs/PushToAgent.java` 到 OA 审批节点的「节点前附件操作」。流程提交后 Java Action 自动 POST：
  ```json
  {"requestId": 917393}
  ```
  Agent 取最新校验结果，不通过则调 OA REST API 退回流程。

### 方式二：Web 对话界面

**启动后端**

```bash
uvicorn contract_agent.server:app --host 0.0.0.0 --port 8000
```

**启动前端**

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:3000。

**对话示例**

```
帮我查一下 requestId 917393，文件名是 02-行李费
```

Agent 自动执行：查询 OA 附件 → 匹配文件名 → Cookie 下载 → OCR → 提取金额 → 校验 → 报告。也可以直接上传 PDF/图片。

### 方式三：CLI

```bash
# 通过 requestId 查询 OA 附件
python -m contract_agent.main --params '{"request_id": 917393}'

# 按文件名过滤
python -m contract_agent.main --params '{"request_id": 917393, "filename": "行李费"}'

# 直接指定本地文件
python -m contract_agent.main --params '{"file_path": "C:/Users/yy_b705/Desktop/合同.pdf"}'

# 本地文件 + OA 金额比对
python -m contract_agent.main --params '{"file_path": "合同.pdf", "oa_amount": "100000"}'
```

## 项目结构

```
OA_agent_demo/
├── contract_agent/                   # Python 后端
│   ├── config.yaml                   # 配置（DB/下载/OCR/校验/OA退回/LLM/LangSmith）
│   ├── config.py                     # 配置加载
│   ├── main.py                       # CLI 入口
│   ├── agent.py                      # 流水线编排 + 代码级核心校验
│   ├── server.py                     # FastAPI SSE 端点
│   ├── function_calling.py           # DeepSeek Function Calling 编排
│   ├── local_receiver.py             # OA 推送接收器（ddcode + requestId 双模式）
│   ├── tracing.py                    # LangSmith 可观测性初始化
│   ├── validation_results.json       # 校验结果缓存（用于审批阶段复用）
│   └── tools/
│       ├── db_query.py               # OA 附件查询（pyodbc → SQL Server）
│       ├── downloader.py             # 文件下载（Cookie + DDCode 双模式）
│       ├── prepare_images.py         # PDF/图片 → OCR 图片（含文件大小自适应）
│       ├── ocr_runner.py             # OCR 识别调度
│       ├── ocr/                      # OCR 引擎（base/baidu/aliyun/tencent/mcp）
│       ├── extractor.py              # LLM 提取金额字段
│       ├── validator.py              # LLM 辅助校验（可选）
│       └── oa_reject.py              # OA 流程退回（登录→rejectRequest）
├── frontend/                         # Next.js 前端
├── docs/
│   ├── PushToAgent.java              # OA 审批节点 Java Action
│   └── ...
├── tests/                            # 测试用例
└── requirements.txt
```

## 运行测试

```bash
pytest tests/ -v
```

## 注意事项

- **Cookie 有效期**：OA Cookie 过期后需重新填写
- **DDCode**：一次性下载凭证，由 OA 表单按钮生成，无需 Cookie
- **OA 退回**：审批阶段收到 requestId 后等待 `reject_delay_seconds` 秒再退回，确保 OA 流程状态已落库
- **校验结果复用**：表单阶段校验结果存入 `validation_results.json`，审批阶段直接读取，避免重复 OCR
- **poppler**：PDF 转图片必需，Windows 需手动安装
- **不做登录认证**：内部工具，无用户系统
- **不做对话持久化**：刷新页面即清空对话历史
