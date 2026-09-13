"""
🛠️ TOOL DEFINITIONS & EXECUTION BACKEND
Đề tài: EV Charging Station Rescue Agent — Trợ lý AI điều phối cứu hộ sự cố trạm sạc xe điện
Mã nguồn chứa danh sách Tool Schemas (JSON Schema) và Execution Layer phục vụ cho MCP Server.
"""

import json
from typing import Dict, Any, List

# ==============================================================================
# 1. KHAI BÁO TOOL SCHEMAS CHUẨN NATIVE JSON SCHEMA (TASK 1.2)
# ==============================================================================

TOOLS_SCHEMA = [
    # --------------------------------------------------------------------------
    # Tool 1: get_station_status (Tra cứu - Read)
    # Mục đích: Lấy trạng thái hiện tại và mức độ sự cố của một trạm sạc xe điện.
    # Đây là Tool tra cứu đầu tiên trong ReAct Loop để Agent biết trạm đang
    # gặp vấn đề gì trước khi quyết định phương án xử lý tiếp theo.
    # --------------------------------------------------------------------------
    {
        "name": "get_station_status",
        "description": "Tra cứu trạng thái hiện tại và mức độ sự cố của một trạm sạc xe điện. Trả về state (OK/FAULT/OFFLINE), severity (LOW/MEDIUM/HIGH) và error_code để Agent quyết định bước ReAct tiếp theo.",
        "parameters": {
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "string",
                    "description": "Mã trạm sạc cần kiểm tra (ví dụ: 'ST001', 'ST002', 'ST003')"
                }
            },
            "required": ["station_id"]
        }
    },

    # --------------------------------------------------------------------------
    # Tool 2: find_available_technician (Tra cứu - Read)
    # Mục đích: Tìm danh sách kỹ thuật viên phù hợp gần trạm, có xét trạng thái
    # (available/busy) và chuyên môn. Tool này quyết định Dynamic Decision vì Agent
    # phải suy luận chọn kỹ thuật viên tối ưu từ Observation trả về.
    # --------------------------------------------------------------------------
    {
        "name": "find_available_technician",
        "description": "Tìm danh sách kỹ thuật viên phù hợp gần một trạm sạc đang gặp sự cố. Tool trả về danh sách ứng viên kèm khoảng cách (km), trạng thái (available/busy) và chuyên môn để Agent cân nhắc đánh đổi giữa khoảng cách và trạng thái.",
        "parameters": {
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "string",
                    "description": "Mã trạm sạc cần cứu hộ (ví dụ: 'ST001')"
                },
                "required_severity": {
                    "type": "string",
                    "enum": ["LOW", "MEDIUM", "HIGH"],
                    "description": "Mức độ sự cố tối thiểu mà kỹ thuật viên cần đáp ứng (HIGH = yêu cầu chuyên gia EV_CHARGER)."
                }
            },
            "required": ["station_id", "required_severity"]
        }
    },

    # --------------------------------------------------------------------------
    # Tool 3: create_rescue_request (Hành động - Write)
    # Mục đích: Tạo yêu cầu cứu hộ chính thức gửi tới kỹ thuật viên đã chọn.
    # Đây là Tool hành động cuối cùng trong ReAct Loop, đánh dấu hoàn tất
    # mục tiêu Long Horizon của Agent.
    # --------------------------------------------------------------------------
    {
        "name": "create_rescue_request",
        "description": "Tạo yêu cầu cứu hộ chính thức cho một trạm sạc gặp sự cố, gửi tới kỹ thuật viên đã được chọn. Trả về rescue_id để Agent đưa vào Final Answer.",
        "parameters": {
            "type": "object",
            "properties": {
                "station_id": {
                    "type": "string",
                    "description": "Mã trạm sạc đang gặp sự cố (ví dụ: 'ST001')"
                },
                "technician_id": {
                    "type": "string",
                    "description": "Mã kỹ thuật viên được phân công xử lý (ví dụ: 'TECH003')"
                },
                "severity": {
                    "type": "string",
                    "enum": ["LOW", "MEDIUM", "HIGH"],
                    "description": "Mức độ sự cố của trạm — phải khớp với kết quả trả về từ get_station_status."
                }
            },
            "required": ["station_id", "technician_id", "severity"]
        }
    }
]

# ==============================================================================
# 2. MÔ PHỎNG DỮ LIỆU & HÀM THỰC THI TOOL (EXECUTION LAYER)
# ==============================================================================

# ------------------------------------------------------------------------------
# MOCK DATABASE
# Gồm 3 bảng logic:
#   - STATIONS:        danh sách trạm sạc và trạng thái hiện tại
#   - TECHNICIANS:     danh sách kỹ thuật viên (trạng thái, khoảng cách, skill)
#   - RESCUE_REQUESTS: log các yêu cầu cứu hộ đã tạo (in-memory)
# ------------------------------------------------------------------------------
MOCK_DATABASE: Dict[str, Any] = {
    "STATIONS": {
        "ST001": {
            "station_name": "Trạm sạc Vincom Bà Triệu",
            "location": "Hà Nội",
            "state": "FAULT",
            "severity": "HIGH",
            "error_code": "E_COMM_LOST"
        },
        "ST002": {
            "station_name": "Trạm sạc Crescent Mall",
            "location": "TP. Hồ Chí Minh",
            "state": "OFFLINE",
            "severity": "MEDIUM",
            "error_code": "E_NET_TIMEOUT"
        },
        "ST003": {
            "station_name": "Trạm sạc Aeon Long Biên",
            "location": "Hà Nội",
            "state": "FAULT",
            "severity": "HIGH",
            "error_code": "E_OVERCURRENT"
        }
    },
    "TECHNICIANS": [
        {"tech_id": "TECH001", "distance_km": 2.1, "state": "busy",    "skill": "EV_CHARGER"},
        {"tech_id": "TECH002", "distance_km": 5.4, "state": "available","skill": "EV_CHARGER"},
        {"tech_id": "TECH003", "distance_km": 3.2, "state": "available","skill": "EV_CHARGER"},
        {"tech_id": "TECH004", "distance_km": 1.5, "state": "available","skill": "GENERAL"}
    ],
    "RESCUE_REQUESTS": {}
}

