import csv
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
import requests

# Increase CSV field size limit to handle massive JSON cells
maxInt = sys.maxsize
while True:
    try:
        csv.field_size_limit(maxInt)
        break
    except OverflowError:
        maxInt = int(maxInt/10)

# ===============================================================
# 0. CONFIGURATION & CONSTANTS
# ===============================================================

# --- File Paths ---
INPUT_PATH = Path("dataset_categories/usernames_completo_categories.csv")
OUTPUT_PATH = Path("complete_dataset_raw/raw_actions_compressed.jsonl")
COMPLETED_PATH = Path("completed_nfts.txt")
TEMP_WORKER_DIR = Path("worker_temp_files")

# --- Toncenter v3 API Configuration ---
BASE_URL = "https://toncenter.com/api/v3/actions"

# Load keys safely
try:
    with open(".env", "r") as f:
        #API_KEYS = [line.strip() for line in f if line.strip()]
        API_KEYS= []
except FileNotFoundError:
    print("Error: .env file not found.")
    sys.exit(1)

# --- Fetch & Rate Limit Tuning ---
PAGE_SIZE = 1000
REQUEST_INTERVAL = 0.15   # Seconds between requests on the SAME key (~6.7 RPS)
MAX_RETRIES = 8
REQUEST_TIMEOUT = 60      # Seconds before HTTP timeout


# ===============================================================
# 1. LOGGING, UI HELPERS & METRICS
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

def render_bar(pct: float, width: int = 25) -> str:
    """Generates an ASCII progress bar string."""
    filled = int(width * (pct / 100))
    bar = "█" * filled + "-" * (width - filled)
    return f"[{bar}] {pct:5.1f}%"

