# Kaggle worker push (manual — Plan K)

Push thủ công worker img2text lên Kaggle: kernel GPU (notebook) + dataset chứa `pipeline.py`/`verdict.py`.

## 1. Lấy API key

**Khuyến nghị (kaggle 2.x)**: kaggle.com → `kaggle.com/settings/api` → Generate New Token → dùng `KAGGLE_API_TOKEN` (kaggle package tự authenticate từ env — blob upload legacy username+key bị 401).

```bash
export KAGGLE_USERNAME=<username>          # OWNER id trong metadata (bắt buộc)
export KAGGLE_API_TOKEN=<token>            # khuyến nghị — kaggle 2.x primary
# hoặc legacy:
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

Script làm gì: copy `worker/pipeline.py` + `worker/verdict.py` → `deploy/kaggle/files/`; điền `OWNER` = `KAGGLE_USERNAME` vào 2 metadata (build vào thư mục tạm, không đè template); `kcompat.api_create_dataset` (`dataset_create_new`, dataset đã tồn tại → version mới từ folder staged); `kernels_push`; poll `kernels_status` mỗi 30s tới `complete`/`failed`.

## 4. Status / output

- Status: `kaggle kernels status OWNER/img2text-worker`
- Output: `kaggle kernels output OWNER/img2text-worker`

## 5. Lưu ý

- **kaggle package**: `kaggle>=1.6` — mọi call dataset đi qua `deploy/kaggle/kcompat.py` (hasattr dispatch, hỗ trợ cả 2 thế hệ API: `dataset_create_new`/`dataset_create_version`/`dataset_delete` mới và `datasets_*` cũ); thiếu method → lỗi rõ `kaggle package: <name> not found — cần kaggle>=1.6`.
- **Internet phải bật** (`enable_internet: true`) và `BASE_URL` phải **public** — Kaggle không tới được localhost.
- Quota GPU free ~**30h/tuần**. Accelerator ids: `NvidiaTeslaT4` (mặc định), `NvidiaTeslaP100`, `NvidiaTeslaK80`; CPU dùng `--accelerator CPU`.
- Kaggle↔cloud storage sync để production sau (non-goal Plan K).

## 6. Test nhanh (không cần backend public)

Batch mode (Plan K4): client đẩy input → **single-file script kernel** chạy → client tự lấy output. **Không cần backend public, không cần Secrets (`BASE_URL`/`RUNNER_KEY`) mode này** — auth khuyên `KAGGLE_API_TOKEN` (kèm `KAGGLE_USERNAME` cho OWNER metadata; token path tự authenticate, username chỉ để đặt id trong metadata), hoặc legacy `KAGGLE_USERNAME`+`KAGGLE_KEY`.

```bash
export KAGGLE_USERNAME=<username>
export KAGGLE_API_TOKEN=<token>            # khuyến nghị (kaggle 2.x)
# hoặc legacy: export KAGGLE_KEY=<key>
python deploy/kaggle/run_one.py ./TA.jpg                    # đẩy input → run kernel → lấy output
python deploy/kaggle/run_one.py ./TA.pdf --timeout 3600 --poll 20 --out ./out
python deploy/kaggle/run_one.py ./TA.jpg --kernel-ref alice/my-batch --accelerator NvidiaTeslaT4
```

Flow:
1. **Input**: copy file vào temp stage + `dataset-metadata.json` (`img2text-input`) → check tồn tại qua `kcompat.api_dataset_exists` (`dataset_list` — method thật, không nuốt AttributeError); chưa có → `kcompat.api_create_dataset`; **đã có → `kcompat.api_delete_dataset` + create lại với staged folder** — **dataset input bị thay thế mỗi run** (đảm bảo re-run upload file mới nhất, không stale — version bump không upload files). Không còn dataset `img2text-worker-files` — worker code nằm hẳn trong script.
2. **Kernel (single file)**: copy `kernel/img2text_batch.py` + `kernel/kernel-batch-metadata.json` (`kernel_type: script`, `dataset_sources`: chỉ `img2text-input`) → `kernels_push`. Script tự cài deps + tự discover input (glob `/kaggle/input/**/*` — mount mới Kaggle đặt dataset dưới `/kaggle/input/<owner>/<slug>/`).
3. **Poll** `kernels_status` mỗi `--poll` giây: `complete` → lấy output; `failed` → exit 1; timeout → exit 2.
4. **Output**: `kernels_output` vào thư mục mới `./out/<timestamp>/` (không lẫn output cũ) — có `result.json` (document shape: `pages[]`/`blocks[]` theo notebook, block `{id, order, type, bbox, text, empty}`) + `result.md`.

Lưu ý capture: `kernel_type: script` chỉ capture output từ **`/kaggle/working`** (`/kaggle/outputs` chỉ được capture với notebook kernel) — script ghi `result.{json,md}` vào `/kaggle/working` (capture chính) + copy sang `/kaggle/outputs` (compat, hại nếu thiếu).

Paddle trên Kaggle: kernel Kaggle mặc định Python 3.13 (không có paddle wheel) → script tạo venv py3.12 riêng bằng `uv` (`uv venv /tmp/paddle-venv --python 3.12` + `paddlepaddle-gpu==3.2.1` index cu126) rồi re-exec chính nó (`--ocr`) dưới venv đó. **Nếu `uv venv --python 3.12` fail**: kiểm tra kernel `internet=true` (Settings) + GPU quota; cài xong đã verify `import paddle, paddleocr` (fail → SystemExit rõ). Chạy CPU-only = chậm, chỉ để test.

Giới hạn (ponytail): **1 file/lần** (thư mục → báo lỗi), **1 slug input dataset dùng chung** — mỗi run ghi đè (`delete+recreate`) input dataset, song song sẽ đè nhau; `--poll` tối thiểu 1s; output vào `./out/<timestamp-micros>/` riêng mỗi run; quota GPU free ~30h/tuần. K2 polling-backend mode (`push.py`) giữ nguyên cho production.
