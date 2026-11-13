# Báo cáo cá nhân — Day 6

Nguyễn Hoàng Huy · 2A202603410 · L3A · lần chạy cuối `2026-11-13T10:43:46Z` ([run_config.json](../../results/run_config.json))

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** Corpus gồm ba tài liệu "What's New In Python" bản 3.11, 3.12 và 3.13 trên docs.python.org. Bản chụp được tải về `starter/data/raw/` lúc `2026-11-13T10:05:08Z`. Đây là các bản build tài liệu 3.11.18, 3.12.16 và 3.13.18, cả ba ghi "Last updated Oct 26, 2026". Giấy phép là PSF License Version 2 cho phần chữ, còn code ví dụ có thêm Zero Clause BSD; thông tin này lấy từ footer từng trang. HTML không có trang vật lý, nên theo GUIDE mỗi "trang" là một **đơn vị nội dung**: gộp nguyên các mục lá (h1–h4) theo đúng thứ tự tài liệu cho tới khi đạt **≥1.500 ký tự đã chuẩn hóa**; phần đuôi ngắn thì nhập vào đơn vị trước đó. Kết quả có **100 đơn vị**: 3.11 có 31, 3.12 có 31, 3.13 có 38. Đơn vị ngắn nhất 1.504 ký tự, dài nhất 10.168 ký tự, tổng 288.673 ký tự. Không có đơn vị nào dưới 1.500 ký tự và không nhân bản nội dung. ID, ranh giới (heading đầu tiên, các section) và số ký tự của từng đơn vị nằm trong [data/manifest.json](../../data/manifest.json); text đã chuẩn hóa của từng đơn vị nằm trong [data/pages.jsonl](../../data/pages.jsonl).
- **Chuẩn hóa, lỗi và giới hạn:** Dùng BeautifulSoup để duyệt `div.body`, xuất heading, `p`, `pre`, `li`, `dt/dd` và từng hàng bảng (`|`). Bỏ ký tự `¶` của headerlink. Chuẩn hóa Unicode NFKC, bỏ ký tự zero-width, gộp khoảng trắng trong từng dòng, nhưng giữ dòng trống giữa các đoạn và giữ xuống dòng trong code. Log ở [ingestion_log.json](../../results/ingestion_log.json): 2.507 block, 0 block rỗng, 0 đơn vị ngắn, không có lỗi. Giới hạn: (1) Các mục "Notable changes in 3.x.y" (os.path, tarfile, ssl) có nội dung giống hệt nhau giữa ba tài liệu. Đây là nội dung thật của từng tài liệu nên mình không khử trùng, nhưng khi truy xuất không có filter thì không phân biệt được. (2) `source` là `og:url` lấy từ file. Với 3.12 và 3.13 đó là đường dẫn `/3/...`, sau này sẽ trỏ tới bản docs mới hơn; phiên bản snapshot chính xác được ghi riêng trong manifest. (3) Mất định dạng inline như code và link, chỉ giữ text.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:** Model `BAAI/bge-small-en-v1.5`, revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, chạy local bằng sentence-transformers 6.3.0 trên CPU (torch 2.15.0+cpu). Vector 384 chiều, đã chuẩn hóa L2, độ dài tối đa 512 token. Document được encode nguyên văn; query thêm instruction của model card: `"Represent this sentence for searching relevant passages: "`. Model được cache ở `D:\VinAI\.cache\huggingface` qua biến `HF_HOME`. Vector store là PostgreSQL 16.16 + pgvector 0.8.7 (Docker image `pgvector/pgvector:0.8.7-pg16`), bảng `chunks`, khóa chính `(strategy, chunk_id)`. Metric cosine (`<=>`), tìm kiếm **exact** (không dùng ANN index), filter là `WHERE version = %s` có tham số hóa. Lệnh chạy: `cd starter && python -m src.run` (xem [README](../../README.md)). Chi phí **0 USD** vì không gọi API.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:** Mỗi chunk có `document_id` (text), `source` (URL), `page` (số nguyên, thứ tự đơn vị trong tài liệu), và thêm `char_start`/`char_end` để truy vết tới ký tự. Trường lọc là **`version`** (text `3.11`/`3.12`/`3.13`), đọc từ `og:title` của từng file chứ không tự đoán. Ba tài liệu mô tả cùng các module (math, tempfile, sqlite3, …) theo từng phiên bản, nên version là trường phân biệt phạm vi rõ nhất. Ngoài ra có `section` (h2) và `subsection` (h3), tính từ heading đang có hiệu lực tại `char_start`, dùng để truy vết và ghép breadcrumb.

