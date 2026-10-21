import json
import logging
import os
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

# ===============================================================
# 0. CONFIGURATION & CONSTANTS
# ===============================================================

# --- File Paths ---
INPUT_PATH = Path("dataset_clean_categories/fragment_username_sample_clean_categories.csv")
OUTPUT_PATH = Path("complete_dataset/raw_actions_compressed.jsonl")
COMPLETED_PATH = Path("completed_nfts.txt")
TEMP_WORKER_DIR = Path("worker_temp_files")

# --- Toncenter v3 API Configuration ---
BASE_URL = "https://toncenter.com/api/v3/actions"

# Load keys from environment variable (comma-separated) or hardcode a fallback list
API_KEYS = ["63054951e624ae18bea53567400123b039df0e05a0245f95a64ac0897bcb1917",
    "8660df71b1606cc5be730aaeb25427e0aebd58d10c120960a84d6457a82023d7",
    "a95ce82f4d3022ce910b7e221c76e7f09ecb6fced42a2044564e9222f5c95284",
    "c251d33135e1fd46e6c331275ea4f175960d16bd7d1571701c6aed9552a55080",
    "61a4fbc15496d9205296ebd033f324bb545716c750766980d46582438c3b9009",
    "5bb4c419276f450cbdc419914c92b4bb3ad3e51e5c514e8ff081e89c4ba05f07",
    "4f1188c792c88cf27a59bbda10e95126706ae0f86664d1a0174bd8ff619c5fc7",
    "562aaa8a60ac481c7b1f9e7ad80c301a4d2d613f6caab8d9736688c3e03946af",
    "1f7cf1a40b082b4218d1caef06789aeaf0b6da72c775ed86d50c5779eaf6b494",
    "f66bf494477344c5cc3fbee4c3ccaf4a14194ca7828ec1cd106b597557c6c5d3",
    "55c99061a03ed5b0623c024f9031b89c91921a1b37eeac6b133ab72d44620f03"
    # Add your additional Toncenter API keys here
]

# --- Fetch & Rate Limit Tuning ---
PAGE_SIZE = 1000
REQUEST_INTERVAL = 0.15   # Seconds between requests on the SAME key (~6.7 RPS)
MAX_RETRIES = 8
REQUEST_TIMEOUT = 60      # Seconds before HTTP timeout


# ===============================================================
# 1. LOGGING & GLOBAL METRICS TRACKER
# ===============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

stats_lock = threading.Lock()
global_addresses_done = 0
global_records_extracted = 0
global_api_calls = 0
stop_monitor_event = threading.Event()


def progress_monitor(total_targets: int, start_time: float):
    """
    Dedicated thread outputting live global throughput and ETA once per second.
    """
    last_records = 0
    while not stop_monitor_event.is_set():
        time.sleep(1.0)

        with stats_lock:
            done = global_addresses_done
            records = global_records_extracted

        elapsed = time.perf_counter() - start_time
        records_last_sec = records - last_records
        last_records = records

        if done > 0 and elapsed > 0:
            rate_addr = done / elapsed
            remaining = max(0, total_targets - done)
            eta_seconds = remaining / rate_addr if rate_addr > 0 else 0
            eta_min, eta_sec = divmod(int(eta_seconds), 60)
            eta_str = f"{eta_min:02d}m {eta_sec:02d}s"
        else:
            eta_str = "Calculating..."

        pct = (done / total_targets * 100) if total_targets > 0 else 0
        sys.stdout.write(
            f"\r[STATUS] {done}/{total_targets} addrs ({pct:.1f}%) | "
            f"+{records_last_sec} actions/s (Total: {records:,}) | "
            f"ETA: {eta_str}    "
        )
        sys.stdout.flush()
    print()


# ===============================================================
# 2. SCHEMA COMPRESSION & DECOMPRESSION
# ===============================================================
KEY_MAP = {
    "nft": "n",
    "username": "u",
    "categories": "c",
    "layer": "ly",
    "owner_address": "oa",
    "action_id": "aid",
    "trace_id": "tid",
    "timestamp": "t",
    "end_timestamp": "et",
    "start_lt": "slt",
    "end_lt": "elt",
    "action_type": "y",
    "success": "ok",
    "details": "det",
}


