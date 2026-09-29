# Alert và Runbook

Mỗi alert dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ. Định nghĩa máy đọc được nằm tại [`config/alert_rules.yaml`](../config/alert_rules.yaml); SLO và error budget tại [`config/slo.yaml`](../config/slo.yaml). Dashboard kiểm tra: `python scripts/build_dashboard.py` rồi mở `data/dashboard.html`.

Quy ước chung khi nhận alert:

1. Xác nhận trên dashboard (panel tương ứng, time range 60 phút) rằng triệu chứng có thật, không phải một điểm lẻ.
2. Lọc `data/logs.jsonl` trong khoảng sự cố, lấy `correlation_id` bất thường.
3. Mở trace có cùng `correlation_id` trong project Langfuse `day13-k4-l3a-2A202602475`, xem waterfall `lab-agent-run → retrieval / llm-generation`.

Lệnh lọc log hữu ích (PowerShell):

```powershell
Get-Content data/logs.jsonl | ConvertFrom-Json | Where-Object { $_.event -eq "response_sent" -and $_.latency_ms -gt 3000 } | Select-Object ts, correlation_id, feature, latency_ms
```

## Alert 1

- Tên: `high_latency_p95_breach`
- Severity: P2-high
- Duration: 5m
- Kênh thông báo: Slack `#day13-llmops-alerts`
- SLI/SLO liên quan: `fast_successful_requests` — 99.5% request có `response_sent` với `latency_ms <= 3000` trong 28 ngày.
- Điều kiện và thời gian duy trì: P95 của `latency_ms` (event `response_sent`) trong cửa sổ trượt 5 phút > 3000 ms, duy trì liên tục 5 phút. Khi alert bắn, gần như mọi request chậm đều là "bad event" nên budget cháy ở burn rate ≥ 14.4.
- Ảnh hưởng tới người dùng: câu trả lời chậm hơn 3 giây; với chat, người dùng thấy UI treo và có thể gửi lại câu hỏi (tăng tải).
- Ba bước kiểm tra đầu tiên:
  1. Panel Latency: P95 tăng nhưng TTFT P95 giữ nguyên (~50 ms) → phần chậm nằm trước LLM (retrieval/prompt fetch); TTFT cũng tăng → phía LLM.
  2. Lọc log `response_sent` có `latency_ms > 3000`, xem có dồn vào một `feature` hay không, lấy 1–2 `correlation_id`.
  3. Mở trace tương ứng: so sánh duration của span `retrieval` với `llm-generation`; nếu root dài mà hai child ngắn → xem `prompt_source` (fetch prompt timeout sẽ là `local-fallback`).
- Mitigation tạm thời: nếu retrieval chậm (ví dụ incident `rag_slow`) → tắt nguồn chậm / bật cache kết quả retrieval, giảm timeout retrieval và trả lời fallback; nếu prompt fetch chậm → tăng `cache_ttl_seconds`; nếu LLM chậm → chuyển sang model nhỏ hơn. Sau khi hết sự cố: `python scripts/inject_incident.py --scenario rag_slow --disable` (khi luyện tập).
- Owner: tranhongson-oncall

## Alert 2

- Tên: `high_error_rate`
- Severity: P1-critical
- Duration: 5m
- Kênh thông báo: Slack `#day13-llmops-alerts`
- SLI/SLO liên quan: `fast_successful_requests` và guardrail `error_rate_pct_max: 2`.
- Điều kiện và thời gian duy trì: `(1 - response_sent / request_received) * 100 > 2` trong cửa sổ 5 phút, duy trì 5 phút. Dùng hiệu `request_received − response_sent` thay vì đếm `request_failed` để bắt cả request bị worker crash/timeout không kịp ghi log lỗi (đã gặp khi uvicorn `--reload` khởi động lại giữa lúc có traffic).
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 hoặc mất kết nối, không có câu trả lời.
- Ba bước kiểm tra đầu tiên:
  1. Panel Errors: xem error rate, breakdown `error_type` và retrieval success. Retrieval success giảm (< 90%) → lỗi ở vector store.
  2. Lọc log `request_failed` trong khoảng sự cố, đọc `error_type`, `tool_name`, `payload.detail` (ví dụ `RuntimeError: Vector store timeout`) và lấy `correlation_id`. Nếu không có `request_failed` nhưng vẫn thiếu `response_sent` → kiểm tra process API (crash/restart).
  3. Mở trace có cùng `correlation_id`: span `retrieval` có level ERROR hay exception nằm ở `llm-generation`.
- Mitigation tạm thời: với lỗi retrieval (incident `tool_fail`) → bắt exception và trả lời không kèm context (degrade gracefully) thay vì 500, hoặc chuyển sang replica vector store khác; với crash process → restart API không dùng `--reload`; rollback commit/prompt gần nhất nếu lỗi bắt đầu ngay sau deploy (`python scripts/prompt_versions.py promote --version <bản trước>`).
- Owner: tranhongson-oncall

## Alert 3

- Tên: `cost_burn_above_daily_budget`
- Severity: P3-warning
- Duration: 15m
- Kênh thông báo: Slack `#day13-llmops-cost`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5` (tương đương 0.104 USD/giờ nếu chi đều).
- Điều kiện và thời gian duy trì: tổng `cost_usd` của `response_sent` trong 1 giờ gần nhất > 0.104 USD, duy trì 15 phút. Duration dài hơn hai alert trên vì chi phí không gây hại tức thời, tránh bắn do một burst ngắn.
- Ảnh hưởng tới người dùng: không ảnh hưởng trực tiếp tới trải nghiệm, nhưng nếu kéo dài sẽ vượt ngân sách ngày và có thể buộc phải throttle/tắt tính năng.
- Ba bước kiểm tra đầu tiên:
  1. Panel Cost và Tokens: cost tăng do traffic tăng (panel Traffic tăng theo) hay do chi phí/request tăng (tokens_out/request tăng — dấu hiệu incident `cost_spike`).
  2. Lọc log `response_sent` có `tokens_out` lớn bất thường (> 2x baseline ~130), nhóm theo `feature`, `model`, lấy `correlation_id`.
  3. Mở trace: xem `usage_details` và `cost_details` của `llm-generation`, cùng `prompt_version` — một prompt version mới có thể làm output dài hơn.
- Mitigation tạm thời: giới hạn `max_tokens` output, rollback prompt về version trước nếu cost tăng sau khi đổi label `production`, chuyển feature `summary` sang model rẻ hơn, bật rate limit theo `user_id_hash` nếu do một vài user.
- Owner: tranhongson-oncall