## Cấu hình và benchmark
- **A / B / C:**
  - **A:** `fixed_size`, cửa sổ 800 ký tự, overlap 100, cắt trong phạm vi từng đơn vị, không lọc. Tạo ra 453 chunk.
  - **B:** `by_paragraph`, gom đoạn cho tới tối đa 1.200 ký tự phần thân. Chunk **không vượt qua heading**; đoạn quá dài được cắt ở cuối câu hoặc cuối dòng. Mỗi chunk mở đầu bằng breadcrumb `Python 3.12 > Improved Modules > sqlite3`. Không lọc. Tạo ra 425 chunk.
  - **C:** dùng **chính index B**, cùng chunk và cùng vector; chỉ thêm `WHERE version = …` khi câu hỏi mang filter. Khác biệt duy nhất giữa B và C là filter lúc truy vấn.
  - Ba cấu hình dùng cùng corpus, cùng model, cùng store và cùng 23 câu hỏi. Lưu ý A–B thay đổi đồng thời hai thứ thuộc cách chunk: ranh giới và breadcrumb. Bài này không tách được đóng góp riêng của từng yếu tố (xem phần Hạn chế).
- **≥20 câu:** [benchmark/questions.json](../../benchmark/questions.json) có 23 câu: **18 dev / 5 test**. Theo loại: 7 trực tiếp, 6 diễn đạt lại, 5 điều kiện/ngoại lệ, 5 metadata. **5 câu có filter** `version`: d15, d16, d17 ở dev; t01, t02 ở test. Tập được chia theo chủ đề trước khi chạy, và các chủ đề test (ngày phát hành, `tempfile.mkdtemp`, free-threading, zero-cost exceptions, `itertools.batched`) không xuất hiện ở dev. Nguy cơ rò rỉ: t01 và d15 đều hỏi phần đầu trang 1; t02, t05 có dạng giống d16, d17. Có 7 câu ghi thêm nguồn bằng chứng thay thế (tổng 30 phương án gold). Trước khi truy xuất, `load_benchmark()` kiểm tra tự động rằng từng `evidence_quote` nằm trong text đã chuẩn hóa của đúng đơn vị gold; kết quả 30/30 ([benchmark_verification.json](../../results/benchmark_verification.json)). Câu hỏi viết bằng tiếng Anh cho khớp ngôn ngữ corpus và model.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test** (ghi trong `selection_rule` của benchmark): ưu tiên dev Evidence Hit@3 cao nhất; nếu hòa thì xét dev Hit@1; sau đó đến coherence trung bình; cuối cùng là số chunk và thời gian ingest.

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 13/18 | 15/18 | 453 | ingest 39,3 s (embed 38,2 s, upsert 0,3 s); query 25,2 ms | 0 USD |
| A | test | 3/5 | 5/5 | 453 | như trên | 0 USD |
| B | dev | 16/18 | 18/18 | 425 | ingest 30,3 s (embed 29,3 s, upsert 0,2 s); query 24,3 ms | 0 USD |
| B | test | 4/5 | 4/5 | 425 | như trên | 0 USD |
| C | dev | 17/18 | 18/18 | 425 (index B) | không ingest thêm; query 25,8 ms | 0 USD |
| C | test | 4/5 | 5/5 | 425 (index B) | như trên | 0 USD |

Thời gian lấy từ lần chạy cuối trên CPU. Ba lần chạy trên cùng máy cho embed A lần lượt 18,8 / 41,2 / 38,2 s và B lần lượt 17,2 / 37,8 / 29,3 s, nên thời gian dao động khoảng 2 lần theo tải máy; Hit@k thì giống hệt nhau ở cả ba lần. Thống kê chunk ([chunk_stats.json](../../results/chunk_stats.json)):
- **A:** 93.799 token, trung vị 800 ký tự, 16 chunk dưới 200 ký tự.
- **B:** 86.515 token, trung vị 713 ký tự, 39 chunk dưới 200 ký tự, có **1 chunk dài 536 token** (vượt 512 nên phần đuôi bị model cắt).