def compress_entry(record: dict) -> dict:
    """
    Compresses recurring metadata and schema fields into compact 1-2 char keys.
    """
    return {
        KEY_MAP["nft"]: record.get("nft"),
        KEY_MAP["username"]: record.get("username"),
        KEY_MAP["categories"]: record.get("categories", []),
        KEY_MAP["layer"]: record.get("layer"),
        KEY_MAP["owner_address"]: record.get("owner_address"),
        KEY_MAP["action_id"]: record.get("action_id"),
        KEY_MAP["trace_id"]: record.get("trace_id"),
        KEY_MAP["timestamp"]: record.get("timestamp"),
        KEY_MAP["end_timestamp"]: record.get("end_timestamp"),
        KEY_MAP["start_lt"]: record.get("start_lt"),
        KEY_MAP["end_lt"]: record.get("end_lt"),
        KEY_MAP["action_type"]: record.get("action_type"),
        KEY_MAP["success"]: record.get("success"),
        KEY_MAP["details"]: record.get("details"),
    }


def decompress_entry(compressed: dict) -> dict:
    """
    Losslessly reconstructs the original schema.
    """
    return {
        "nft": compressed.get(KEY_MAP["nft"]),
        "username": compressed.get(KEY_MAP["username"]),
        "categories": compressed.get(KEY_MAP["categories"], []),
        "layer": compressed.get(KEY_MAP["layer"]),
        "owner_address": compressed.get(KEY_MAP["owner_address"]),
        "action_id": compressed.get(KEY_MAP["action_id"]),
        "trace_id": compressed.get(KEY_MAP["trace_id"]),
        "timestamp": compressed.get(KEY_MAP["timestamp"]),
        "end_timestamp": compressed.get(KEY_MAP["end_timestamp"]),
        "start_lt": compressed.get(KEY_MAP["start_lt"]),
        "end_lt": compressed.get(KEY_MAP["end_lt"]),
        "action_type": compressed.get(KEY_MAP["action_type"]),
        "success": compressed.get(KEY_MAP["success"]),
        "details": compressed.get(KEY_MAP["details"]),
    }


