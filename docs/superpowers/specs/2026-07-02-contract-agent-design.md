# 合同校验 Agent 设计文档

日期：2026-07-02

## 背景

需要搭建一个自动化 Agent，能够：
1. 从数据库查询合同文件的内网 HTTP URL
2. 下载合同文件（PDF 或图片）
3. 通过商业 OCR API 识别合同内容（中英文混合扫描件）
4. 提取金额字段并按配置规则校验
5. 输出可读的校验报告

## 技术选型

| 组件 | 选型 | 说明 |
|---|---|---|
| Agent 框架 | LangChain | 工具编排，ReAct 模式 |
| LLM | DeepSeek | 不支持图片，纯文本推理 |
| OCR | 商业 API（可插拔） | 百度 / 阿里云 / 腾讯云，通过配置切换 |
| 数据库 | SQL（待定） | SQL 语句由调用方提供 |

## 整体流程

```
查询条件（合同ID等）
    ↓ Tool: query_contract_url
内网 HTTP URL
    ↓ Tool: download_contract
合同文件（PDF 或 JPG/PNG 等图片）
    ↓ Tool: prepare_images
         ├── PDF → 逐页转图片
         └── 图片 → 直接使用
图片列表
    ↓ Tool: ocr_images（商业 OCR，可插拔）
各页 OCR 原始文字
    ↓ Tool: extract_amounts
结构化金额数据（JSON）
    ↓ Tool: validate_amounts
校验结果
    ↓ Agent 综合整理
可读报告（文字输出）
```

## 项目结构

```
contract_agent/
├── config.yaml              # 配置：OCR 提供商、数据库连接、校验规则
├── main.py                  # 入口：接收查询条件，运行 Agent，打印报告
├── agent.py                 # LangChain Agent 定义（工具注册、prompt、DeepSeek 接入）
├── tools/
│   ├── db_query.py          # Tool: query_contract_url，执行 SQL 查询返回 URL
│   ├── downloader.py        # Tool: download_contract，HTTP 下载合同文件
│   ├── prepare_images.py    # Tool: prepare_images，统一 PDF/图片 → 图片列表
│   ├── ocr/
│   │   ├── base.py          # OCR 抽象接口 OCRProvider
│   │   ├── baidu.py         # 百度智能云实现
│   │   ├── aliyun.py        # 阿里云实现
│   │   └── tencent.py       # 腾讯云实现
│   ├── extractor.py         # Tool: extract_amounts，LLM 从 OCR 文字提取金额字段
│   └── validator.py         # Tool: validate_amounts，按规则校验金额
└── requirements.txt
```

## 各工具职责

### query_contract_url
- 输入：查询条件（如合同 ID）
- 操作：连接数据库，执行配置的 SQL 语句
- 输出：合同文件的内网 HTTP URL
- 注：SQL 语句由调用方提供，存放在 `config.yaml`

### download_contract
- 输入：HTTP URL
- 操作：HTTP GET 下载文件到本地临时目录
- 输出：本地文件路径
- 注：根据响应 Content-Type 或 URL 后缀判断文件类型

### prepare_images
- 输入：本地文件路径
- 操作：
  - PDF → 使用 `pdf2image` 逐页转 PNG
  - 图片（JPG/PNG/BMP/TIFF）→ 直接返回
- 输出：图片路径列表（按页顺序）

### ocr_images
- 输入：图片路径列表
- 操作：调用 OCR Provider，逐图识别
- 输出：各页 OCR 原始文字（按页合并）
- 注：OCR Provider 通过 `config.yaml` 中 `ocr.provider` 字段切换

### extract_amounts
- 输入：OCR 原始文字
- 操作：调用 DeepSeek，从文字中提取所有金额字段，输出结构化 JSON
- 输出：金额字段 JSON，示例：
  ```json
  {
    "合同总价": 100000.00,
    "不含税金额": 88495.58,
    "税率": "13%",
    "税额": 11504.42,
    "含税金额": 100000.00
  }
  ```

### validate_amounts
- 输入：金额字段 JSON
- 操作：调用 DeepSeek，按 `config.yaml` 中配置的规则逐条校验
- 输出：校验结果 JSON，示例：
  ```json
  {
    "passed": true,
    "results": [
      {"rule": "含税金额 = 不含税金额 × (1 + 税率)", "passed": true, "detail": "88495.58 × 1.13 = 100000.01，误差 0.01 元，在允许范围内"},
      {"rule": "各分项之和 = 合同总价", "passed": true, "detail": "未找到分项明细，跳过"}
    ]
  }
  ```

## 配置文件结构

```yaml
# config.yaml

database:
  host: "192.168.1.100"
  port: 3306
  user: "readonly_user"
  password: "your_password"
  db: "contracts"
  sql: "SELECT file_url FROM contracts WHERE contract_id = :contract_id"
  # SQL 占位符统一用 :param_name 格式

ocr:
  provider: "baidu"          # 可选: baidu / aliyun / tencent
  baidu:
    api_key: ""
    secret_key: ""
  aliyun:
    access_key_id: ""
    access_key_secret: ""
    region: "cn-shanghai"
  tencent:
    secret_id: ""
    secret_key: ""
    region: "ap-guangzhou"

validation:
  rules:
    - "含税金额 = 不含税金额 × (1 + 税率)，允许误差 ±1元"
    - "各分项金额之和应等于合同总价，允许误差 ±1元"
  # 规则用自然语言描述，由 LLM 执行校验

deepseek:
  api_key: ""
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
```

## OCR 抽象接口

```python
class OCRProvider(ABC):
    @abstractmethod
    def recognize(self, image_path: str) -> str:
        """识别单张图片，返回原始文字"""
        pass
```

通过 `config.yaml → ocr.provider` 工厂模式实例化对应实现。

## 报告输出示例

```
合同校验报告
============
合同来源：http://192.168.1.10/contracts/001.pdf
识别页数：3 页

【提取的金额字段】
- 合同总价：¥100,000.00
- 不含税金额：¥88,495.58
- 税率：13%
- 税额：¥11,504.42

【校验结果】
✅ 含税金额 = 不含税金额 × (1 + 税率)
   88,495.58 × 1.13 = 100,000.01，误差 0.01 元，通过

⚠️ 各分项之和 = 合同总价
   未在合同中找到分项明细，无法校验，请人工确认

【总结】
1 条规则通过，1 条规则无法自动校验。
```

## 依赖包

```
langchain
langchain-openai        # DeepSeek 兼容 OpenAI 接口
langchain-community
pdf2image               # PDF 转图片（依赖 poppler）
Pillow                  # 图片处理
sqlalchemy              # 数据库连接
pymysql                 # MySQL 驱动（视数据库类型调整）
requests                # HTTP 下载
pyyaml                  # 配置文件读取
```

## 待确认事项

1. 数据库类型（MySQL / PostgreSQL / 其他）及 SQL 语句
2. OCR 提供商选择
3. 金额校验规则具体内容