Kiểm tra nạp lại ([reingest_check.json](../../results/reingest_check.json)):
- Upsert lần hai cùng nội dung: A giữ 453 → 453, B giữ 425 → 425, không xóa gì.
- Mô phỏng tài liệu bị sửa (3 chunk rồi còn 2): 1 chunk cũ bị xóa, còn đúng 2.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,8 (n=10; nhãn 0:2, 1:8, 2:0) | 10/15 | test 0/2 · dev 0/3 | 0 / 1 / 4 → 1,8 |
| B | 2,0 (n=10) | 15/15 | test 0/2 · dev 1/3 | 1 / 0 / 4 → 1,6 |
| C | 2,0 (n=10; cùng chunk với B) | 15/15 | test 2/2 · dev 3/3 | 0 / 0 / 5 → 2,0 |

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- Trace top-3 đầy đủ (câu hỏi, filter, chunk_id, text, score, metadata, cờ hit theo từng hạng) nằm ở [results/traces.jsonl](../../results/traces.jsonl), tổng 69 dòng. Bảng số liệu ở [metrics.md](../../results/metrics.md) và [metrics.json](../../results/metrics.json).
- **Coherence** ([labels_coherence.csv](../../results/labels_coherence.csv)): 10 vị trí được chốt bằng quy tắc trước khi xem điểm. Lấy 10 đơn vị cách đều trong danh sách 100 đơn vị đã sắp xếp; vị trí là đoạn không phải heading cắt qua điểm giữa của đơn vị. Với mỗi chiến lược, chấm chunk đầu tiên chứa vị trí đó ([template](../../results/audit_coherence_template.csv)).
- **Metadata** ([labels_metadata.csv](../../results/labels_metadata.csv)): kiểm 5 câu test × top-3 cho mỗi chiến lược. Script đối chiếu `text == source[char_start:char_end]`, URL, `version` và heading tại `char_start`; người chấm duyệt thêm xem `section` có bao trọn nội dung chunk không. A có 5/15 chunk vắt qua nhiều mục (ví dụ `A:whatsnew-3.12:p009:c000` chứa itertools, math và os nhưng `section` chỉ ghi itertools), nên bị tính là không đủ.
- **Grounding** ([labels_grounding.csv](../../results/labels_grounding.csv)): chấm top-3 của 5 câu test. Quy tắc: 2 = có chunk chứa đủ bằng chứng kèm điều kiện và không có chunk ngoài phạm vi mâu thuẫn; 1 = có bằng chứng nhưng thiếu điều kiện hoặc lẫn chunk ngoài phạm vi mâu thuẫn; 0 = không có bằng chứng.

