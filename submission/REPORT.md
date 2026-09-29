# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Trần Hồng Sơn
- **MSSV:** 2A202602475
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/HongSon507/K4-L3-DAY13-TranHongSon-2A202602475-Monitoring-LLMOps.git
- **Commit SHA cuối:**
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`
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
| Prompt promote / rollback | `evidence/10a-prompt-rollback.png` (promote v2), `evidence/10b-prompt-rollback.png` (rollback v1) |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 | Baseline thiếu fields, enrichment và correlation ID; sau CP1 đạt đủ 4 nhóm kiểm tra |
| `validate_dashboard.py` | HỢP LỆ (6/6 panel) | HỢP LỆ (6/6 panel) | Contract không đổi; dashboard runtime dựng bằng `scripts/build_dashboard.py` |
| `pytest` | 22 passed | 28 passed | Thêm test PII (CCCD, thẻ), child observations và dashboard |
| Số traces hợp lệ | 0 | ≥ 23 (root + retrieval + generation) | Baseline chỉ có root observation, correlation ID `MISSING` |
| Số PII leak | 0 | 0 (log + 23 traces) | Kiểm tra bằng validator và quét trace với 3 chuỗi PII mẫu |
| Latency P95 / TTFT P95 | ~1007 ms / 50 ms | 1586 ms / 50 ms (cửa sổ 60 phút) | P95 cuối gồm cold start khi fetch prompt Langfuse; warm P50 ~152 ms |
| Retrieval success rate | 100% | 100% | Incident challenge làm retrieval chậm chứ không lỗi |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** Trong `CorrelationIdMiddleware` ([`app/middleware.py`](../app/middleware.py)), mỗi request được xóa context cũ bằng `clear_contextvars()`, trích xuất `x-request-id` từ request headers hoặc tự động sinh mới theo định dạng `req-<8-hex>` (`f"req-{uuid.uuid4().hex[:8]}"`). Sau đó gán vào `bind_contextvars(correlation_id=...)` và `request.state.correlation_id`. Middleware trả lại `correlation_id` qua header `x-request-id` và thời gian phản hồi qua header `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** Mỗi log record `service="api"` ghi nhận đầy đủ: `ts` (ISO UTC), `level`, `service`, `event`, `correlation_id`, cùng context metadata: `user_id_hash` (sha256 rút gọn 12 ký tự), `session_id`, `feature`, `model`, và `env`.
- **Cách bảo đảm PII được scrub trước khi ghi:** Đăng ký processor `scrub_event` trong danh sách processors của structlog ([`app/logging_config.py`](../app/logging_config.py)) đứng trước `JsonlFileProcessor` và `JSONRenderer`. Processor này quét đệ quy các trường văn bản và thay thế bằng các token `[REDACTED_<TYPE>]` (email, phone_vn, cccd, credit_card) định nghĩa tại [`app/pii.py`](../app/pii.py).
- **Cách kiểm chứng kết quả:** Chạy `python scripts/validate_logs.py` kiểm tra toàn bộ log thực tế đạt **100/100** điểm (0 missing required fields, 0 missing enrichment, 10/10 correlation IDs duy nhất, 0 PII leak). Bộ unit test [`tests/test_pii.py`](../tests/test_pii.py) và toàn bộ test suite pass (24/24 ở CP1, 28/28 ở commit cuối).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** Key trong `.env` thuộc project `day13-k4-l3a-2A202602475`. Tôi tự chạy `python scripts/load_test.py --concurrency 5` và chạy tuần tự thêm một lượt, rồi truy vấn lại qua API `GET /api/public/v2/observations` (org mới không dùng được API `/traces` cũ): **23 traces trong 10 phút, cả 23 đều có đủ root + retrieval + generation, 0 trace chứa PII mẫu** (email, số điện thoại, số thẻ trong `data/sample_queries.jsonl`).
- **Cấu trúc root/retrieval/generation observations:** [`app/agent.py`](../app/agent.py) dùng decorator `@observe` của Langfuse SDK v4:
  - `lab-agent-run` (`as_type="agent"`, root): `propagate_attributes` gắn `user_id` = sha256 rút gọn, `session_id`, `environment`, tags `[lab, feature, model]` và metadata `feature`, `model`, `correlation_id`; metadata span có `prompt_name/label/version/source`.
  - `retrieval` (`as_type="retriever"`, con của root): input là query đã scrub + cắt ngắn (`summarize_text`), output `doc_count`, metadata `domain_match`.
  - `llm-generation` (`as_type="generation"`, con của root): `model`, `usage_details` (input/output/total), `cost_details` (theo đơn giá 3 / 15 USD mỗi 1M token), `completion_start_time` (để Langfuse hiện TTFT), link tới managed prompt, input/output chỉ là preview đã scrub.
  - Mọi observation đặt `capture_input=False, capture_output=False` nên SDK không tự ghi raw message. Waterfall cho thấy retrieval ~1 ms, generation ~152 ms (TTFT 50 ms), nên LLM là bước chậm khi hệ thống bình thường.
  - Test: [`tests/test_agent_child_observations.py`](../tests/test_agent_child_observations.py).
