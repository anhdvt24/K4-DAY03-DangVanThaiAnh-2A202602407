"""
🔌 MULTI-PROVIDER LLM ADAPTER (Google Gemini, OpenAI & Offline Mock)
Hỗ trợ Native Tool Calling và chuyển đổi linh hoạt qua biến môi trường LLM_PROVIDER.
"""

import os
import sys
import json
from typing import Dict, Any, List
from dotenv import load_dotenv

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

class BaseLLMProvider:
    """Interface cơ sở cho các LLM Provider hỗ trợ Native Tool Calling"""
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError

    def generate_with_tools(
        self,
        prompt: str,
        tools_schema: List[Dict[str, Any]],
        system_prompt: str = "",
        messages_history: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sinh phản hồi có hỗ trợ Native Tool Calling.

        Args:
            prompt: Câu hỏi gốc của người dùng (giữ cố định qua các turn).
            tools_schema: Danh sách JSON Schema các Tool công bố qua MCP Server.
            system_prompt: System instruction cho LLM.
            messages_history: Lịch sử turn trước đó dạng
                [
                    {"role": "assistant", "content": None,
                     "tool_calls": [{"name": ..., "arguments": ...}]},
                    {"role": "tool", "name": ..., "content": "<json string>"}
                ]
                — để triển khai strict ReAct Loop (Thought -> Action -> Observation
                  -> quay lại Thought). Mặc định None nghĩa là single-shot.
        """
        raise NotImplementedError


class MockOfflineProvider(BaseLLMProvider):
    """
    Offline Mock Provider dùng để chạy thử mà không tốn API Key.
    Đề tài: EV Charging Station Rescue Agent — mô phỏng đúng tool schema EV.
    """

    def __init__(self):
        self.model_name = "Offline-Mock-Model-2026"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        return (
            f"[Mock Chatbot Response]: Tôi là Trợ lý Tư vấn Hệ thống Cứu hộ Trạm sạc Xe điện (EV). "
            f"Đã nhận câu hỏi '{prompt}'. (Chế độ Chatbot không có Tool tra cứu thời gian thực)."
        )

    def generate_with_tools(
        self,
        prompt: str,
        tools_schema: List[Dict[str, Any]],
        system_prompt: str = "",
        messages_history: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Strict ReAct Loop cho Mock Provider:
        - Turn đầu (messages_history rỗng): route theo keyword để quyết định tool_call hay text.
        - Turn sau (last message role="tool"): LLM đã thấy Observation → synthesize Final Answer.
        """
        # ---- Strict ReAct: nếu message cuối là tool result → Final Answer ----
        if messages_history and len(messages_history) > 0:
            last_msg = messages_history[-1]
            if last_msg.get("role") == "tool":
                return self._synthesize_final_answer(last_msg)

        prompt_lower = prompt.lower()

        # ---- EV Charging keyword routing --------------------------------------
        # TC04 (multi-step): truy vấn có nhắc 2-3 trạm/tech/đặt cứu hộ → simulate gọi get_station_status
        # rồi find_available_technician (chỉ trả final 1 tool_call để bám sát Mock offline đơn giản).
        has_st003 = "st003" in prompt_lower
        has_st001 = "st001" in prompt_lower
        has_st002 = "st002" in prompt_lower
        has_st999 = "st999" in prompt_lower
        has_rescue = any(k in prompt_lower for k in ["tạo yêu cầu", "cứu hộ", "phân công", "tạo rescue", "đặt cứu"])
        has_find_tech = any(k in prompt_lower for k in ["kỹ thuật viên", "tìm tech", "tech khả dụng", "tìm kỹ thuật"])

        # TC03 — tạo yêu cầu cứu hộ cụ thể (ưu tiên tool action trước)
        if has_rescue and has_st001:
            return {
                "type": "tool_call",
                "tool_name": "create_rescue_request",
                "arguments": {"station_id": "ST001", "technician_id": "TECH003", "severity": "HIGH"},
                "thought": "Người dùng yêu cầu tạo yêu cầu cứu hộ cho ST001 với TECH003 mức HIGH. Tôi sẽ gọi tool create_rescue_request."
            }

        # TC04 — multi-step reasoning (mock đơn giản: gọi find_available_technician trước,
        # agent sẽ tổng hợp sau; bám sát test case mong đợi tool call đầu tiên).
        if (has_st003 or has_st001) and has_find_tech:
            station = "ST003" if has_st003 else "ST001"
            return {
                "type": "tool_call",
                "tool_name": "find_available_technician",
                "arguments": {"station_id": station, "required_severity": "HIGH"},
                "thought": f"Trạm {station} đang gặp sự cố nghiêm trọng. Tôi sẽ gọi tool find_available_technician với required_severity=HIGH."
            }

        # TC02 — tra cứu trạng thái trạm (kèm "trạng thái", "sự cố", "lỗi")
        if (has_st001 or has_st003 or has_st002) and any(
            k in prompt_lower for k in ["trạng thái", "sự cố", "lỗi", "kiểm tra", "gặp"]
        ):
            station = "ST001" if has_st001 else ("ST003" if has_st003 else "ST002")
            return {
                "type": "tool_call",
                "tool_name": "get_station_status",
                "arguments": {"station_id": station},
                "thought": f"Người dùng muốn tra cứu trạng thái trạm {station}. Tôi sẽ gọi tool get_station_status."
            }

        # TC05 — edge case trạm không tồn tại
        if has_st999:
            return {
                "type": "tool_call",
                "tool_name": "get_station_status",
                "arguments": {"station_id": "ST999"},
                "thought": "Người dùng hỏi trạm ST999. Tôi sẽ gọi tool get_station_status để kiểm tra."
            }

        # TC01 / direct_query — câu hỏi chung → text-only
        return {
            "type": "text",
            "content": (
                "[Mock Agent Response]: Hệ thống điều phối cứu hộ trạm sạc xe điện hoạt động theo quy trình "
                "3 bước chính: (1) Giám sát & phát hiện sự cố (state=FAULT/OFFLINE); (2) Phân loại mức độ "
                "(LOW/MEDIUM/HIGH) và tìm kỹ thuật viên phù hợp; (3) Phân công cứu hộ qua yêu cầu chính thức."
            ),
            "thought": "Câu hỏi chung về quy trình điều phối, trả lời trực tiếp không cần gọi Tool."
        }

    def _synthesize_final_answer(self, tool_message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Helper: tổng hợp Final Answer từ 1 tool message cuối cùng trong history.
        Mô phỏng hành vi của LLM thật khi đã nhận Observation: phân tích nội dung,
        chọn schema phù hợp theo tool_name và render câu trả lời tự nhiên.
        """
        tool_name = tool_message.get("name", "")
        raw_content = tool_message.get("content", "{}")

        try:
            obs = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
        except (json.JSONDecodeError, TypeError):
            obs = {}

        status = obs.get("status")

        # ----- Trường hợp lỗi nghiệp vụ -----
        if status in ("NOT_FOUND", "UNKNOWN_TOOL", "TECH_NOT_FOUND", "EXECUTION_ERROR"):
            message = obs.get("message") or obs.get("error") or "Hệ thống không tìm thấy thông tin yêu cầu."
            return {
                "type": "text",
                "content": message,
                "thought": (
                    f"Tool '{tool_name}' trả về lỗi ({status}). "
                    "Tổng hợp Final Answer thân thiện cho người dùng, không bịa đặt dữ liệu."
                )
            }

        # ----- Trường hợp SUCCESS — render theo từng tool -----
        if status == "SUCCESS":
            if tool_name == "get_station_status":
                data = obs.get("data", {}) or {}
                content = (
                    f"Trạm sạc {obs.get('station_id', '?')} — {data.get('station_name', 'không rõ')} "
                    f"(khu vực: {data.get('location', 'không rõ')}) đang ở trạng thái "
                    f"**{data.get('state', '?')}** với mức độ sự cố **{data.get('severity', '?')}** "
                    f"(mã lỗi: {data.get('error_code', 'N/A')})."
                )
                thought = (
                    f"Đã nhận Observation từ '{tool_name}'. Tổng hợp trạng thái trạm "
                    f"thành Final Answer cho người dùng."
                )

            elif tool_name == "find_available_technician":
                candidates = obs.get("candidates", []) or []
                if not candidates:
                    content = (
                        f"Trạm {obs.get('station_id', '?')} yêu cầu mức độ "
                        f"{obs.get('required_severity', '?')}, nhưng hệ thống không tìm thấy "
                        f"kỹ thuật viên khả dụng phù hợp. Vui lòng mở rộng phạm vi hoặc chờ điều phối."
                    )
                else:
                    listed = "; ".join(
                        f"{c.get('tech_id')} (cách {c.get('distance_km')} km, "
                        f"trạng thái {c.get('state')}, skill {c.get('skill')})"
                        for c in candidates[:3]
                    )
                    content = (
                        f"Tìm thấy {len(candidates)} kỹ thuật viên khả dụng cho trạm "
                        f"{obs.get('station_id', '?')} (mức độ {obs.get('required_severity', '?')}): "
                        f"{listed}. Kỹ thuật viên tối ưu (gần nhất + đúng chuyên môn) được khuyến nghị "
                        f"là {candidates[0].get('tech_id')}."
                    )
                thought = (
                    f"Đã nhận Observation từ '{tool_name}'. Tổng hợp danh sách ứng viên "
                    f"và khuyến nghị kỹ thuật viên tối ưu."
                )

            elif tool_name == "create_rescue_request":
                content = (
                    f"{obs.get('message', 'Đã tạo yêu cầu cứu hộ.')} "
                    f"Mã yêu cầu: **{obs.get('rescue_id', '?')}** — "
                    f"trạm {obs.get('station_id', '?')} / kỹ thuật viên "
                    f"{obs.get('technician_id', '?')} / mức độ {obs.get('severity', '?')}."
                )
                thought = (
                    f"Đã nhận Observation từ '{tool_name}'. Xác nhận rescue_id và "
                    f"tổng hợp Final Answer cho người dùng."
                )

            else:
                content = (
                    f"Đã hoàn tất tool '{tool_name}'. Kết quả: "
                    f"{json.dumps(obs, ensure_ascii=False)}"
                )
                thought = "Tool không xác định trước, trả nguyên Observation."

            return {"type": "text", "content": content, "thought": thought}

        # ----- Fallback cuối cùng -----
        return {
            "type": "text",
            "content": f"Đã nhận phản hồi từ tool '{tool_name}': {json.dumps(obs, ensure_ascii=False)}",
            "thought": "Observation không rõ status, trả nguyên nội dung."
        }


class GeminiProvider(BaseLLMProvider):
    """Google Gemini Provider (Native Tool Calling với Google GenAI SDK)"""
    # Timeout mặc định cho HTTP request tới Gemini API (ms). Có thể override bằng env GEMINI_TIMEOUT.
    DEFAULT_TIMEOUT_MS = 30_000

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gemini-2.5-flash"
        try:
            self.timeout_ms = int(os.getenv("GEMINI_TIMEOUT", str(self.DEFAULT_TIMEOUT_MS)))
        except (TypeError, ValueError):
            self.timeout_ms = self.DEFAULT_TIMEOUT_MS

    def _build_client(self):
        """Khởi tạo genai.Client kèm HttpOptions(timeout=...) để chống treo vĩnh viễn."""
        from google import genai
        from google.genai import types as genai_types
        return genai.Client(
            api_key=self.api_key,
            http_options=genai_types.HttpOptions(timeout=self.timeout_ms),
        )

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return "[Gemini Error]: Chưa cấu hình GEMINI_API_KEY trong file .env! Đang sử dụng chế độ Mock."
        try:
            client = self._build_client()
            contents = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = client.models.generate_content(model=self.model_name, contents=contents)
            return response.text
        except Exception as e:
            return f"[Gemini Exception]: {str(e)}"

    def generate_with_tools(
        self,
        prompt: str,
        tools_schema: List[Dict[str, Any]],
        system_prompt: str = "",
        messages_history: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            print("ℹ️ [Gemini Provider]: Chưa tìm thấy GEMINI_API_KEY hợp lệ. Tự động chuyển sang Mock Offline.")
            return MockOfflineProvider().generate_with_tools(
                prompt, tools_schema, system_prompt, messages_history
            )

        try:
            from google.genai import types

            client = self._build_client()

            # Chuẩn hóa function declarations cho Gemini SDK
            function_declarations = []
            for tool in tools_schema:
                if not tool.get("name") or not tool.get("parameters"):
                    continue
                function_declarations.append({
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {})
                })

            config = types.GenerateContentConfig(
                system_instruction=system_prompt if system_prompt else None,
                tools=[{"function_declarations": function_declarations}] if function_declarations else None,
                temperature=0.2
            )

            # ----- Build multi-turn contents nếu có messages_history -----
            if messages_history and len(messages_history) > 0:
                contents = []
                # User turn đầu
                contents.append(
                    types.Content(role="user", parts=[types.Part(text=prompt)])
                )
                # Các turn tiếp theo: assistant (tool_call) + tool (observation)
                for msg in messages_history:
                    role = msg.get("role")
                    if role == "assistant" and msg.get("tool_calls"):
                        fc_parts = []
                        for tc in msg["tool_calls"]:
                            fc_parts.append(
                                types.Part(
                                    function_call=types.FunctionCall(
                                        name=tc["name"],
                                        args=tc.get("arguments", {}) or {},
                                    )
                                )
                            )
                        if fc_parts:
                            contents.append(types.Content(role="model", parts=fc_parts))
                    elif role == "tool":
                        contents.append(
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_function_response(
                                        name=msg.get("name", ""),
                                        response={"result": msg.get("content", "{}")},
                                    )
                                ],
                            )
                        )
            else:
                contents = prompt

            response = client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )

            if response.function_calls:
                call = response.function_calls[0]
                args = dict(call.args) if hasattr(call, 'args') and call.args else {}
                return {
                    "type": "tool_call",
                    "tool_name": call.name,
                    "arguments": args,
                    "thought": f"Gemini quyết định gọi công cụ '{call.name}' với tham số: {json.dumps(args, ensure_ascii=False)}"
                }
            else:
                return {
                    "type": "text",
                    "content": response.text or "",
                    "thought": "Gemini phản hồi trực tiếp bằng văn bản (không cần gọi công cụ)."
                }

        except Exception as e:
            print(f"⚠️ [Gemini API Warning]: Không thể kết nối live API ({str(e)}). Tự động fallback về Mock.")
            return MockOfflineProvider().generate_with_tools(
                prompt, tools_schema, system_prompt, messages_history
            )


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Provider (Native Tool Calling với OpenAI SDK)"""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            return "[OpenAI Error]: Chưa cấu hình OPENAI_API_KEY trong file .env! Đang sử dụng chế độ Mock."
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(model=self.model_name, messages=messages)
            return response.choices[0].message.content or ""
        except Exception as e:
            return f"[OpenAI Exception]: {str(e)}"

    def generate_with_tools(
        self,
        prompt: str,
        tools_schema: List[Dict[str, Any]],
        system_prompt: str = "",
        messages_history: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            print("ℹ️ [OpenAI Provider]: Chưa tìm thấy OPENAI_API_KEY hợp lệ. Tự động chuyển sang Mock Offline.")
            return MockOfflineProvider().generate_with_tools(
                prompt, tools_schema, system_prompt, messages_history
            )

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            tools = []
            for tool in tools_schema:
                if not tool.get("name"):
                    continue
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {})
                    }
                })

            messages: List[Dict[str, Any]] = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # ----- Nạp messages_history (assistant tool_calls + tool results) -----
            if messages_history:
                for msg in messages_history:
                    role = msg.get("role")
                    if role == "assistant" and msg.get("tool_calls"):
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": f"call_{idx}",
                                    "type": "function",
                                    "function": {
                                        "name": tc.get("name", ""),
                                        "arguments": json.dumps(tc.get("arguments", {}) or {}, ensure_ascii=False),
                                    },
                                }
                                for idx, tc in enumerate(msg["tool_calls"])
                            ],
                        })
                    elif role == "tool":
                        # OpenAI yêu cầu tool_call_id khớp với id ở message assistant phía trước
                        messages.append({
                            "role": "tool",
                            "tool_call_id": "call_0",
                            "name": msg.get("name", ""),
                            "content": msg.get("content", ""),
                        })

            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None
            )

            msg = response.choices[0].message
            if msg.tool_calls:
                call = msg.tool_calls[0]
                args = json.loads(call.function.arguments) if call.function.arguments else {}
                return {
                    "type": "tool_call",
                    "tool_name": call.function.name,
                    "arguments": args,
                    "thought": f"OpenAI quyết định gọi công cụ '{call.function.name}' với tham số: {json.dumps(args, ensure_ascii=False)}"
                }
            else:
                return {
                    "type": "text",
                    "content": msg.content or "",
                    "thought": "OpenAI phản hồi trực tiếp bằng văn bản (không cần gọi công cụ)."
                }
        except Exception as e:
            print(f"⚠️ [OpenAI API Warning]: Không thể kết nối live API ({str(e)}). Tự động fallback về Mock.")
            return MockOfflineProvider().generate_with_tools(
                prompt, tools_schema, system_prompt, messages_history
            )


def get_llm_provider() -> BaseLLMProvider:
    """Factory function khởi tạo Provider theo LLM_PROVIDER env variable"""
    provider_type = os.getenv("LLM_PROVIDER", "gemini").lower()
    
    if provider_type == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        if key and key != "your_gemini_api_key_here":
            return GeminiProvider()
        else:
            return MockOfflineProvider()
    elif provider_type == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if key and key != "your_openai_api_key_here":
            return OpenAIProvider()
        else:
            return MockOfflineProvider()
    elif provider_type == "mock":
        return MockOfflineProvider()
    else:
        return MockOfflineProvider()