## Phân tích và kết luận
- **So sánh A–B và B–C; ví dụ sai:**
  - **A–B (chỉ đổi cách chunk):**
    - Dev Hit@1 tăng 13 → 16, Hit@3 tăng 15 → 18.
    - Coherence tăng 0,8 → 2,0, và metadata đủ và đúng tăng 10/15 → 15/15.
    - Tài nguyên tương đương: 425 so với 453 chunk, ít hơn 7,8% token; thời gian embed chênh nhau ít hơn mức dao động giữa các lần chạy.
    - Riêng test thì B kém hơn A: Hit@3 4/5 so với 5/5, grounding 1,6 so với 1,8. Cả hai khác biệt đều do một câu t01.
  - **B–C (chỉ thêm filter):** tài nguyên không đổi.
    - Dev Hit@1 tăng 16 → 17 (câu d17).
    - Test Hit@3 tăng 4 → 5 (câu t01).
    - Tỷ lệ tuân thủ filter tăng từ 1/3 dev và 0/2 test lên 3/3 và 2/2.
    - Grounding tăng 1,6 → 2,0.
  - **Ví dụ sai 1 — t01** (test, gold `whatsnew-3.13` p1, filter version=3.13): B không lọc trả về r1 = `B:whatsnew-3.13:p001:c001`, là phần Summary của 3.13 nhưng không có ngày phát hành; r2 và r3 lại là ngày phát hành của 3.12 và 3.11. Như vậy B trượt, grounding 0, và còn dễ gây trả lời sai. A trúng ở r2 vì cửa sổ 800 ký tự tình cờ chứa cả đoạn mở đầu lẫn Summary. C lọc 3.13 nên trúng ở r2 (`B:whatsnew-3.13:p001:c000`). Hit@1 vẫn trượt vì B tách đoạn mở đầu khỏi Summary, và Summary được xếp cao hơn.
  - **Ví dụ sai 2 — d17** (dev, gold `whatsnew-3.11` p11 math, filter 3.11):
    - A: bằng chứng `exp2` + `cbrt` bị chia qua hai cửa sổ `…p011:c000` và `…c001`; r3 chỉ chứa nửa `cbrt`, nên trượt.
    - B: chunk đúng chỉ đứng r3, sau phần math của 3.13 (fma) và 3.12 (sumprod).
    - C: lọc 3.11 nên chunk đúng lên r1.
  - **Ví dụ sai 3 — d10** (dev, `whatsnew-3.12` p6): r1 của A đúng section nhưng cửa sổ bắt đầu giữa từ ("ping.override() has been added…"), làm mất phần đầu của evidence, nên không tính hit. Đây là lỗi evidence bị tách qua hai chunk, đúng như GUIDE yêu cầu ghi lại.
  - **Ví dụ sai 4 — d18:** cả ba cấu hình chỉ trúng ở r3 (`B:whatsnew-3.13:p006:c000`). "Build Changes" của 3.11 (WebAssembly ở tier 3) và "Faster CPython > About" xếp cao hơn, vì các từ "tier", "platform" và "CPython" lấn át chữ "mobile".
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** Chọn **C** theo quy tắc đã chốt trước: dev Hit@3 hòa giữa B và C (18/18), dev Hit@1 của C cao hơn (17 > 16). Kết quả test 4/5 Hit@1 và 5/5 Hit@3 không mâu thuẫn với lựa chọn này, nhưng N=5, nên một câu tương đương 20 điểm phần trăm; không thể kết luận đây là chiến lược tốt nhất nói chung. Các đánh đổi:
  - Chunking theo heading làm tăng số chunk rất ngắn (39 chunk dưới 200 ký tự, ví dụ mục `uuid` chỉ một câu) và có một chunk vượt 512 token.
  - Breadcrumb chứa chữ "Python 3.x" nên giúp phần nào ngay cả khi không lọc, nhưng không đủ cho câu hỏi kiểu "this version" (t01).
  - Filter chỉ có ích khi ngữ cảnh người dùng cho biết phiên bản. Câu không có filter thì C hoạt động giống hệt B. Nếu ngữ cảnh đưa sai version, C sẽ loại bỏ luôn bằng chứng đúng.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - Corpus chỉ có ba tài liệu cùng cấu trúc và bằng tiếng Anh; "trang" là đơn vị nhân tạo nên `gold_page` khá thô.
  - Câu hỏi, evidence và nhãn thủ công do AI soạn, có nguy cơ hợp gu với chính chiến lược B/C do cùng người thiết kế.
  - Hit dựa trên việc chunk chứa nguyên văn evidence; bằng chứng diễn đạt khác sẽ bị tính trượt. Mình đã đọc lại các câu trượt (d10, d17, t01) và chúng đều là trượt thật, không có trường hợp nào cần người chấm sửa.
  - Thời gian chỉ đo trên CPU, không lặp có kiểm soát, và dao động khoảng 2 lần giữa ba lần chạy; chi phí bằng 0 vì chạy local.
  - Không tách được tác động của breadcrumb so với ranh giới đoạn trong so sánh A–B.
- **Nếu làm lại hoặc mở rộng:**
  - Thêm cấu hình B không có breadcrumb để tách hai yếu tố.
  - Thử hybrid BM25 + dense cho các truy vấn có định danh như `tempfile.mkdtemp` hay `PYTHON_BASIC_REPL`, chọn trọng số trên dev.
  - Gộp các chunk quá ngắn trong cùng một h2, và cắt đoạn để không vượt 512 token.
  - Mở rộng tập test (≥15 câu) với một người chấm thứ hai độc lập.
  - Thêm filter `section` cho các câu như "removed/deprecated".