# ===============================================================
# 3. CSV METADATA PARSING
# ===============================================================
def parse_categories(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def clean_value(value):
    return None if pd.isna(value) else str(value)


def load_metadata():
    meta_df = pd.read_csv(INPUT_PATH, dtype={"address": str})
    required = {"address", "name", "categories", "owner_address"}
    missing = required - set(meta_df.columns)
    if missing:
        raise ValueError(f"Missing columns in CSV: {missing}")

    meta_df["categories"] = meta_df["categories"].apply(parse_categories)
    meta_df = meta_df.dropna(subset=["address"]).drop_duplicates(subset=["address"])

    addresses = meta_df["address"].tolist()
    metadata = {
        row["address"]: {
            "username": clean_value(row["name"]),
            "categories": row["categories"],
            "owner_address": clean_value(row["owner_address"]),
        }
        for _, row in meta_df.iterrows()
    }
    return addresses, metadata


# ===============================================================
# 4. HTTP REQUEST & RETRY LOGIC (Thread-Isolated)
# ===============================================================
def get_retry_delay(response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            try:
                date = parsedate_to_datetime(retry_after)
                seconds = (date - datetime.now(timezone.utc)).total_seconds()
                return max(seconds, 1.0)
            except (TypeError, ValueError, OverflowError):
                pass
    return min(10 * (2 ** attempt), 120) + random.random()


def request_actions_worker(session: requests.Session, params: dict, last_req_box: list) -> dict:
    for attempt in range(MAX_RETRIES):
        now = time.monotonic()
        if last_req_box[0] is not None:
            remaining = REQUEST_INTERVAL - (now - last_req_box[0])
            if remaining > 0:
                time.sleep(remaining)
        last_req_box[0] = time.monotonic()

        try:
            response = session.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT)

            if response.status_code in (401, 403):
                raise PermissionError(
                    f"API unauthorized: HTTP {response.status_code}. Verify key permissions."
                )

            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == MAX_RETRIES - 1:
                    response.raise_for_status()
                delay = get_retry_delay(response, attempt)
                time.sleep(delay)
                continue

            response.raise_for_status()
            data = response.json()

            if not isinstance(data, dict):
                raise RuntimeError("Invalid API response format (expected JSON dict)")
            if data.get("error"):
                raise RuntimeError(f"TON Center API Error: {data['error']}")

            return data

        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(min(5 * (2 ** attempt), 60))

    raise RuntimeError("Exceeded maximum retries on request")


def flatten_action(nft_address: str, act: dict, metadata_map: dict) -> dict:
    meta = metadata_map.get(nft_address, {})
    return {
        "nft": nft_address,
        "username": meta.get("username"),
        "categories": meta.get("categories", []),
        "layer": "usernames", # phone_numbers / gifts
        "owner_address": meta.get("owner_address"),
        "action_id": act.get("action_id"),
        "trace_id": act.get("trace_id"),
        "timestamp": act.get("start_utime"),
        "end_timestamp": act.get("end_utime"),
        "start_lt": act.get("start_lt"),
        "end_lt": act.get("end_lt"),
        "action_type": act.get("type"),
        "success": act.get("success"),
        "details": act.get("details"),
    }


def fetch_account_actions(session: requests.Session, address: str, metadata_map: dict, last_req_box: list):
    offset = 0
    rows = []
    seen_ids = set()
    pages = 0

    while True:
        params = {
            "account": address,
            "limit": PAGE_SIZE,
            "offset": offset,
            "sort": "asc",
            "include_accounts": "false",
            "include_transactions": "false",
        }

        data = request_actions_worker(session, params, last_req_box)
        pages += 1
        batch = data.get("actions")

        if not isinstance(batch, list):
            raise RuntimeError(f"Missing 'actions' array in API response for {address}")

        for act in batch:
            action_id = act.get("action_id")
            if action_id is not None:
                if action_id in seen_ids:
                    continue
                seen_ids.add(action_id)

            rows.append(flatten_action(address, act, metadata_map))

        if len(batch) < PAGE_SIZE:
            break

        offset += len(batch)

    return rows, pages


# ===============================================================
# 5. WORKER THREAD TASK
# ===============================================================
def worker_task(worker_id: int, api_key: str, addresses: list, metadata_map: dict):
    global global_addresses_done, global_records_extracted, global_api_calls

    worker_out_path = TEMP_WORKER_DIR / f"worker_{worker_id}.jsonl"
    worker_comp_path = TEMP_WORKER_DIR / f"completed_{worker_id}.txt"

    session = requests.Session()
    session.headers.update({
        "X-API-Key": api_key,
        "Accept": "application/json"
    })

    last_req_box = [None]

    with open(worker_out_path, "a", encoding="utf-8") as fout, \
         open(worker_comp_path, "a", encoding="utf-8") as fcomp:

        for addr in addresses:
            start_offset = fout.tell()

            try:
                rows, pages = fetch_account_actions(session, addr, metadata_map, last_req_box)

                is_empty = False
                if not rows:
                    is_empty = True
                    meta = metadata_map.get(addr, {})
                    rows = [{
                        "nft": addr,
                        "username": meta.get("username"),
                        "categories": meta.get("categories", []),
                        "layer": "usernames",
                        "owner_address": meta.get("owner_address"),
                        "action_id": None,
                        "trace_id": None,
                        "timestamp": None,
                        "end_timestamp": None,
                        "start_lt": None,
                        "end_lt": None,
                        "action_type": "NO_ACTIONS",
                        "success": None,
                        "details": None,
                    }]

                # Write compressed JSON lines directly
                compressed_lines = [
                    json.dumps(compress_entry(r), ensure_ascii=False, separators=(",", ":"))
                    for r in rows
                ]
                fout.write("\n".join(compressed_lines) + "\n")
                fout.flush()

                # Register checkpoint
                fcomp.write(addr + "\n")
                fcomp.flush()

                with stats_lock:
                    global_addresses_done += 1
                    if not is_empty:
                        global_records_extracted += len(rows)
                    global_api_calls += pages

            except PermissionError as e:
                logging.error(f"Worker {worker_id} Authentication Error: {e}")
                return

            except Exception:
                # Rollback partial write on failure
                fout.seek(start_offset)
                fout.truncate(start_offset)
                fout.flush()

                with stats_lock:
                    global_addresses_done += 1


# ===============================================================
# 6. MAIN ORCHESTRATION & SPEEDUP BENCHMARK
# ===============================================================
def main():
    TEMP_WORKER_DIR.mkdir(parents=True, exist_ok=True)

    asset_addresses, metadata_map = load_metadata()

    # Load previously completed NFTs
    already_done = set()
    files_to_check = [COMPLETED_PATH] + list(TEMP_WORKER_DIR.glob("completed_*.txt"))
    for file_path in files_to_check:
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        already_done.add(stripped)

    todo = [a for a in asset_addresses if a not in already_done]
    total_todo = len(todo)
    num_keys = len(API_KEYS)

    logging.info("NFTs in CSV: %d | Completed: %d | Remaining: %d", len(asset_addresses), len(already_done), total_todo)
    logging.info("Active worker pool: %d keys", num_keys)

    if not todo:
        logging.info("All NFTs already processed.")
        return

    # Shard evenly across available keys
    chunks = [todo[i::num_keys] for i in range(num_keys)]

    start_time = time.perf_counter()

    # Start the 1-second global progress monitor
    monitor_thread = threading.Thread(
        target=progress_monitor,
        args=(total_todo, start_time),
        daemon=True
    )
    monitor_thread.start()

    with ThreadPoolExecutor(max_workers=num_keys) as executor:
        futures = [
            executor.submit(worker_task, i, API_KEYS[i], chunks[i], metadata_map)
            for i in range(num_keys)
        ]
        for f in futures:
            f.result()

    # Stop monitor thread
    stop_monitor_event.set()
    monitor_thread.join()

    elapsed = time.perf_counter() - start_time

    # Consolidate shards
    logging.info("Consolidating temporary worker shards...")
    with open(OUTPUT_PATH, "a", encoding="utf-8") as out_jsonl, \
         open(COMPLETED_PATH, "a", encoding="utf-8") as out_comp:

        for worker_file in TEMP_WORKER_DIR.glob("worker_*.jsonl"):
            with open(worker_file, "r", encoding="utf-8") as f:
                for line in f:
                    out_jsonl.write(line)
            worker_file.unlink()

        for comp_file in TEMP_WORKER_DIR.glob("completed_*.txt"):
            with open(comp_file, "r", encoding="utf-8") as f:
                for line in f:
                    out_comp.write(line)
            comp_file.unlink()

    if TEMP_WORKER_DIR.exists() and not any(TEMP_WORKER_DIR.iterdir()):
        TEMP_WORKER_DIR.rmdir()

    # Speedup calculation
    effective_call_rate = global_api_calls / elapsed if elapsed > 0 else 0
    estimated_single_key_time = global_api_calls * (REQUEST_INTERVAL + 0.12)
    observed_speedup = (estimated_single_key_time / elapsed) if elapsed > 0 else 1.0

    print("\n" + "=" * 55)
    print("EXTRACTION BENCHMARK REPORT (TONCENTER V3)")
    print("=" * 55)
    print(f"Addresses processed       : {global_addresses_done}")
    print(f"Actions extracted         : {global_records_extracted:,}")
    print(f"Total API calls executed  : {global_api_calls}")
    print(f"Runtime                   : {elapsed:.2f}s ({elapsed / 60:.2f} min)")
    print(f"Throughput                : {effective_call_rate:.2f} calls/sec")
    print(f"Estimated 1-key runtime   : {estimated_single_key_time:.2f}s ({estimated_single_key_time / 60:.2f} min)")
    print(f"Observed speedup          : {observed_speedup:.2f}x (Theoretical max: {num_keys}.00x)")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