- **Cách nối trace với log:** Cùng một `correlation_id` (`req-<8-hex>`) xuất hiện trong log `request_received`/`response_sent` và trong metadata của trace. Ví dụ log `req-2e4234fd` ↔ trace `aeab9043a7370ffd88f9c10cc18c09a8`.
  - Ảnh [`07-trace-waterfall`](evidence/07-trace-waterfall.png): trace `c01fea4a9ddd59e9ad08028d87650c97` (`correlation_id=req-dcaed9b9`, tạo khi `production` đang ở v2). Root `lab-agent-run` 0.15 s, con `retrieval` 0.00 s và `llm-generation` 0.15 s, $0.001992, 172 tokens.
  - Ảnh [`08-trace-metadata`](evidence/08-trace-metadata.png): trace `bf42ea4b131419105e3486501250a16f` (`correlation_id=req-8c22dab1`). Metadata có `model`, `feature`, `ttft_ms`, `prompt_name=day13-chat`, `prompt_label=production`, `prompt_version=1`, `prompt_source=langfuse`. Generation: 34 input + 179 output tokens, $0.002787, khớp với log `response_sent` cùng `correlation_id`.
- **Prompt name:** `day13-chat` (text prompt, giữ 3 biến `{{feature}}`, `{{docs}}`, `{{message}}`), tạo bằng [`scripts/prompt_versions.py`](../scripts/prompt_versions.py) `create`.
- **Version/label baseline:** v1, labels `baseline` + `production`: `Feature/Docs/Question`.
- **Version/label candidate:** v2, label `candidate`: thêm dòng "Answer in at most 3 short bullet points, using only the docs above." (tokens_in của cùng input tăng từ 32 lên 49).
- **Trace ID của mỗi version:** Cùng input "Explain why metrics traces and logs work together", session `s-prompt-compare`:
  - baseline (v1): trace `aeab9043a7370ffd88f9c10cc18c09a8`, correlation `req-2e4234fd`;
  - candidate (v2): trace `a4606e47d36846f07a94024d4edbc104`, correlation `req-2d2f296f`.
  - Hai trace đều có `prompt_source=langfuse`, generation được link tới `day13-chat` v1/v2.
