package weaver.interfaces.yy.WMS.zwbftc;

import com.alibaba.fastjson.JSONObject;
import weaver.general.BaseBean;
import weaver.integration.logging.Logger;
import weaver.integration.logging.LoggerFactory;
import weaver.interfaces.workflow.action.Action;
import weaver.soa.workflow.request.RequestInfo;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * OA 审批节点执行：将流程 requestId 推送给本地 AI Agent。
 *
 * 配置方式：在 OA 流程的审批节点 → 节点前附件操作 → 添加此 Action。
 */
public class PushToAgent extends BaseBean implements Action {

    private Logger logger = LoggerFactory.getLogger(PushToAgent.class);

    /** Agent 地址（主机名，不会随 WiFi 变动；解析失败则换 IP） */
    private static final String AGENT_URL = "http://yy_b705:18888";

    @Override
    public String execute(RequestInfo requestInfo) {
        int requestId = requestInfo.getRequestManager().getRequestid();
        logger.info("PushToAgent —— requestId=" + requestId);

        JSONObject body = new JSONObject();
        body.put("requestId", requestId);

        try {
            URL url = new URL(AGENT_URL);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            conn.setDoOutput(true);
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(5000);

            OutputStream os = conn.getOutputStream();
            os.write(body.toJSONString().getBytes("UTF-8"));
            os.close();

            int code = conn.getResponseCode();
            logger.info("Agent 响应: HTTP " + code);
            conn.disconnect();
        } catch (Exception e) {
            logger.error("推送 Agent 失败: " + e.getMessage());
        }

        return Action.SUCCESS;
    }
}
