# Network State Recorder — Development Guide

This guide provides developers with a comprehensive understanding of the NSR (Network State Recorder) architecture and instructions for extending its functionality.

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Code Structure](#code-structure)
- [Data Flow](#data-flow)
- [Global Variables](#global-variables)
- [Core Functions](#core-functions)
- [Thread Synchronization](#thread-synchronization)
- [Adding New Data Sources](#adding-new-data-sources)
- [Adding New Output Formats](#adding-new-output-formats)
- [Best Practices](#best-practices)

## Architecture Overview

NSR follows a **multi-threaded producer-consumer pattern** with the following components:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              NSR Architecture                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐        │
│   │   NDTwin     │         │   NDTwin     │         │  New Source  │        │
│   │  Flow API    │         │  Graph API   │         │    (...)     │        │
│   └──────┬───────┘         └──────┬───────┘         └──────┬───────┘        │
│          │                        │                        │                │
│          ▼                        ▼                        ▼                │
│   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐        │
│   │ request_data │         │ request_data │         │ request_data │        │
│   │   Thread     │         │   Thread     │         │   Thread     │        │
│   └──────┬───────┘         └──────┬───────┘         └──────┬───────┘        │
│          │                        │                        │                │
│          ▼                        ▼                        ▼                │
│   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐        │
│   │   QUEUES     │         │   QUEUES     │         │   QUEUES     │        │
│   │ ["flowinfo"] │         │ ["graphinfo"]│         │ ["newinfo"]  │        │
│   └──────┬───────┘         └──────┬───────┘         └──────┬───────┘        │
│          │                        │                        │                │
│          ▼                        ▼                        ▼                │
│   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐        │
│   │  write_data  │         │  write_data  │         │  write_data  │        │
│   │   Thread     │         │   Thread     │         │   Thread     │        │
│   └──────┬───────┘         └──────┬───────┘         └──────┬───────┘        │
│          │                        │                        │                │
│          └────────────────────────┼────────────────────────┘                │
│                                   ▼                                         │
│                          ┌──────────────┐                                   │
│                          │   ZIP_PATH   │                                   │
│                          │    Queue     │                                   │
│                          └──────┬───────┘                                   │
│                                 │                                           │
│                                 ▼                                           │
│                          ┌──────────────┐                                   │
│                          │zip_json_files│                                   │
│                          │   Thread     │                                   │
│                          └──────┬───────┘                                   │
│                                 │                                           │
│                                 ▼                                           │
│                          ┌──────────────┐                                   │
│                          │  ZIP Files   │                                   │
│                          │  (Storage)   │                                   │
│                          └──────────────┘                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Roles

| Component | Role | Thread Type |
|-----------|------|-------------|
| `request_data` | **Producer** - Fetches data from APIs and pushes to queues | Worker Thread |
| `write_data` | **Consumer/Producer** - Reads from data queues, writes JSON files, pushes to ZIP queue | Worker Thread |
| `zip_json_files` | **Consumer** - Reads from ZIP queue, compresses files | Worker Thread |
| `zipper` | Compression worker | Process (via ProcessPoolExecutor) |

## Code Structure

```
network_state_recorder.py
├── Imports & License Header
├── Global Constants
│   ├── FLOWINFO_URL, GRAPHINFO_URL    # API endpoints
│   ├── REQ_INTERVAL, STORAGE_INTERVAL # Timing configurations
│   └── DIR                            # Output directory
├── Global State Variables
│   ├── THREADS                        # Thread registry
│   ├── QUEUES                         # Named queues dictionary
│   ├── ZIP_PATH                       # Compression queue
│   ├── STOP_EVENT                     # Shutdown signal
│   └── *_FINAL_EVENT                  # Per-source completion signals
├── Compression Functions
│   ├── zipper()                       # Single file compression
│   └── zip_json_files()               # Compression thread loop
├── Data Pipeline Functions
│   ├── write_data()                   # Queue-to-file writer
│   └── request_data()                 # API data fetcher
├── Utility Functions
│   ├── terminate()                    # Graceful shutdown
│   ├── ndtwin_alive()                 # Health check
│   └── logger_config()                # Logging setup
├── Application Entry
│   └── start()                        # Main initialization
└── Main Block
    └── Signal handlers + start()
```

## Data Flow

### 1. Data Fetching Stage

```python
# request_data() fetches from API every REQ_INTERVAL seconds
response = requests.get(url, params=params)
data = {"timestamp": current_timestamp_ms, ...response_data}
QUEUES[queue_name].put(data)
```

### 2. Data Writing Stage

```python
# write_data() consumes from queue and writes to JSON file
item = QUEUES[queue_name].get()
f.write(orjson.dumps(item))
# After STORAGE_INTERVAL, add file to compression queue
ZIP_PATH.put(file_name)
```

### 3. Compression Stage

```python
# zip_json_files() monitors ZIP_PATH and compresses in parallel
file_path = ZIP_PATH.get()
executor.submit(zipper, file_path)
```

## Global Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `THREADS` | `List[Thread]` | Registry of all spawned threads for cleanup |
| `QUEUES` | `Dict[str, Queue]` | Named queues for each data source |
| `ZIP_PATH` | `Queue` | Files pending compression |
| `STOP_EVENT` | `threading.Event` | Signal for graceful shutdown |
| `FLOW_FINAL_EVENT` | `threading.Event` | Signals flowinfo writer completion |
| `GRAPH_FINAL_EVENT` | `threading.Event` | Signals graphinfo writer completion |

## Core Functions

### `request_data(url, queue_name, params=None)`

**Purpose**: Periodically fetch data from an API endpoint.

**Key Logic**:
1. Loop until `STOP_EVENT` is set
2. Send GET request to the specified URL
3. Add timestamp to response data
4. Push to named queue
5. Sleep for remaining interval time

### `write_data(queue_name)`

**Purpose**: Write queued data to JSON files with time-based rotation.

**Key Logic**:
1. Create new JSON file every `STORAGE_INTERVAL` seconds
2. Continuously drain the named queue
3. Write each item as newline-delimited JSON
4. Add completed file to `ZIP_PATH` for compression
5. Set completion event on shutdown

### `zip_json_files()`

**Purpose**: Background compression of JSON files.

**Key Logic**:
1. Monitor `ZIP_PATH` queue for files
2. Use `ProcessPoolExecutor` for parallel compression
3. Wait for all `*_FINAL_EVENT` signals before final cleanup

### `zipper(file_path)`

**Purpose**: Compress a single JSON file to ZIP format.

**Key Logic**:
1. Create ZIP archive with deflate compression
2. Remove original JSON file after successful compression

## Thread Synchronization

### Shutdown Sequence

```
1. SIGINT/SIGTERM received
      │
      ▼
2. terminate() called
      │
      ▼
3. STOP_EVENT.set()
      │
      ├──► request_data threads exit loops
      │
      ├──► write_data threads exit loops
      │         │
      │         ▼
      │    Set *_FINAL_EVENT for each data source
      │
      └──► zip_json_files waits for all FINAL_EVENTs
                  │
                  ▼
           Process remaining ZIP_PATH items
                  │
                  ▼
4. All threads join()
      │
      ▼
5. Application exits
```

### Adding a New Final Event

When adding a new data source, you must create a corresponding `*_FINAL_EVENT`:

```python
# At the top with other events
NEW_SOURCE_FINAL_EVENT = threading.Event()

# In write_data(), set the event on exit
if queue_name == "new_source":
    NEW_SOURCE_FINAL_EVENT.set()

# In zip_json_files(), wait for it
while not FLOW_FINAL_EVENT.is_set() or not GRAPH_FINAL_EVENT.is_set() or not NEW_SOURCE_FINAL_EVENT.is_set():
    time.sleep(REQ_INTERVAL)
```

## Adding New Data Sources

Follow these steps to add a new NDTwin API endpoint or external data source:

### Step 1: Define the API Endpoint

```python
# Add near the top with other URL constants
NEW_SOURCE_URL = "/ndt/get_new_data"
```

### Step 2: Create a Final Event

```python
# Add with other event definitions
NEW_SOURCE_FINAL_EVENT = threading.Event()
```

### Step 3: Update `request_data()` Data Formatting

```python
# In request_data(), add handling for the new queue_name
if queue_name == "flowinfo":
    data['flowinfo'] = response.json()
elif queue_name == "graphinfo":
    data = {**data, **response.json()}
elif queue_name == "new_source":  # Add this block
    data['new_source'] = response.json()
```

### Step 4: Update `write_data()` Final Event

```python
# In write_data(), set the appropriate final event
if queue_name == "flowinfo":
    FLOW_FINAL_EVENT.set()
elif queue_name == "graphinfo":
    GRAPH_FINAL_EVENT.set()
elif queue_name == "new_source":  # Add this block
    NEW_SOURCE_FINAL_EVENT.set()
```

### Step 5: Update `zip_json_files()` to Wait for New Event

```python
# In zip_json_files(), update the wait condition
while not FLOW_FINAL_EVENT.is_set() or not GRAPH_FINAL_EVENT.is_set() or not NEW_SOURCE_FINAL_EVENT.is_set():
    logger.debug("Waiting for final files to be ready for zipping...")
    time.sleep(REQ_INTERVAL)
```

### Step 6: Create and Register Threads in `start()`

```python
# In start(), after reading config
NEW_SOURCE_URL = ndtwin_kernel + NEW_SOURCE_URL

# Create the threads
new_source_thread = threading.Thread(target=request_data, args=(NEW_SOURCE_URL, 'new_source'))
new_source_write_thread = threading.Thread(target=write_data, args=('new_source',))

# Register them
THREADS.append(new_source_thread)
THREADS.append(new_source_write_thread)
```

### Complete Example: Adding Port Statistics

```python
# Step 1: Add URL constant
PORTSTAT_URL = "/ndt/get_port_statistics"

# Step 2: Add final event
PORTSTAT_FINAL_EVENT = threading.Event()

# Step 3: In request_data()
elif queue_name == "portstat":
    data['port_statistics'] = response.json()

# Step 4: In write_data()
elif queue_name == "portstat":
    PORTSTAT_FINAL_EVENT.set()

# Step 5: In zip_json_files()
while not FLOW_FINAL_EVENT.is_set() or not GRAPH_FINAL_EVENT.is_set() or not PORTSTAT_FINAL_EVENT.is_set():
    ...

# Step 6: In start()
PORTSTAT_URL = ndtwin_kernel + PORTSTAT_URL
portstat_thread = threading.Thread(target=request_data, args=(PORTSTAT_URL, 'portstat'))
portstat_write_thread = threading.Thread(target=write_data, args=('portstat',))
THREADS.append(portstat_thread)
THREADS.append(portstat_write_thread)
```

## Adding New Output Formats

### Example: Adding CSV Output

To support CSV output alongside JSON:

```python
import csv

def write_data_csv(queue_name, fields):
    """
    Write data from a named queue to CSV files at regular intervals.
    
    Args:
        queue_name (str): The name of the queue to read data from.
        fields (list): List of field names for CSV header.
    """
    global QUEUES, ZIP_PATH
    file_name = ""
    while not STOP_EVENT.is_set():
        start_time = time.time()
        file_name = f"{DIR}/{datetime.fromtimestamp(start_time).strftime('%Y_%m_%d_%H-%M-%S')}_{queue_name}.csv"
        logger.info(f"Storing CSV data from {queue_name} queue to file: {file_name}...")
        
        with open(file_name, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['timestamp'] + fields)
            writer.writeheader()
            
            while time.time() - start_time < STORAGE_INTERVAL and not STOP_EVENT.is_set():
                while not QUEUES[queue_name].empty() and not STOP_EVENT.is_set():
                    item = QUEUES[queue_name].get(timeout=0.1)
                    # Flatten the data for CSV
                    row = {'timestamp': item['timestamp']}
                    # Add your field extraction logic here
                    writer.writerow(row)
                    QUEUES[queue_name].task_done()
                time.sleep(REQ_INTERVAL - 0.1)
            
            ZIP_PATH.put(file_name)
    
    # Handle final event similar to write_data()
```

### Example: Adding Database Storage

```python
import sqlite3

def write_data_db(queue_name, db_path, table_name):
    """
    Write data from a named queue to a SQLite database.
    
    Args:
        queue_name (str): The name of the queue to read data from.
        db_path (str): Path to the SQLite database file.
        table_name (str): Name of the table to insert data into.
    """
    global QUEUES
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    while not STOP_EVENT.is_set():
        while not QUEUES[queue_name].empty() and not STOP_EVENT.is_set():
            item = QUEUES[queue_name].get(timeout=0.1)
            # Insert your database insertion logic here
            cursor.execute(
                f"INSERT INTO {table_name} (timestamp, data) VALUES (?, ?)",
                (item['timestamp'], orjson.dumps(item).decode())
            )
            conn.commit()
            QUEUES[queue_name].task_done()
        time.sleep(REQ_INTERVAL)
    
    conn.close()
```

## Best Practices

### 1. Always Use `STOP_EVENT` for Loop Control

```python
# Good
while not STOP_EVENT.is_set():
    # do work
    if STOP_EVENT.wait(timeout=sleep_time):
        break

# Bad - won't respond to shutdown signals
while True:
    # do work
    time.sleep(sleep_time)
```

### 2. Register All Threads in `THREADS` List

```python
# Always append new threads for proper cleanup
my_thread = threading.Thread(target=my_function)
THREADS.append(my_thread)
```

### 3. Create Final Events for Each Data Source

This ensures the compression thread waits for all data to be written before final cleanup.

### 4. Use Queue Timeouts

```python
# Good - allows checking STOP_EVENT
item = queue.get(timeout=0.1)

# Bad - blocks forever, won't respond to shutdown
item = queue.get()
```

### 5. Handle Exceptions in Threads

```python
def my_thread_function():
    try:
        while not STOP_EVENT.is_set():
            # do work
    except Exception as e:
        logger.error(f"Error in thread: {e}")
    finally:
        logger.info("Thread exiting...")
```

### 6. Use Appropriate Log Levels

| Level | Use Case |
|-------|----------|
| `TRACE` | Detailed data content, per-item logging |
| `DEBUG` | Flow control messages, queue operations |
| `INFO` | Major state changes, file operations |
| `WARNING` | Recoverable issues, empty responses |
| `ERROR` | Failures, exceptions |

### 7. Configuration Best Practices

When adding new configurable parameters:

```python
# In start(), read from config with sensible defaults
MY_PARAM = config.inventory.hosts["Recorder"].data.get("my_param", default_value)
```

Update `setting/recorder_setting.yaml`:

```yaml
Recorder:
  data:
    my_param: value
```

## Testing Your Changes

### 1. Test with Verbose Logging

Set `log_level: "TRACE"` in configuration to see all data flow.

### 2. Use Short Intervals for Testing

```yaml
Recorder:
  data:
    request_interval: 1
    storage_interval: 1  # 1 minute for quick testing
```

### 3. Verify Graceful Shutdown

```bash
# Start NSR
python3 network_state_recorder.py &

# Wait for some data collection
sleep 30

# Send SIGTERM and verify clean exit
kill -15 $!
```

### 4. Check Output Files

```bash
# Verify JSON structure
unzip -p recorded_info/*_flowinfo_json.zip | head -1 | python -m json.tool

# Check file rotation timing
ls -la recorded_info/
```
