# Plan K — Kaggle worker push (manual push, sync production sau)

Quyết định user (2026-10-05): trước mắt **push file thủ công** lên Kaggle qua script; cơ chế đồng bộ Kaggle↔cloud storage để production sau.

## Nghiên cứu (docs chính thức Kaggle CLI repo Kaggle/kaggle-cli)
- `pip install kaggle`; auth = env KAGGLE_USERNAME + KAGGLE_KEY (không cần ~/.kaggle).
- Kernel push = folder chứa `code_file` (.ipynb) + `kernel-metadata.json`; `kaggle kernels push -p folder` = upload + CHẠY NGAY (`--accelerator NvidiaTeslaT4`, `--timeout`, `--no-run`). Python: `KaggleApi().authenticate(); api.kernels_push(path); api.kernels_status(ref); api.kernels_output(ref, path)`.
- File đính kèm (pipeline.py/verdict.py) KHÔNG push kèm kernel → phải là **Kaggle dataset** (`dataset_sources` trong metadata; mount tại `/kaggle/input/<slug>/`).
- Bí mật: Kaggle Secrets (Add-ons UI) → `kaggle_secrets.UserSecretsClient().get_secret("BASE_URL"/"RUNNER_KEY")` (không có CLI).
- Internet phải BẬT (`enable_internet: true`) + BASE_URL phải public (Kaggle không tới localhost).

## Deliverables (worktree plan-kaggle)
1. `deploy/kaggle/files/` — dataset content: `worker/pipeline.py`, `worker/verdict.py` (copy từ worker/), `dataset-metadata.json` (title "img2text-worker-files", id auto theo KAGGLE_USERNAME khi push).
2. `deploy/kaggle/kernel/` — kernel folder:
   - `img2text_worker.ipynb` — notebook TÁCH từ worker/colab_notebook.ipynb, đổi 2 chỗ: (a) secrets `google.colab.userdata` → `kaggle_secrets.UserSecretsClient` (BASE_URL, RUNNER_KEY); (b) `sys.path.insert(0, "/kaggle/input/img2text-worker-files/worker")` (mount dataset) thay `"worker"`; cells Setup(!apt poppler + !pip paddlepaddle-gpu paddleocr httpx opencv-python-headless rapidfuzz pypdf pillow numpy) → Secrets(retry loop) → Smoke → Init → Loop GIỮ NGUYÊN logic.
   - `kernel-metadata.json` — template: id "OWNER/img2text-worker" (OWNER điền lúc push), kernel_type "notebook", language python, is_private true, enable_gpu true, enable_internet true, machine_shape "NvidiaTeslaT4", dataset_sources ["OWNER/img2text-worker-files"], timeout note.
3. `deploy/kaggle/push.py` — script Python (stdlib + kaggle package):
   - env: KAGGLE_USERNAME/KAGGLE_KEY bắt buộc (fail message rõ); tùy chọn: --no-run, --timeout, --accelerator (default NvidiaTeslaT4), --skip-dataset.
   - Bước: (1) copy worker/pipeline.py + verdict.py vào deploy/kaggle/files/ (fresh); (2) điền OWNER vào 2 metadata (generate vào build/ tạm, không ghi đè template); (3) `datasets_create_with_files` + `datasets_create_version` (dataset slug img2text-worker-files — nếu đã tồn tại: version mới); (4) `kernels_push` (build/kernel); (5) poll `kernels_status` mỗi 30s tới complete/failed rồi in kết quả + gợi ý `kernels output` khi xong.
   - In ra dặn dò: đặt BASE_URL (public!) + RUNNER_KEY vào Kaggle Secrets trước khi run; quota free ~30h GPU/tuần.
4. `deploy/kaggle/README.md` — hướng dẫn 1 trang: lấy API key, đặt Secrets trên kaggle.com, chạy `python deploy/kaggle/push.py`, xem status/output, cảnh báo internet/public URL + quota.
5. Test: `deploy/kaggle/test_push.py` (pytest, không network — mock KaggleApi) — push.py: OWNER substitution đúng, dataset calls đúng args, --skip-dataset bỏ qua, env thiếu báo lỗi; notebook builder: secrets cell chứa UserSecretsClient + sys.path mount đúng. Chạy: `.venv` server hoặc worker venv pytest deploy/kaggle/test_push.py (pytest có sẵn trong worker venv).
6. Gate: pytest test_push green; notebook JSON hợp lệ (python -m json.tool); không đụng web/server code. Commit: "feat(deploy): kaggle worker push (manual) — notebook + files dataset + push.py".

## Non-goals
Đồng bộ Kaggle↔cloud storage (production sau); auto-restart khi session 12h hết; thay đổi worker/pipeline.py logic.