def progress_monitor(total_targets: int, start_time: float):
    """
    Dedicated thread outputting live global throughput, progress bar, and ETA.
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
            f"\r[STAGE 5/6] Extractor {render_bar(pct, 20)} | "
            f"{done}/{total_targets} addrs | "
            f"+{records_last_sec}/s (Tot: {records:,}) | ETA: {eta_str}    "
        )
        sys.stdout.flush()
    print()


# ===============================================================
# 2. SCHEMA COMPRESSION & DECOMPRESSION
# ===============================================================
KEY_MAP = {
    "nft": "n", "username": "u", "categories": "c", "layer": "ly", 
    "owner_address": "oa", "action_id": "aid", "trace_id": "tid", 
    "timestamp": "t", "end_timestamp": "et", "start_lt": "slt", 
    "end_lt": "elt", "action_type": "y", "success": "ok", "details": "det",
}

def compress_entry(record: dict) -> dict:
    return {
        KEY_MAP["nft"]: record.get("nft"), KEY_MAP["username"]: record.get("username"),
        KEY_MAP["categories"]: record.get("categories", []), KEY_MAP["layer"]: record.get("layer"),
        KEY_MAP["owner_address"]: record.get("owner_address"), KEY_MAP["action_id"]: record.get("action_id"),
        KEY_MAP["trace_id"]: record.get("trace_id"), KEY_MAP["timestamp"]: record.get("timestamp"),
        KEY_MAP["end_timestamp"]: record.get("end_timestamp"), KEY_MAP["start_lt"]: record.get("start_lt"),
        KEY_MAP["end_lt"]: record.get("end_lt"), KEY_MAP["action_type"]: record.get("action_type"),
        KEY_MAP["success"]: record.get("success"), KEY_MAP["details"]: record.get("details"),
    }


# ===============================================================
# 3. METADATA PARSING & FILE INTEGRITY TOOLS (OPTIMIZED)
# ===============================================================
def parse_categories(value):
    if not value: return []
    value = value.strip()
    if not value or value == "[]": return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError: 
        return []

def clean_value(value):
    if not value: return None
    value = value.strip()
    return None if not value or value.lower() in ("nan", "null") else value

class FileByteTracker:
    """Wraps a file object to safely track bytes read without breaking csv.reader"""
    def __init__(self, f):
        self.f = f
        self.bytes_read = 0

    def __iter__(self):
        for line in self.f:
            self.bytes_read += len(line.encode("utf-8"))
            yield line

def load_metadata():
    """High-speed CSV parser using raw Python to avoid RAM spikes."""
    print(f"[STAGE 1/6] Loading CSV {render_bar(0)}", end="\r", flush=True)
    
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Cannot find dataset at {INPUT_PATH}")
        
    file_size = os.path.getsize(INPUT_PATH)
    total_gb = file_size / (1024 ** 3)
    
    addresses = []
    metadata = {}
    start_t = time.perf_counter()
    last_t = start_t
    rows_parsed = 0
    
    with open(INPUT_PATH, "r", encoding="utf-8") as raw_f:
        tracker = FileByteTracker(raw_f)
        reader = csv.reader(tracker)
        
        try: 
            headers = next(reader)
        except StopIteration: 
            raise ValueError("CSV file is empty.")
            
        required = {"address", "name", "categories", "owner_address"}
        if required - set(headers):
            raise ValueError(f"Missing columns in CSV: {required - set(headers)}")
            
        idx = {k: headers.index(k) for k in required}
        
        for row in reader:
            rows_parsed += 1
            if len(row) <= max(idx.values()): continue
                
            addr = row[idx["address"]].strip()
            if not addr or addr in metadata: continue
                
            addresses.append(addr)
            metadata[addr] = {
                "username": clean_value(row[idx["name"]]),
                "categories": parse_categories(row[idx["categories"]]),
                "owner_address": clean_value(row[idx["owner_address"]]),
            }
            
            curr_t = time.perf_counter()
            if curr_t - last_t > 0.25:
                pct = (tracker.bytes_read / file_size) * 100 if file_size > 0 else 0
                print(f"\r[STAGE 1/6] Loading CSV {render_bar(pct)} | {tracker.bytes_read / (1024**3):.2f}/{total_gb:.2f} GB | {rows_parsed:,} rows    ", end="", flush=True)
                last_t = curr_t
                
    elapsed = time.perf_counter() - start_t
    print(f"\r[STAGE 1/6] Loading CSV {render_bar(100.0)} | {len(addresses):,} unique NFTs loaded in {elapsed:.1f}s{' '*20}")
    return addresses, metadata

def clean_and_repair_jsonl(filepath: Path) -> str | None:
    if not filepath.exists() or os.path.getsize(filepath) == 0: return None
    with open(filepath, "rb+") as f:
        f.seek(-1, os.SEEK_END)
        last_char = f.read(1)
        file_size = f.tell()
        
        if last_char != b"\n":
            print(f"\n[WARNING] Detected incomplete trailing write in {filepath.name}. Repairing...")
            buffer_size = 1024 * 64
            found_pos = -1
            for offset in range(buffer_size, file_size + buffer_size, buffer_size):
                read_pos = max(0, file_size - offset)
                f.seek(read_pos)
                chunk = f.read(min(offset, file_size))
                newline_idx = chunk.rfind(b"\n")
                if newline_idx != -1:
                    found_pos = read_pos + newline_idx + 1
                    break
            
            if found_pos != -1:
                f.seek(found_pos)
                f.truncate()
                file_size = found_pos
            else:
                f.seek(0)
                f.truncate()
                return None

        if file_size == 0: return None
        read_size = min(file_size, 64 * 1024)
        f.seek(file_size - read_size)
        tail_data = f.read().decode("utf-8", errors="ignore")
        for line in reversed(tail_data.splitlines()):
            line = line.strip()
            if line:
                try: return json.loads(line).get("n")
                except json.JSONDecodeError: continue
    return None

def sanitize_output_and_remove_addresses(filepath: Path, target_addrs: set):
    """Purges ALL target addresses in a single, high-speed binary pass."""
    if not filepath.exists() or not target_addrs:
        return

    file_size = os.path.getsize(filepath)
    if file_size == 0:
        return

    temp_path = filepath.with_suffix(".tmp")
    
    # Pre-encode all target patterns to search natively in bytes
    target_patterns = {f'"n":"{addr}"'.encode("utf-8") for addr in target_addrs}

    with open(filepath, "rb") as fin, open(temp_path, "wb") as fout:
        processed_bytes = 0
        start_time = time.perf_counter()
        last_update_time = start_time
        last_bytes = 0

        for line in fin:
            processed_bytes += len(line)

            # Drop line if ANY suspicious address pattern matches
            if any(pattern in line for pattern in target_patterns):
                continue
            
            fout.write(line)

            now = time.perf_counter()
            dt = now - last_update_time
            if dt >= 0.25:
                rate = (processed_bytes - last_bytes) / dt if dt > 0 else 0
                remaining = max(0, file_size - processed_bytes)
                eta = remaining / rate if rate > 0 else 0
                pct = (processed_bytes / file_size) * 100

                print(
                    f"\r[STAGE 4/6] Sanitizing  {render_bar(pct)} | "
                    f"{processed_bytes / (1024**3):.2f}/{file_size / (1024**3):.2f} GB | "
                    f"Speed: {rate / (1024*1024):.1f} MB/s | ETA: {int(eta)}s    ",
                    end="",
                    flush=True,
                )
                last_update_time = now
                last_bytes = processed_bytes

    temp_path.replace(filepath)
    print(f"\r[STAGE 4/6] Sanitizing  {render_bar(100.0)} | File safely sanitized.{' ' * 30}")


# ===============================================================
# 4. HTTP REQUEST & RETRY LOGIC
# ===============================================================
def get_retry_delay(response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try: return max(float(retry_after), 1.0)
        except ValueError:
            try:
                date = parsedate_to_datetime(retry_after)
                return max((date - datetime.now(timezone.utc)).total_seconds(), 1.0)
            except: pass
    return min(10 * (2 ** attempt), 120) + random.random()

def request_actions_worker(session: requests.Session, params: dict, last_req_box: list) -> dict:
    for attempt in range(MAX_RETRIES):
        now = time.monotonic()
        if last_req_box[0] is not None:
            remaining = REQUEST_INTERVAL - (now - last_req_box[0])
            if remaining > 0: time.sleep(remaining)
        last_req_box[0] = time.monotonic()

        try:
            response = session.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code in (401, 403):
                raise PermissionError(f"API unauthorized: HTTP {response.status_code}.")
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == MAX_RETRIES - 1: response.raise_for_status()
                time.sleep(get_retry_delay(response, attempt))
                continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict): raise RuntimeError("Invalid API response format")
            if data.get("error"): raise RuntimeError(f"API Error: {data['error']}")
            return data
        except (requests.Timeout, requests.ConnectionError):
            if attempt == MAX_RETRIES - 1: raise
            time.sleep(min(5 * (2 ** attempt), 60))
    raise RuntimeError("Exceeded maximum retries")

def fetch_account_actions(session: requests.Session, address: str, metadata_map: dict, last_req_box: list):
    offset, pages, rows, seen_ids = 0, 0, [], set()
    while True:
        data = request_actions_worker(session, {
            "account": address, "limit": PAGE_SIZE, "offset": offset, 
            "sort": "asc", "include_accounts": "false", "include_transactions": "false"
        }, last_req_box)
        pages += 1
        batch = data.get("actions")
        if not isinstance(batch, list): raise RuntimeError(f"Missing 'actions' array for {address}")

        for act in batch:
            aid = act.get("action_id")
            if aid:
                if aid in seen_ids: continue
                seen_ids.add(aid)
            
            meta = metadata_map.get(address, {})
            rows.append({
                "nft": address, "username": meta.get("username"),
                "categories": meta.get("categories", []), "layer": "usernames", 
                "owner_address": meta.get("owner_address"), "action_id": aid,
                "trace_id": act.get("trace_id"), "timestamp": act.get("start_utime"),
                "end_timestamp": act.get("end_utime"), "start_lt": act.get("start_lt"),
                "end_lt": act.get("end_lt"), "action_type": act.get("type"),
                "success": act.get("success"), "details": act.get("details"),
            })

        if len(batch) < PAGE_SIZE: break
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
    session.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    last_req_box = [None]

    with open(worker_out_path, "a", encoding="utf-8") as fout, open(worker_comp_path, "a", encoding="utf-8") as fcomp:
        for addr in addresses:
            start_offset = fout.tell()
            try:
                rows, pages = fetch_account_actions(session, addr, metadata_map, last_req_box)
                is_empty = not rows
                if is_empty:
                    meta = metadata_map.get(addr, {})
                    rows = [{"nft": addr, "username": meta.get("username"), "categories": meta.get("categories", []), "layer": "usernames", "owner_address": meta.get("owner_address"), "action_id": None, "trace_id": None, "timestamp": None, "end_timestamp": None, "start_lt": None, "end_lt": None, "action_type": "NO_ACTIONS", "success": None, "details": None}]

                fout.write("\n".join([json.dumps(compress_entry(r), ensure_ascii=False, separators=(",", ":")) for r in rows]) + "\n")
                fout.flush()
                fcomp.write(addr + "\n")
                fcomp.flush()

                with stats_lock:
                    global_addresses_done += 1
                    if not is_empty: global_records_extracted += len(rows)
                    global_api_calls += pages

            except PermissionError as e:
                print(f"\n[Worker {worker_id}] Auth Error: {e}")
                return
            except Exception:
                fout.seek(start_offset)
                fout.truncate(start_offset)
                fout.flush()
                with stats_lock: global_addresses_done += 1


# ===============================================================
# 6. MAIN ORCHESTRATION & SPEEDUP BENCHMARK
# ===============================================================
def main():
    print("\nStarting TON NFT Extractor Pipeline...")
    TEMP_WORKER_DIR.mkdir(parents=True, exist_ok=True)

    # STAGE 1: LOAD CSV DATA
    asset_addresses, metadata_map = load_metadata()

    # STAGE 2: VERIFY JSONL FILE INTEGRITY
    jsonl_files = [OUTPUT_PATH] + list(TEMP_WORKER_DIR.glob("worker_*.jsonl"))
    tot_files = len(jsonl_files)
    for i, j_file in enumerate(jsonl_files):
        pct = (i / max(1, tot_files)) * 100
        print(f"\r[STAGE 2/6] Integrity   {render_bar(pct)} | Checking {j_file.name}...{' '*15}", end="", flush=True)
        clean_and_repair_jsonl(j_file)
    print(f"\r[STAGE 2/6] Integrity   {render_bar(100.0)} | File integrity passed.{' '*25}")

    # STAGE 3: RECOVER COMPLETED ADDRESSES
    already_done = set()
    last_txt_nft = None

    for file_path in [COMPLETED_PATH] + list(TEMP_WORKER_DIR.glob("completed_*.txt")):
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        already_done.add(stripped)
                        last_txt_nft = stripped

    existing_jsonls = [f for f in jsonl_files if f.exists()]
    total_bytes = sum(os.path.getsize(f) for f in existing_jsonls)
    last_jsonl_nft = None

    if total_bytes > 0:
        total_mb = total_bytes / (1024 * 1024)
        processed_bytes = 0
        start_scan_time = time.perf_counter()
        last_update_time = start_scan_time

        for j_file in existing_jsonls:
            with open(j_file, "r", encoding="utf-8") as f:
                for line in f:
                    processed_bytes += len(line.encode("utf-8"))
                    if not line.strip(): continue
                    try:
                        record = json.loads(line)
                        if "n" in record:
                            already_done.add(record["n"])
                            last_jsonl_nft = record["n"]
                    except json.JSONDecodeError: continue

                    current_time = time.perf_counter()
                    if current_time - last_update_time > 0.25:
                        elapsed = current_time - start_scan_time
                        rate = processed_bytes / elapsed if elapsed > 0 else 0
                        eta = (total_bytes - processed_bytes) / rate if rate > 0 else 0
                        pct = (processed_bytes / total_bytes) * 100
                        print(f"\r[STAGE 3/6] Recovery    {render_bar(pct)} | {processed_bytes / (1024*1024):.1f}/{total_mb:.1f} MB | ETA: {int(eta)}s    ", end="", flush=True)
                        last_update_time = current_time

        print(f"\r[STAGE 3/6] Recovery    {render_bar(100.0)} | Scan finished in {time.perf_counter() - start_scan_time:.1f}s{' '*20}")
    else:
        print(f"[STAGE 3/6] Recovery    {render_bar(100.0)} | No existing data. Starting fresh.")

    # # STAGE 4: HANDLE CRASH EDGE CASES
    # suspicious_targets = {a for a in [last_txt_nft, last_jsonl_nft] if a is not None}
    # if suspicious_targets:
    #     for sus_addr in suspicious_targets:
    #         already_done.discard(sus_addr)
            
    #     # Single pass per file to sanitize all suspicious addresses simultaneously
    #     for j_file in existing_jsonls: 
    #         sanitize_output_and_remove_addresses(j_file, suspicious_targets)
        
    #     print(f"\r[STAGE 4/6] Sanitizing  {render_bar(100.0)} | Crash artifacts removed.{' '*25}")
        
    #     if COMPLETED_PATH.exists():
    #         with open(COMPLETED_PATH, "r", encoding="utf-8") as f:
    #             lines = [l for l in f if l.strip() not in suspicious_targets]
    #         with open(COMPLETED_PATH, "w", encoding="utf-8") as f: f.writelines(lines)
    # else:
    #     print(f"[STAGE 4/6] Sanitizing  {render_bar(100.0)} | Clean shutdown detected. No repair needed.")

    # STAGE 5: PREPARE REMAINING WORK & EXTRACT
    todo = [a for a in asset_addresses if a not in already_done]
    total_todo = len(todo)
    num_keys = len(API_KEYS)
    print(f"\nTarget: {total_todo:,} remaining NFTs | Workers: {num_keys} API keys\n")

    if not todo:
        print("All NFTs already processed.")
        return

    chunks = [todo[i::num_keys] for i in range(num_keys)]
    start_time = time.perf_counter()

    monitor_thread = threading.Thread(target=progress_monitor, args=(total_todo, start_time), daemon=True)
    monitor_thread.start()

    with ThreadPoolExecutor(max_workers=num_keys) as executor:
        futures = [executor.submit(worker_task, i, API_KEYS[i], chunks[i], metadata_map) for i in range(num_keys)]
        for f in futures: f.result()

    stop_monitor_event.set()
    monitor_thread.join()

    # STAGE 6: CONSOLIDATE SHARDS
    elapsed = time.perf_counter() - start_time
    
    worker_files = list(TEMP_WORKER_DIR.glob("worker_*.jsonl"))
    comp_files = list(TEMP_WORKER_DIR.glob("completed_*.txt"))
    total_shards = len(worker_files) + len(comp_files)
    
    if total_shards > 0:
        processed_shards = 0
        with open(OUTPUT_PATH, "a", encoding="utf-8") as out_jsonl, open(COMPLETED_PATH, "a", encoding="utf-8") as out_comp:
            for w_file in worker_files:
                with open(w_file, "r", encoding="utf-8") as f:
                    for line in f: out_jsonl.write(line)
                w_file.unlink()
                processed_shards += 1
                pct = (processed_shards / total_shards) * 100
                print(f"\r[STAGE 6/6] Consolidate {render_bar(pct)} | Merging {w_file.name}...{' '*15}", end="", flush=True)

            for c_file in comp_files:
                with open(c_file, "r", encoding="utf-8") as f:
                    for line in f: out_comp.write(line)
                c_file.unlink()
                processed_shards += 1
                pct = (processed_shards / total_shards) * 100
                print(f"\r[STAGE 6/6] Consolidate {render_bar(pct)} | Merging {c_file.name}...{' '*15}", end="", flush=True)
                
        print(f"\r[STAGE 6/6] Consolidate {render_bar(100.0)} | Shards fully merged.{' '*25}")
    else:
        print(f"[STAGE 6/6] Consolidate {render_bar(100.0)} | No temp shards to merge.{' '*25}")

    if TEMP_WORKER_DIR.exists() and not any(TEMP_WORKER_DIR.iterdir()):
        try: TEMP_WORKER_DIR.rmdir()
        except OSError: pass

    # 7. METRICS & BENCHMARK
    effective_rate = global_api_calls / elapsed if elapsed > 0 else 0
    est_single_key = global_api_calls * (REQUEST_INTERVAL + 0.12)
    obs_speedup = (est_single_key / elapsed) if elapsed > 0 else 1.0

    print("\n" + "=" * 55)
    print("EXTRACTION BENCHMARK REPORT")
    print("=" * 55)
    print(f"Addresses processed       : {global_addresses_done:,}")
    print(f"Actions extracted         : {global_records_extracted:,}")
    print(f"Total API calls executed  : {global_api_calls:,}")
    print(f"Runtime                   : {elapsed:.2f}s ({elapsed / 60:.2f} min)")
    print(f"Throughput                : {effective_rate:.2f} calls/sec")
    print(f"Observed speedup          : {obs_speedup:.2f}x (Theoretical max: {num_keys}.00x)")
    print("=" * 55 + "\n")

if __name__ == "__main__":
    main()
