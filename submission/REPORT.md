# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Trần Hồng Sơn
- **MSSV:** 2A202602475
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/HongSon507/K4-L3-DAY13-TranHongSon-2A202602475-Monitoring-LLMOps.git
- **Commit SHA cuối:**
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602475`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 | Thiếu fields, enrichment và correlation ID (chưa làm CP1) |
| `validate_dashboard.py` | HỢP LỆ (6/6 panel) | HỢP LỆ (6/6 panel) | Cấu hình dashboard đầy đủ theo contract |
| `pytest` | 22 passed (100%) | 28 passed | Test suite ban đầu pass 22/22 tests |
| Số traces hợp lệ | 0 | 23 (root + retrieval + generation) | Correlation ID bị MISSING, chưa tạo trace hoàn chỉnh |
| Số PII leak | 0 | 0 (log + 23 traces) | Không phát hiện PII leak trong sample log ban đầu |
| Latency P95 / TTFT P95 | ~1007 ms / 50 ms | 1586 ms / 50 ms (cửa sổ 60 phút, gồm cold start) | Đo từ 10 sample requests ban đầu (P95 server latency ~1007ms, TTFT 50ms) |
| Retrieval success rate | 100% | 100% | 10/10 lượt gọi retrieval tool thành công |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** Trong `CorrelationIdMiddleware` ([`app/middleware.py`](file:///d:/VINUNI/K4-L3-DAY13-TranHongSon-2A202602475-Monitoring-LLMOps.git/app/middleware.py)), mỗi request được xóa context cũ bằng `clear_contextvars()`, trích xuất `x-request-id` từ request headers hoặc tự động sinh mới theo định dạng `req-<8-hex>` (`f"req-{uuid.uuid4().hex[:8]}"`). Sau đó gán vào `bind_contextvars(correlation_id=...)` và `request.state.correlation_id`. Middleware trả lại `correlation_id` qua header `x-request-id` và thời gian phản hồi qua header `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** Mỗi log record `service="api"` ghi nhận đầy đủ: `ts` (ISO UTC), `level`, `service`, `event`, `correlation_id`, cùng context metadata: `user_id_hash` (sha256 rút gọn 12 ký tự), `session_id`, `feature`, `model`, và `env`.
- **Cách bảo đảm PII được scrub trước khi ghi:** Đăng ký processor `scrub_event` trong danh sách processors của structlog ([`app/logging_config.py`](file:///d:/VINUNI/K4-L3-DAY13-TranHongSon-2A202602475-Monitoring-LLMOps.git/app/logging_config.py)) đứng trước `JsonlFileProcessor` và `JSONRenderer`. Processor này quét đệ quy các trường văn bản và thay thế bằng các token `[REDACTED_<TYPE>]` (email, phone_vn, cccd, credit_card) định nghĩa tại [`app/pii.py`](file:///d:/VINUNI/K4-L3-DAY13-TranHongSon-2A202602475-Monitoring-LLMOps.git/app/pii.py).
- **Cách kiểm chứng kết quả:** Chạy `python scripts/validate_logs.py` kiểm tra toàn bộ log thực tế đạt **100/100** điểm (0 missing required fields, 0 missing enrichment, 10/10 correlation IDs duy nhất, 0 PII leak). Bộ unit test [`tests/test_pii.py`](file:///d:/VINUNI/K4-L3-DAY13-TranHongSon-2A202602475-Monitoring-LLMOps.git/tests/test_pii.py) và toàn bộ test suite pass 24/24.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** Key trong `.env` thuộc project `day13-k4-l3a-2A202602475`. Tôi tự chạy `python scripts/load_test.py --concurrency 5` và chạy tuần tự thêm một lượt, rồi truy vấn lại qua API `GET /api/public/v2/observations` (org mới không dùng được API `/traces` cũ): **23 traces trong 10 phút, cả 23 đều có đủ root + retrieval + generation, 0 trace chứa PII mẫu** (email, số điện thoại, số thẻ trong `data/sample_queries.jsonl`).
- **Cấu trúc root/retrieval/generation observations:** [`app/agent.py`](../app/agent.py) dùng decorator `@observe` của Langfuse SDK v4:
  - `lab-agent-run` (`as_type="agent"`, root): `propagate_attributes` gắn `user_id` = sha256 rút gọn, `session_id`, `environment`, tags `[lab, feature, model]` và metadata `feature`, `model`, `correlation_id`; metadata span có `prompt_name/label/version/source`.
  - `retrieval` (`as_type="retriever"`, con của root): input là query đã scrub + cắt ngắn (`summarize_text`), output `doc_count`, metadata `domain_match`.
  - `llm-generation` (`as_type="generation"`, con của root): `model`, `usage_details` (input/output/total), `cost_details` (theo đơn giá 3 / 15 USD mỗi 1M token), `completion_start_time` (để Langfuse hiện TTFT), link tới managed prompt, input/output chỉ là preview đã scrub.
  - Mọi observation đặt `capture_input=False, capture_output=False` nên SDK không tự ghi raw message. Waterfall cho thấy retrieval ~1 ms, generation ~152 ms (TTFT 50 ms), nên LLM là bước chậm khi hệ thống bình thường.
  - Test: [`tests/test_agent_child_observations.py`](../tests/test_agent_child_observations.py).
- **Cách nối trace với log:** Cùng một `correlation_id` (`req-<8-hex>`) xuất hiện trong log `request_received`/`response_sent` và trong metadata của trace. Ví dụ log `req-2e4234fd` ↔ trace `aeab9043a7370ffd88f9c10cc18c09a8`.
- **Prompt name:** `day13-chat` (text prompt, giữ 3 biến `{{feature}}`, `{{docs}}`, `{{message}}`), tạo bằng [`scripts/prompt_versions.py`](../scripts/prompt_versions.py) `create`.
- **Version/label baseline:** v1, labels `baseline` + `production`: `Feature/Docs/Question`.
- **Version/label candidate:** v2, label `candidate`: thêm dòng "Answer in at most 3 short bullet points, using only the docs above." (tokens_in của cùng input tăng từ 32 lên 49).
- **Trace ID của mỗi version:** Cùng input "Explain why metrics traces and logs work together", session `s-prompt-compare`:
  - baseline (v1): trace `aeab9043a7370ffd88f9c10cc18c09a8`, correlation `req-2e4234fd`;
  - candidate (v2): trace `a4606e47d36846f07a94024d4edbc104`, correlation `req-2d2f296f`.
  - Hai trace đều có `prompt_source=langfuse`, generation được link tới `day13-chat` v1/v2.
- **Cách promote và rollback `production`:**
  - `python scripts/prompt_versions.py promote --version 2` → production trỏ sang v2, chạy lại một request (trace: _TODO_);
  - `python scripts/prompt_versions.py promote --version 1` → rollback. Lệnh in trạng thái label trước/sau; `update_prompt(new_labels=["production"])` tự gỡ label khỏi version cũ. Vì app cache prompt 60 s (`cache_ttl_seconds=60`), request ngay sau khi đổi label có thể vẫn dùng version cũ tối đa 60 s.
  - Evidence: `evidence/10-prompt-rollback.png` (_TODO_).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** [`scripts/build_dashboard.py`](../scripts/build_dashboard.py) đọc [`config/dashboard.yaml`](../config/dashboard.yaml) và `data/logs.jsonl`, phần tính toán nằm ở [`app/dashboard_data.py`](../app/dashboard_data.py), rồi xuất `data/dashboard.html` (HTML + SVG, tự refresh 30 s, `--watch` để dựng lại liên tục).
  - Sáu panel: Latency P50/P95/P99 + TTFT P95 (ms), Traffic (req/phút), Error rate + breakdown + retrieval success (%), Cost cộng dồn (USD), Input/output tokens, Quality proxy (0–1).
  - Time range 60 phút tính tới event mới nhất. Mỗi panel có đường threshold/SLO lấy trực tiếp từ contract và badge OK/BREACH.
  - Số liệu lúc dựng: P50 153 / P95 1586 / P99 1593 ms, TTFT P95 50 ms, error rate 0%, retrieval success 100%, cost $0.0657, tokens 1,095 in / 4,161 out, quality mean 0.875.
  - Test: [`tests/test_dashboard_data.py`](../tests/test_dashboard_data.py).
- **SLO và lý do chọn:** Xem [`config/slo.yaml`](../config/slo.yaml). Giữ 99.5% request `response_sent` với `latency_ms <= 3000` trong 28 ngày.
  - Baseline warm: P95 ~450 ms; cold start phải fetch prompt nên lên ~1.6 s. Như vậy 3000 ms chừa khoảng dư ~2x mà vẫn bắt được `rag_slow` (retrieval +2.5 s).
  - Chọn 99.5% vì app phụ thuộc Langfuse và vector store, cả hai không có SLA.
  - Mẫu số là `request_received`: khi uvicorn `--reload` restart giữa lúc có traffic, 12 request trả 500/reset mà không kịp ghi `request_failed`. Đếm theo `request_failed` sẽ bỏ sót, còn SLI theo `request_received` thì không.
- **Cách tính error budget:** `allowed_bad = total × (1 − 0.995)`.
  - Giả định 10 req/phút → 403,200 req/28 ngày → 2,016 bad requests, tương đương ~3.4 giờ hỏng hoàn toàn.
  - Burn rate = (bad/total) / 0.005. Burn ≥ 14.4 trong 1 h (tiêu ~2% budget/giờ) → page; ≥ 6 trong 6 h → ticket; còn < 25% budget → dừng đổi prompt/model không khẩn cấp.
- **Ba alert và runbook tương ứng:** [`config/alert_rules.yaml`](../config/alert_rules.yaml), runbook tại [`docs/alerts.md`](../docs/alerts.md):
  1. `high_latency_p95_breach`: P95 > 3000 ms trong 5 m, P2, `#day13-llmops-alerts`, ứng với `rag_slow`;
  2. `high_error_rate`: tỷ lệ request không có `response_sent` > 2% trong 5 m, P1, `#day13-llmops-alerts`, ứng với `tool_fail`/crash;
  3. `cost_burn_above_daily_budget`: cost 1 h > 0.104 USD trong 15 m, P3, `#day13-llmops-cost`, ứng với `cost_spike`.
  - Owner của cả ba là `tranhongson-oncall`; mỗi runbook có 3 bước kiểm tra Metrics → Logs → Traces và mitigation.

## 7. Điều tra challenge

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
