"""
🚀 CORE AGENT APPLICATION (DAY 03: CHATBOT VS REACT AGENT)
Thực thi so sánh giữa Chatbot Baseline (Cấp 2) và ReAct Agent kết nối MCP Server (Cấp 3).
Đề tài: EV Charging Station Rescue Agent — Trợ lý AI điều phối cứu hộ sự cố trạm sạc xe điện.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Dict, List
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# Timeout chốt hạ ở app-level (giây) — bảo vệ khi SDK không raise (vd. Google GenAI SDK đôi khi im lặng).
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "35"))


def flush_print(*args, **kwargs):
    """Wrapper cho print() luôn flush=True để tránh lặp text trên PowerShell."""
    kwargs.setdefault('flush', True)
    print(*args, **kwargs)

from mcp_server import MCPEVRescueServer
from prompts import (
    CHATBOT_BASELINE_PROMPT,
    REACT_AGENT_SYSTEM_PROMPT,
    MAX_ITERATIONS
)
from providers import get_llm_provider

load_dotenv()

def load_test_cases():
    """Tải danh sách 5 test cases từ config/test_cases.json hoặc config/test_cases.example.json"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "test_cases.json")
    if not os.path.exists(config_path):
        example_path = os.path.join(base_dir, "config", "test_cases.example.json")
        if os.path.exists(example_path):
            print("⚠️ [CONFIG NOTICE]: Chưa thấy file 'config/test_cases.json'. Đang dùng mẫu 'config/test_cases.example.json'.")
            print("👉 Hãy chạy: copy config/test_cases.example.json config/test_cases.json và viết test cases theo đề tài của bạn!\n")
            config_path = example_path
        else:
            config_path = "test_cases.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_waterfall_trace(trace_data: list):
    """Ghi vết log Waterfall Trace Log ra file docs/trace_waterfall.json"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(base_dir, "docs")
    os.makedirs(docs_dir, exist_ok=True)
    trace_path = os.path.join(docs_dir, "trace_waterfall.json")
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(trace_data, f, ensure_ascii=False, indent=2)
    flush_print(f"📊 [OBSERVABILITY]: Đã lưu {len(trace_data)} sự kiện Waterfall Trace tại '{trace_path}'!")


def run_baseline_chatbot(user_query: str, provider):
    """Chạy Chatbot gốc (Cấp 2) không có công cụ gọi Tool"""
    flush_print(f"\n💬 [CHATBOT BASELINE] Câu hỏi: {user_query}")
    response = provider.generate(user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    flush_print(f"🤖 Chatbot phản hồi:\n{response}")


def _format_tool_observation(obs_data: dict, tool_name: str) -> str:
    """
    Format Final Answer phù hợp với schema EV Charging (KHÔNG còn field VinUni).
    Branch theo tool_name để tóm tắt observation cho người dùng cuối.
    """
    status = obs_data.get("status", "")

    if status == "NOT_FOUND" or status == "TECH_NOT_FOUND":
        return obs_data.get("message", "Không tìm thấy thông tin trong hệ thống.")

    if "message" in obs_data and tool_name == "create_rescue_request":
        return obs_data["message"]

    if tool_name == "get_station_status":
        d = obs_data.get("data", {}) or {}
        return (
            f"Trạm sạc {obs_data.get('station_id', '')} — '{d.get('station_name', 'không rõ')}' "
            f"(khu vực: {d.get('location', 'không rõ')}) đang ở trạng thái {d.get('state', 'không rõ')}, "
            f"mức độ sự cố {d.get('severity', 'không rõ')}, mã lỗi {d.get('error_code', 'không rõ')}."
        )

    if tool_name == "find_available_technician":
        candidates = obs_data.get("candidates", []) or []
        if not candidates:
            return f"Không có kỹ thuật viên khả dụng cho trạm {obs_data.get('station_id', '')}."
        lines = [
            f"Tìm thấy {len(candidates)} kỹ thuật viên khả dụng cho trạm {obs_data.get('station_id', '')} "
            f"(yêu cầu severity={obs_data.get('required_severity', 'không rõ')}):"
        ]
        for i, tech in enumerate(candidates, start=1):
            lines.append(
                f"  {i}. {tech.get('tech_id', '?')} — cách {tech.get('distance_km', '?')} km, "
                f"trạng thái {tech.get('state', '?')}, chuyên môn {tech.get('skill', '?')}."
            )
        return "\n".join(lines)

    # Fallback chung cho mọi tool khác
    return f"Phản hồi từ công cụ {tool_name}: {json.dumps(obs_data, ensure_ascii=False)}"


def run_react_agent(user_query: str, provider, mcp_server: MCPEVRescueServer) -> list:
    """
    [STRICT REACT LOOP] — Thought -> Action -> Observation -> Thought (lặp lại).

    Triển khai đúng sơ đồ mermaid trong CODELAB:
        A[User Query] -> B[LLM Thought] -> C{cần Tool?}
        C -- Có --> E[Action] -> F[MCP Server] -> G[Observation] -> B

    Sau khi nhận Observation, message được NẠP vào `messages_history` và vòng lặp
    QUAY LẠI LLM Thought (không tự template Final Answer trong app.py). Đây là điểm
    khác biệt với cài đặt "shortcut": mọi quyết định tổng hợp câu trả lời đều do LLM
    thực hiện, đảm bảo Agent thực sự suy luận đa bước (multi-step reasoning) cho TC04.
    """
    flush_print(f"\n🤖 [REACT AGENT] Câu hỏi: {user_query}")

    step = 0
    trace_logs: List[Dict[str, Any]] = []
    tools_list = mcp_server.list_tools()
    messages_history: List[Dict[str, Any]] = []
    final_answer: str | None = None
    # Executor global, shutdown(wait=False) ở cuối để tránh context-manager chờ thread treo.
    _llm_executor = ThreadPoolExecutor(max_workers=1)

    while step < MAX_ITERATIONS:
        step += 1
        step_start_time = time.time()
        flush_print(f"\n--- 🔄 Vòng lặp ReAct Loop (Step {step}/{MAX_ITERATIONS}) ---")

        # Gọi LLM với Native Tool Calling + history tích lũy (có timeout chốt hạ ở app-level).
        try:
            _future = _llm_executor.submit(
                provider.generate_with_tools,
                user_query,
                tools_list,
                REACT_AGENT_SYSTEM_PROMPT,
                messages_history if messages_history else None,
            )
            llm_response = _future.result(timeout=LLM_TIMEOUT_SECONDS)
        except FuturesTimeout:
            _future.cancel()  # yêu cầu cancel (không tác dụng với thread đã chạy, nhưng tránh re-enter).
            flush_print(f"⏰ [LLM Timeout] Provider không phản hồi trong {LLM_TIMEOUT_SECONDS}s. Fallback Final Answer.")
            final_answer = (
                f"⚠️ Hệ thống đang quá tải hoặc LLM provider không phản hồi trong "
                f"{LLM_TIMEOUT_SECONDS}s. Vui lòng thử lại sau ít phút hoặc chuyển sang "
                f"LLM_PROVIDER=mock để chạy offline."
            )
            flush_print(f"🏁 [Final Answer]: {final_answer}")
            trace_logs.append({
                "step": step,
                "query": user_query,
                "action_type": "LLM_TIMEOUT",
                "thought": f"Provider bị timeout sau {LLM_TIMEOUT_SECONDS}s.",
                "output": final_answer,
                "latency_ms": round((time.time() - step_start_time) * 1000, 2),
            })
            break
        except Exception as _e:
            flush_print(f"💥 [LLM Exception]: {_e}. Fallback Final Answer.")
            final_answer = (
                f"⚠️ LLM provider gặp lỗi: {type(_e).__name__}: {_e}. "
                f"Vui lòng kiểm tra API key / mạng, hoặc chuyển sang LLM_PROVIDER=mock."
            )
            flush_print(f"🏁 [Final Answer]: {final_answer}")
            trace_logs.append({
                "step": step,
                "query": user_query,
                "action_type": "LLM_ERROR",
                "thought": f"Provider ném exception: {type(_e).__name__}.",
                "output": final_answer,
                "latency_ms": round((time.time() - step_start_time) * 1000, 2),
            })
            break
        latency_ms = round((time.time() - step_start_time) * 1000, 2)

        thought = llm_response.get("thought", "Đang suy luận...")
        flush_print(f"🧠 [Thought]: {thought}")

        # ---------- Nhánh 1: LLM trả Final Answer bằng văn bản ----------
        if llm_response.get("type") == "text":
            final_answer = llm_response.get("content", "")
            flush_print(f"🏁 [Final Answer]: {final_answer}")
            trace_logs.append({
                "step": step,
                "query": user_query,
                "action_type": "FINAL_ANSWER",
                "thought": thought,
                "output": final_answer,
                "latency_ms": latency_ms,
            })
            break

        # ---------- Nhánh 2: LLM đề xuất gọi Tool (Action) ----------
        elif llm_response.get("type") == "tool_call":
            tool_name = llm_response.get("tool_name")
            arguments = llm_response.get("arguments", {}) or {}

            flush_print(f"🛠️ [Action Proposed]: {tool_name}({arguments})")

            # Nạp assistant turn (tool_call) vào history
            messages_history.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{"name": tool_name, "arguments": arguments}],
            })

            # Thực thi Tool qua MCP Server
            mcp_result = mcp_server.call_tool(tool_name, arguments)

            # Chuẩn hóa observation (cả JSON-RPC result.success lẫn error.data đều là observation)
            if "result" in mcp_result and mcp_result["result"]:
                obs_data = mcp_result["result"]
            elif "error" in mcp_result:
                obs_data = mcp_result["error"].get("data") or {
                    "status": "INTERNAL_ERROR",
                    "message": mcp_result["error"].get("message", "Unknown error"),
                }
            else:
                obs_data = mcp_result or {"status": "EMPTY", "message": "MCP Server trả về rỗng."}

            obs_str = json.dumps(obs_data, ensure_ascii=False)
            flush_print(f"👁️ [Observation từ MCP Server]: {obs_str}")

            # Nạp Observation (role="tool") vào history để LLM thấy ở lượt Thought sau
            messages_history.append({
                "role": "tool",
                "name": tool_name,
                "content": obs_str,
            })

            trace_logs.append({
                "step": step,
                "query": user_query,
                "action_type": "TOOL_EXECUTION",
                "tool_name": tool_name,
                "arguments": arguments,
                "observation": obs_data,
                "latency_ms": latency_ms,
            })

            # QUAN TRỌNG — KHÔNG break: tiếp tục vòng lặp để LLM quay lại Thought
            # và tự tổng hợp Final Answer từ Observation vừa nạp (đúng sơ đồ mermaid).
            continue

        # ---------- Nhánh 3: response không hợp lệ ----------
        else:
            flush_print(f"⚠️ [WARN]: LLM trả response không hợp lệ: {llm_response}")
            break

    # Shutdown executor KHÔNG chờ thread đang treo — tránh block toàn bộ test suite.
    _llm_executor.shutdown(wait=False)

    # Hết MAX_ITERATIONS mà chưa có Final Answer → fallback an toàn
    if final_answer is None:
        final_answer = (
            "⚠️ Agent đã đạt số lượt suy luận tối đa mà chưa đưa ra câu trả lời cuối. "
            "Vui lòng thử lại với câu hỏi ngắn gọn hơn hoặc cụ thể hơn."
        )
        flush_print(f"🏁 [Final Answer]: {final_answer}")
        trace_logs.append({
            "step": step + 1,
            "query": user_query,
            "action_type": "FINAL_ANSWER",
            "thought": "Đạt MAX_ITERATIONS mà chưa có Final Answer, fallback an toàn.",
            "output": final_answer,
            "latency_ms": 10.0,
        })

    return trace_logs


if __name__ == "__main__":
    flush_print("==========================================================")
    flush_print("⚡ EV CHARGING RESCUE AGENT — DAY 03 LAB: CHATBOT VS REACT AGENT")
    flush_print("==========================================================")

    provider = get_llm_provider()
    mcp_server = MCPEVRescueServer()

    flush_print(f"🔌 LLM Provider: {provider.__class__.__name__}")
    flush_print(f"🌐 MCP Server: {mcp_server.server_name}\n")

    tests = load_test_cases()
    flush_print(f"✅ Đã tải thành công {len(tests)} Test Cases thử nghiệm.\n")

    if "--interactive" in sys.argv:
        flush_print("🎮 [INTERACTIVE MODE] Trò chuyện trực tiếp với ReAct Agent:")
        flush_print("💡 Gợi ý câu hỏi thử nghiệm (đề tài EV Charging):")
        flush_print("   - Tra cứu: 'Trạm sạc ST001 hiện đang gặp sự cố gì?'")
        flush_print("   - Tìm kỹ thuật viên: 'Tìm kỹ thuật viên EV_CHARGER khả dụng cho trạm ST001'")
        flush_print("   - Tạo yêu cầu cứu hộ: 'Tạo yêu cầu cứu hộ RES001 cho trạm ST001, phân công TECH003 với severity HIGH'")
        flush_print("   - Gõ 'exit' hoặc 'quit' để kết thúc phiên trò chuyện.\n")
        while True:
            try:
                user_input = input("👤 Người dùng hỏi: ").strip()
                if not user_input or user_input.lower() in ["exit", "quit"]:
                    flush_print("👋 Tạm biệt! Kết thúc phiên trò chuyện.")
                    break
                logs = run_react_agent(user_input, provider, mcp_server)
                save_waterfall_trace(logs)
            except (KeyboardInterrupt, EOFError):
                flush_print("\n👋 Đã thoát phiên tương tác.")
                break
    elif "--all" in sys.argv:
        flush_print("🚀 [TEST SUITE MODE] Kiểm tra 5 Test Cases:")
        completed_count = 0
        todo_count = 0
        all_traces = []

        for tc in tests:
            flush_print(f"\n==================================================")
            flush_print(f"🧪 [{tc['id']}] Loại test: {tc['type']} (Độ phức tạp: {tc['complexity']})")
            flush_print(f"📌 Kỳ vọng: {tc['expected_behavior']}")

            if tc["question"].strip().startswith("TODO"):
                flush_print(f"⏸️ [CHƯA KÍCH HOẠT - ĐANG LÀ TODO]:")
                flush_print(f"   {tc['question']}")
                flush_print(f"   👉 Hãy mở file 'config/test_cases.json' để viết câu hỏi thực tế cho Test Case này!")
                todo_count += 1
            else:
                logs = run_react_agent(tc["question"], provider, mcp_server)
                all_traces.extend(logs)
                completed_count += 1

        flush_print(f"\n==================================================")
        flush_print(f"📊 [KẾT QUẢ TEST SUITE]: Đã thực thi {completed_count}/{len(tests)} Test Cases | {todo_count} Test Cases đang chờ điền câu hỏi (TODO)")
        if all_traces:
            save_waterfall_trace(all_traces)
        flush_print(f"💡 Để trò chuyện trực tiếp từng câu: Chạy 'python src/app.py --interactive'")
    else:
        # Chế độ mặc định khi chỉ gõ 'python src/app.py'
        flush_print("ℹ️ HƯỚNG DẪN SỬ DỤNG CHƯƠNG TRÌNH:")
        flush_print("  1. Chat trực tiếp liên tục:   python src/app.py --interactive")
        flush_print("  2. Chạy toàn bộ Test Cases:    python src/app.py --all\n")

        sample_query = tests[1]["question"]
        flush_print(f"--- 🏁 DEMO CHẠY THỬ 1 TEST CASE MẪU (TC02: Tra cứu trạm sạc) ---")
        logs = run_react_agent(sample_query, provider, mcp_server)
        save_waterfall_trace(logs)
        flush_print("\n💡 Hãy thử ngay lệnh: python src/app.py --interactive để chat trực tiếp!")
