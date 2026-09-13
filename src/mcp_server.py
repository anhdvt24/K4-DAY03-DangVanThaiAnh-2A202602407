"""
🔌 MODEL CONTEXT PROTOCOL (MCP) SERVER MODULE
Đề tài: EV Charging Station Rescue Agent
Giả lập MCP Server tuân thủ chuẩn giao thức Model Context Protocol,
cung cấp 3 Tool: get_station_status, find_available_technician, create_rescue_request.
"""

import json
import sys
from typing import Dict, Any, List
from tools import TOOLS_SCHEMA, dispatch_tool_call

# Đảm bảo stdout in được tiếng Việt trên Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


class MCPEVRescueServer:
    """
    Giả lập MCP Server phục vụ các Tool cho EV Charging Station Rescue Agent.
    Mỗi lệnh gọi Tool được đóng gói theo chuẩn JSON-RPC 2.0.
    """

    def __init__(self, server_name: str = "ev-charging-rescue-mcp-server"):
        self.server_name = server_name
        self.version = "2026.1.0"

    def list_tools(self) -> List[Dict[str, Any]]:
        """Trả về danh sách các Tools chuẩn giao thức MCP."""
        return TOOLS_SCHEMA

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        TASK 2.1 — Thực thi request gọi Tool theo chuẩn MCP JSON-RPC 2.0.

        Luồng xử lý:
          1. Gọi dispatch_tool_call(tool_name, arguments)  →  JSON string.
          2. Parse JSON string về Python dict.
          3. Nếu status trả về là lỗi nghiệp vụ → đóng gói JSON-RPC error.
             Ngược lại → đóng gói JSON-RPC result.
          4. Exception bất ngờ → JSON-RPC error code -32603 (Internal Error).
        """
        try:
            # Bước 1: Thực thi tool qua dispatch_tool_call từ src/tools.py
            result_str = dispatch_tool_call(tool_name, arguments)

            # Bước 2: Parse JSON string → dict
            try:
                content: Dict[str, Any] = json.loads(result_str)
            except json.JSONDecodeError:
                content = {"status": "EXECUTION_ERROR", "error": "Tool response is not valid JSON"}

            # Bước 3: Phân loại response — lỗi nghiệp vụ vs. thành công
            error_statuses = {"UNKNOWN_TOOL", "EXECUTION_ERROR", "NOT_FOUND", "TECH_NOT_FOUND"}
            status = content.get("status")

            if status in error_statuses:
                # Đóng gói JSON-RPC 2.0 error response
                return {
                    "jsonrpc": "2.0",
                    "server": self.server_name,
                    "tool": tool_name,
                    "error": {
                        "code": -32602 if status in ("UNKNOWN_TOOL",) else -32603,
                        "message": content.get("message") or content.get("error") or "Tool execution failed",
                        "data": content
                    }
                }

            # Đóng gói JSON-RPC 2.0 success response
            return {
                "jsonrpc": "2.0",
                "server": self.server_name,
                "tool": tool_name,
                "result": content
            }

        except Exception as e:
            # Lỗi bất ngờ từ phía server (vd. arguments sai kiểu, crash)
            return {
                "jsonrpc": "2.0",
                "server": self.server_name,
                "tool": tool_name,
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": str(e)
                }
            }


if __name__ == "__main__":
    print("==========================================================")
    print("🔌 KIỂM THỬ ĐỘC LẬP MCP SERVER (ev-charging-rescue-mcp-server)")
    print("==========================================================")

    server = MCPEVRescueServer()
    tools = server.list_tools()

    print(f"✅ Khởi tạo thành công MCP Server: {server.server_name} (Version: {server.version})")
    print(f"📦 Số lượng Tools công bố: {len(tools)}")
    for t in tools:
        print(f"   - {t['name']}: {len(t['parameters']['properties'])} params, "
              f"required={t['parameters'].get('required', [])}")

    # --------------------------------------------------------------------------
    # Kiểm tra trạng thái TODO 1.2 (Tool Schema)
    # --------------------------------------------------------------------------
    target_tool = "get_station_status"
    schema = next((t for t in tools if t.get("name") == target_tool), None)
    if schema and not schema.get("parameters", {}).get("properties"):
        print(f"⏳ [TODO 1.2]: Tool '{target_tool}' chưa được định nghĩa properties trong 'src/tools.py'.")
    else:
        print(f"✅ [TODO 1.2]: Tool '{target_tool}' đã có schema đầy đủ "
              f"({len(schema['parameters']['properties'])} properties).")

    # --------------------------------------------------------------------------
    # Kiểm tra trạng thái TODO 2.1 (call_tool)
    # --------------------------------------------------------------------------
    print("\n----------------------------------------------------------")
    print("TEST 1 — call_tool('get_station_status', {'station_id': 'ST001'})")
    print("----------------------------------------------------------")
    test_result = server.call_tool("get_station_status", {"station_id": "ST001"})
    if not test_result:
        print("⏳ [TODO 2.1]: Hàm call_tool() đang trả về rỗng. Hãy hoàn thiện TODO 2.1!")
    else:
        print(f"✅ [TODO 2.1]: Dispatch tool thành công. JSON-RPC response:")
        print(json.dumps(test_result, ensure_ascii=False, indent=2))

    print("\n----------------------------------------------------------")
    print("TEST 2 — call_tool('find_available_technician', {'station_id': 'ST001', 'required_severity': 'HIGH'})")
    print("----------------------------------------------------------")
    test2 = server.call_tool("find_available_technician", {"station_id": "ST001", "required_severity": "HIGH"})
    print(json.dumps(test2, ensure_ascii=False, indent=2))

    print("\n----------------------------------------------------------")
    print("TEST 3 — call_tool('create_rescue_request', {...})")
    print("----------------------------------------------------------")
    test3 = server.call_tool("create_rescue_request", {
        "station_id": "ST001",
        "technician_id": "TECH003",
        "severity": "HIGH"
    })
    print(json.dumps(test3, ensure_ascii=False, indent=2))

    print("\n----------------------------------------------------------")
    print("TEST 4 — Edge case: tool không tồn tại → JSON-RPC error")
    print("----------------------------------------------------------")
    test4 = server.call_tool("unknown_tool", {})
    print(json.dumps(test4, ensure_ascii=False, indent=2))

    print("\n----------------------------------------------------------")
    print("TEST 5 — Edge case: station_id không tồn tại → JSON-RPC error")
    print("----------------------------------------------------------")
    test5 = server.call_tool("get_station_status", {"station_id": "ST999"})
    print(json.dumps(test5, ensure_ascii=False, indent=2))