- **Cách promote và rollback `production`:**
  - `python scripts/prompt_versions.py promote --version 2` → production trỏ sang v2. Request sau đó: trace `6cbc1bd383da33261630ac3d7589cd78` (`req-932d537e`, metadata `prompt_label=production`, `prompt_version=2`, tokens_in 49);
  - `python scripts/prompt_versions.py promote --version 1` → rollback. Lệnh in trạng thái label trước/sau; `update_prompt(new_labels=["production"])` tự gỡ label khỏi version cũ. Vì app cache prompt 60 s (`cache_ttl_seconds=60`), request ngay sau khi đổi label có thể vẫn dùng version cũ. Thực tế: request đầu tiên sau 65 s (`req-81d35209`, trace `7d75cf4a8197e2f7b2eca13cdd3d1418`) vẫn là v1, vì SDK trả bản cache cũ rồi mới refresh ngầm (stale-while-revalidate); từ request kế tiếp mới là v2.
  - Evidence: [`evidence/10a-prompt-rollback.png`](evidence/10a-prompt-rollback.png) (trạng thái label trước/sau khi promote v2) và [`evidence/10b-prompt-rollback.png`](evidence/10b-prompt-rollback.png) (rollback production về v1).

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

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1` (cohort K4, 5 queries, feature `monitoring`, `latency_threshold_ms: 2000`).
- **Khoảng thời gian điều tra:** ngày 2026-09-29, giờ UTC:
  - baseline: 09:22:20–09:22:26;
  - bật incident (`python scripts/inject_incident.py`): 09:22:37;
  - load `--challenge --concurrency 5`: 09:22:39–09:22:52;
  - tắt incident: 09:23:46; kiểm tra phục hồi ngay sau đó.
  - chạy lại workload challenge lần 2 lúc ~09:54 UTC khi chụp evidence: kết quả giống hệt, ví dụ `req-8c22dab1` → trace `bf42ea4b131419105e3486501250a16f`, `retrieval` 2501 ms / tổng 2654 ms. Incident tái hiện được.
- **Triệu chứng từ metrics:** Panel **Latency** (ms): server-side `latency_ms` P50 tăng từ **152 ms** (baseline warm) lên **2653 ms**, P95/P99 là 2654 ms. Mức này vượt ngưỡng 2000 ms của challenge, cho 5/5 request, tức tăng ~17 lần.
  - Các panel khác không đổi: TTFT P95 giữ **50 ms**, error rate 0%, retrieval success 100%, tokens_out/request và cost/request ở mức baseline, quality 0.84 (baseline 0.88).
  - Vậy sự cố chỉ về latency, không phải lỗi, không phải chi phí. TTFT không đổi nên phần chậm nằm **trước** bước LLM.
  - Phía client còn tệ hơn: load test đo **10.6–13.3 s** mỗi request.
- **Log line và correlation ID liên quan:** Lọc `data/logs.jsonl` từ 09:22:37 đến 09:22:55, thấy 5 cặp `request_received`/`response_sent`, đều thuộc `feature=monitoring`. Log đại diện:

  ```json
  {"ts": "2026-09-29T09:22:47.009365Z", "event": "response_sent", "correlation_id": "req-85961c7d", "feature": "monitoring", "session_id": "k4-l3a-challenge-s01", "latency_ms": 2652, "ttft_ms": 50, "tool_name": "retrieval", "tool_success": true}
  ```

  - Timestamp cho thấy 5 request gửi đồng thời nhưng được xử lý **tuần tự**: `request_received` của request sau (ví dụ 09:22:44.355) chỉ xuất hiện sau `response_sent` của request trước (09:22:44.354).
  - Đây là lý do client chờ tới ~13 s dù mỗi request chỉ tốn ~2.65 s ở server.
- **Trace ID và span gây ảnh hưởng:** Trace `8eac57756f1dc1b0fd7c260d9a687703`, có cùng `correlation_id=req-85961c7d`:
  - `lab-agent-run`: 2653 ms;
  - **`retrieval`: 2501 ms**, level DEFAULT, không có exception;
  - `llm-generation`: 152 ms, TTFT 50 ms.
  - So với trace baseline `0d7e815be42500079be88c4442580ad8` (`req-649a3d14`): retrieval 0 ms, generation 152 ms, tổng 153 ms.
  - 4 trace incident còn lại cho kết quả giống hệt (retrieval 2500–2501 ms): `ad8803cb162e655dd91d7d2b09d80411`, `1a16e8c70c8573d1461c881951f008e1`, `35fa0537fc6b83049daa188a60d89b7e`, `e6e2cb313947117602012ed2ef05772e`.
- **Root cause:** Bước **retrieval (vector store) chậm thêm ~2.5 s mỗi request** (incident `rag_slow`). Ba nguồn bằng chứng cùng chỉ về một chỗ:
  - metric: latency tăng, TTFT không đổi;
  - log: `latency_ms` ≈ 2653, `tool_success=true`, không có lỗi;
  - trace: span `retrieval` chiếm 2501/2653 ms ≈ 94% thời gian request.
  - **Yếu tố khuếch đại:** endpoint `async def chat` trong [`app/main.py`](../app/main.py) gọi `agent.run` đồng bộ (bên trong dùng `time.sleep`/I/O blocking). Việc này chặn event loop của uvicorn nên các request đồng thời phải xếp hàng, và 2.65 s ở server thành 10–13 s ở phía người dùng.
- **Fix action:**
  1. Ngắt nguồn chậm: tắt incident / failover sang replica vector store. Sau khi tắt lúc 09:23:46, cùng workload chỉ còn 470–780 ms ở client.
  2. Đặt timeout cho retrieval (ví dụ 800 ms). Hết timeout thì trả lời bằng fallback không có context thay vì chờ.
  3. Không chặn event loop nữa: chạy `agent.run` qua `starlette.concurrency.run_in_threadpool`, hoặc khai báo endpoint là `def`, để request đồng thời không xếp hàng sau một request chậm.
- **Preventive measure:**
  - Alert `high_latency_p95_breach` ([`docs/alerts.md`](../docs/alerts.md#alert-1)) theo P95.
  - Thêm alert/panel riêng cho duration span `retrieval` (P95 > 500 ms trong 5 m) để khoanh vùng nhanh hơn.
  - Ghi thêm `retrieval_ms` vào log `response_sent` để dashboard tách được retrieval và LLM mà không cần mở trace.
  - Cache kết quả retrieval cho câu hỏi lặp lại.
  - Đo latency ở middleware (`x-response-time-ms`) hoặc ở client, vì `latency_ms` trong agent không thấy thời gian xếp hàng. Trong incident này, server báo 2.65 s trong khi người dùng chờ 13 s.
  - Load test định kỳ với `--concurrency 5` và bật `rag_slow` trong CI để bắt lỗi blocking event loop.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** SLI dùng mẫu số là `request_received` thay vì `response_sent + request_failed`, và alert lỗi dùng `1 − response_sent/request_received`. Lý do: khi worker API chết giữa request, 12 request trả 500/reset mà không kịp ghi `request_failed`. Nếu đếm theo `request_failed`, error rate vẫn là 0% dù người dùng đang gặp lỗi.
  - Quyết định thứ hai: dashboard được sinh từ chính `config/dashboard.yaml` (panel, đơn vị, threshold) bằng script không cần thêm dependency. Vì vậy contract và dashboard runtime không thể lệch nhau, và có test kiểm tra.
- **Một lỗi/blocker đã gặp:** Sau khi thêm child observations, API chạy bằng `uvicorn --reload` trả HTTP 500 cho mọi `/chat` và làm đứt kết nối của load test. Log có `request_received` nhưng không có `request_failed`.
  - Blocker phụ: org Langfuse mới không gọi được `GET /api/public/traces` (HTTP 410 `LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION`).
- **Cách tìm nguyên nhân và xử lý:**
  - Chạy cùng request bằng `TestClient` in-process và trên instance uvicorn riêng: đều trả 200. Như vậy code không lỗi, lỗi nằm ở process `--reload`: worker bị restart khi file thay đổi trong lúc có traffic.
  - Xử lý: chạy API không `--reload` khi đo và làm challenge; thêm `--base-url` cho `load_test.py` để test instance riêng.
  - Với Langfuse: chuyển sang `GET /api/public/v2/observations` với tham số `fields` để kiểm tra cây observation, metadata và PII của trace bằng script.
- **Cách hiểu luồng Metrics → Logs → Traces:**
  - Metrics trả lời *có vấn đề không và lớn cỡ nào*: panel Latency P50 tăng từ 152 lên 2653 ms, trong khi TTFT/error/cost không đổi, nên vấn đề nằm trước LLM.
  - Logs trả lời *request nào, lúc nào, thuộc feature nào*: lọc khoảng 09:22:37–09:22:55 ra 5 request `monitoring`, chọn `req-85961c7d`. Timestamp còn cho thấy các request bị xử lý tuần tự.
  - Traces trả lời *chậm ở đâu bên trong request*: cùng `correlation_id`, span `retrieval` chiếm 2501/2653 ms.
  - `correlation_id` là khóa nối log với trace. Chỉ kết luận root cause khi cả ba nguồn cùng chỉ về một chỗ.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
  - Prompt là "code" thay đổi hành vi mà không cần deploy. Mỗi trace ghi `prompt_name/label/version` nên biết chính xác request nào dùng version nào. Khi v2 gây vấn đề chỉ cần chuyển label `production` về v1 (rollback trong vài giây, không redeploy). Cần nhớ cache của SDK làm thay đổi có độ trễ.
  - Token/cost: v2 làm tokens_in tăng 32 → 49 (~53%) cho cùng input. Thay đổi prompt nhỏ cũng ảnh hưởng chi phí, nên cần panel tokens/cost và alert cost burn.
  - SLO/error budget: biến mục tiêu độ tin cậy thành con số để quyết định khi nào page, khi nào dừng thay đổi prompt/model.
- **Điều quan trọng nhất đã học:** Số liệu đo ở một điểm có thể che mất trải nghiệm thật của người dùng. Trong challenge, `latency_ms` của agent là 2.65 s (dashboard vẫn OK so với SLO 3 s), nhưng client chờ 10–13 s vì endpoint async bị chặn bởi code đồng bộ khiến request xếp hàng. Cần đo ở nhiều lớp (agent, middleware, client) và luôn kiểm chứng bằng log timestamp và trace.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**
  - Chưa áp dụng fix `run_in_threadpool` cho endpoint `/chat`; mới dừng ở đề xuất trong mục 7.
  - Dashboard là file HTML tĩnh dựng lại theo chu kỳ, không phải hệ thống giám sát thời gian thực. Alert mới được định nghĩa trong YAML, chưa nối với Slack thật.
  - `latency_ms` chưa tách riêng `retrieval_ms`, nên dashboard phải dựa vào trace để khoanh vùng span.
  - Fake LLM làm quality proxy gần như hằng số, chưa phản ánh chất lượng câu trả lời thật.

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace (`req-85961c7d` ↔ trace `8eac57756f1dc1b0fd7c260d9a687703`).
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README (`pytest` 28 passed, `validate_logs` 100/100, `validate_dashboard` 6/6).
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
