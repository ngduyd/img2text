# Kaggle worker push (manual — Plan K)

Push thủ công worker img2text lên Kaggle: kernel GPU (notebook) + dataset chứa `pipeline.py`/`verdict.py`.

## 1. Lấy API key

kaggle.com → Profile → Settings → API → Create New Token → tải `kaggle.json`.

```bash
export KAGGLE_USERNAME=<username>
export KAGGLE_KEY=<key>
```

Không cần `~/.kaggle` — env vars là đủ.

## 2. Đặt Secrets (BẮT BUỘC trước khi run kernel)

kaggle.com → Settings → Add-ons → Secrets:

| Tên | Giá trị |
|-----|---------|
| `BASE_URL` | URL công khai của API worker (`https://...` — **không** localhost) |
| `RUNNER_KEY` | key xác thực worker |

Secrets được đọc lúc kernel chạy (`kaggle_secrets.UserSecretsClient`, có retry loop). Đặt xong rồi mới push.

## 3. Chạy push

```bash
cd img2text
python deploy/kaggle/push.py                 # copy files → dataset create/version → kernels push + poll status
python deploy/kaggle/push.py --no-run        # push không chạy ngay
python deploy/kaggle/push.py --skip-dataset  # bỏ qua dataset (chỉ khi dataset đã push rồi)
python deploy/kaggle/push.py --timeout 10800 --accelerator NvidiaTeslaT4
```

Script làm gì: copy `worker/pipeline.py` + `worker/verdict.py` → `deploy/kaggle/files/`; điền `OWNER` = `KAGGLE_USERNAME` vào 2 metadata (build vào thư mục tạm, không đè template); `datasets_create_with_files` (dataset đã tồn tại → version mới); `kernels_push`; poll `kernels_status` mỗi 30s tới `complete`/`failed`.

## 4. Status / output

- Status: `kaggle kernels status OWNER/img2text-worker`
- Output: `kaggle kernels output OWNER/img2text-worker`

## 5. Lưu ý

- **Internet phải bật** (`enable_internet: true`) và `BASE_URL` phải **public** — Kaggle không tới được localhost.
- Quota GPU free ~**30h/tuần**. Accelerator ids: `NvidiaTeslaT4` (mặc định), `NvidiaTeslaP100`, `NvidiaTeslaK80`; CPU dùng `--accelerator CPU`.
- Kaggle↔cloud storage sync để production sau (non-goal Plan K).

## 6. Test nhanh (không cần backend public)

Batch mode (Plan K3): client đẩy input → kernel chạy → client tự lấy output. **Không cần backend public, không cần Secrets (`BASE_URL`/`RUNNER_KEY`) mode này** — chỉ cần env `KAGGLE_USERNAME`/`KAGGLE_KEY`.

```bash
export KAGGLE_USERNAME=<username>
export KAGGLE_KEY=<key>
python deploy/kaggle/run_one.py ./TA.jpg                    # đẩy input → run kernel → lấy output
python deploy/kaggle/run_one.py ./TA.pdf --timeout 3600 --poll 20 --out ./out
python deploy/kaggle/run_one.py ./TA.jpg --kernel-ref alice/my-batch --accelerator NvidiaTeslaT4
```

Flow:
1. **Input**: copy file vào temp stage + `dataset-metadata.json` (`img2text-input`) → dataset chưa có → `datasets_create_with_files`, đã có → version mới (dataset worker-files cũng ensure song song).
2. **Kernel**: copy `kernel/img2text_batch.ipynb` + `kernel-metadata.json` (`dataset_sources`: worker-files + img2text-input) → `kernels_push`.
3. **Poll** `kernels_status` mỗi `--poll` giây: `complete` → lấy output; `failed` → exit 1; timeout → exit 2.
4. **Output**: `kernels_output` vào thư mục mới `./out/<timestamp>/` (không lẫn output cũ) — có `result.json` (regions/page/markdown) + `result.md`.

Giới hạn (ponytail): **1 file/lần** (thư mục → báo lỗi), **1 slug input dataset dùng chung** (song song sẽ đè nhau), quota GPU free ~30h/tuần. K2 polling-backend mode (`push.py`) giữ nguyên cho production.
