import json
import pyodbc
from langchain_core.tools import Tool
from contract_agent.config import load_config


def _build_conn_str(config: dict) -> str:
    """Build a pyodbc connection string from config."""
    db = config["database"]
    driver = db.get("driver", "ODBC Driver 17 for SQL Server")
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={db['server']},{db['port']};"
        f"DATABASE={db['db']};"
        f"UID={db['user']};"
        f"PWD={db['password']};"
    )


def _execute_sql(request_id: int) -> list[dict]:
    """Execute the TSQL query from config and return file info rows."""
    config = load_config()
    sql = config["database"]["sql"]

    # Validate request_id is already an int — safe to interpolate
    sql = sql.replace(":request_id", str(request_id))

    conn = pyodbc.connect(_build_conn_str(config))
    try:
        cursor = conn.cursor()
        cursor.execute(sql)

        columns = [col[0] for col in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()

    return rows


def _query_contract_url(input_str: str) -> str:
    """Query OA attachment files by request_id.

    Input:  JSON string like ``{"request_id": 917393}``.
    Output: JSON array of file objects, each with file_id, filename,
            file_size, and physical_path.
    """
    try:
        params = json.loads(input_str)
    except json.JSONDecodeError:
        return "错误：输入必须是 JSON 格式，例如 {\"request_id\": 917393}"

    request_id = params.get("request_id")
    if request_id is None:
        return "错误：缺少 request_id 参数"

    try:
        request_id = int(request_id)
    except (ValueError, TypeError):
        return f"错误：request_id 必须是整数，收到：{request_id}"

    try:
        rows = _execute_sql(request_id)
    except Exception as e:
        return f"数据库查询失败：{e}"

    if not rows:
        return f"未找到 requestId={request_id} 对应的附件，返回空列表"

    # The TSQL fallback path returns ``SELECT '[]' AS result`` when there
    # are no attachment fields or all fields are empty — surface it as-is.
    if len(rows) == 1 and set(rows[0].keys()) == {"result"}:
        return rows[0]["result"]

    # Normalise column names to camelCase for the downstream tool chain
    result = []
    for row in rows:
        result.append({
            "file_id": row.get("file_id"),
            "filename": row.get("filename"),
            "file_size": row.get("file_size"),
            "physical_path": row.get("physical_path"),
        })

    return json.dumps(result, ensure_ascii=False, default=str)


query_contract_url_tool = Tool(
    name="query_contract_url",
    func=_query_contract_url,
    description=(
        "根据 requestId 查询 OA 流程表单中的附件文件信息。"
        "输入：JSON 字符串，包含 request_id，例如 {\"request_id\": 917393}。"
        "输出：JSON 字符串数组，每个元素包含 file_id（文件ID）、"
        "filename（文件名）、file_size（文件大小）、physical_path（物理路径）。"
    ),
)