# Bảng xếp hạng severity để quyết định filter kỹ thuật viên theo chuyên môn
_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


def execute_get_station_status(station_id: str) -> str:
    """Thực thi tra cứu trạng thái trạm sạc theo mã trạm."""
    station = MOCK_DATABASE["STATIONS"].get(station_id.strip().upper())
    if station:
        return json.dumps({
            "status": "SUCCESS",
            "station_id": station_id,
            "data": station
        }, ensure_ascii=False)
    else:
        return json.dumps({
            "status": "NOT_FOUND",
            "message": f"Không tìm thấy trạm sạc có mã '{station_id}'"
        }, ensure_ascii=False)


def execute_find_available_technician(station_id: str, required_severity: str = "LOW") -> str:
    """
    Thực thi tìm kỹ thuật viên khả dụng gần trạm.
    Logic Dynamic Decision:
      - Nếu severity = HIGH: chỉ trả về kỹ thuật viên có skill = EV_CHARGER.
      - Nếu severity = MEDIUM/LOW: trả về mọi kỹ thuật viên available.
      - Luôn ưu tiên sắp xếp theo distance_km tăng dần.
    """
    station = MOCK_DATABASE["STATIONS"].get(station_id.strip().upper())
    if not station:
        return json.dumps({
            "status": "NOT_FOUND",
            "message": f"Không tìm thấy trạm sạc có mã '{station_id}'"
        }, ensure_ascii=False)

    severity = required_severity.upper()
    required_skill = "EV_CHARGER" if severity == "HIGH" else None

    candidates: List[Dict[str, Any]] = []
    for tech in MOCK_DATABASE["TECHNICIANS"]:
        if tech["state"] != "available":
            continue
        if required_skill and tech["skill"] != required_skill:
            continue
        candidates.append(tech)

    candidates.sort(key=lambda t: t["distance_km"])

    return json.dumps({
        "status": "SUCCESS",
        "station_id": station_id,
        "required_severity": severity,
        "candidates": candidates
    }, ensure_ascii=False)


def execute_create_rescue_request(station_id: str, technician_id: str, severity: str) -> str:
    """Thực thi tạo yêu cầu cứu hộ — ghi vào RESCUE_REQUESTS và trả về rescue_id."""
    station = MOCK_DATABASE["STATIONS"].get(station_id.strip().upper())
    if not station:
        return json.dumps({
            "status": "NOT_FOUND",
            "message": f"Không tìm thấy trạm sạc có mã '{station_id}'"
        }, ensure_ascii=False)

    tech = next((t for t in MOCK_DATABASE["TECHNICIANS"] if t["tech_id"] == technician_id), None)
    if not tech:
        return json.dumps({
            "status": "TECH_NOT_FOUND",
            "message": f"Không tìm thấy kỹ thuật viên có mã '{technician_id}'"
        }, ensure_ascii=False)

    next_index = len(MOCK_DATABASE["RESCUE_REQUESTS"]) + 1
    rescue_id = f"RES{next_index:03d}"
    MOCK_DATABASE["RESCUE_REQUESTS"][rescue_id] = {
        "station_id": station_id,
        "technician_id": technician_id,
        "severity": severity,
        "station_name": station["station_name"]
    }

    return json.dumps({
        "status": "SUCCESS",
        "rescue_id": rescue_id,
        "station_id": station_id,
        "technician_id": technician_id,
        "severity": severity,
        "message": (
            f"Đã tạo yêu cầu cứu hộ {rescue_id} cho trạm '{station['station_name']}' "
            f"(severity={severity}), phân công kỹ thuật viên {technician_id}."
        )
    }, ensure_ascii=False)


# ------------------------------------------------------------------------------
# Router: ánh xạ tên tool (theo JSON Schema) → hàm thực thi tương ứng
# ------------------------------------------------------------------------------
TOOL_ROUTER = {
    "get_station_status": execute_get_station_status,
    "find_available_technician": execute_find_available_technician,
    "create_rescue_request": execute_create_rescue_request
}


def dispatch_tool_call(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Hàm trung chuyển thực thi tool — nhận yêu cầu từ MCP Client và trả về JSON string."""
    if tool_name in TOOL_ROUTER:
        try:
            return TOOL_ROUTER[tool_name](**arguments)
        except Exception as e:
            return json.dumps({"status": "EXECUTION_ERROR", "error": str(e)}, ensure_ascii=False)
    return json.dumps({"status": "UNKNOWN_TOOL", "error": f"Tool '{tool_name}' không tồn tại!"}, ensure_ascii=False)
