# Network State Recorder － User Manual

Network State Recorder (NSR) is a tool that periodically fetches network state data from NDTwin and stores it in JSON files, which are then compressed into ZIP archives for efficient storage. The recorded data can be used for the Visualizer and Web-GUI to replay network states over time.
For installation, you can follow this [link](./installation_guide/README.md)

## Table of Contents

- [Features](#features)
- [Configuration](#configuration)
- [Usage](#usage)
- [Output Files](#output-files)
- [Troubleshooting](#troubleshooting)

## Features

- **Periodic Data Collection**: Automatically fetches network flow and graph data from NDTwin at configurable intervals
- **Efficient Storage**: Compresses JSON data into ZIP archives to minimize disk usage
- **Multi-threaded Architecture**: Concurrent data fetching, writing, and compression for optimal performance
- **Configurable Logging**: Daily log rotation with customizable log levels
- **Graceful Shutdown**: Properly handles SIGINT/SIGTERM signals for clean termination

## Configuration

NSR uses YAML configuration files located in the project directory.

### Main Configuration (`NSR.yaml`)

This file configures the Nornir framework settings:

```yaml
---
inventory:
  plugin: SimpleInventory
  options:
    host_file: "./setting/recorder_setting.yaml"

runner:
  plugin: threaded
  options:
    num_workers: 1

logging:
  enabled: false
```

### Recorder Settings (`setting/recorder_setting.yaml`)

This file contains the NSR-specific configuration:

```yaml
---
Recorder:
  data:
    ndtwin_server: "http://127.0.0.1:8000"
    request_interval: 5    # Data fetch interval in seconds (integer, >= 1)
    storage_interval: 2    # File rotation interval in minutes (integer, >= 1)
    log_level: "DEBUG"     # Logging level: TRACE, DEBUG, INFO, WARNING, ERROR
```

#### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ndtwin_server` | string | `http://127.0.0.1:8000` | URL of the NDTwin server |
| `request_interval` | integer | `5` | How often to fetch data from NDTwin (seconds) |
| `storage_interval` | integer | `2` | How often to rotate and compress JSON files (minutes) |
| `log_level` | string | `DEBUG` | Minimum logging level to record |

#### Log Levels (from most to least verbose)

- `TRACE` - Most detailed logging
- `DEBUG` - Debugging information
- `INFO` - General operational messages
- `WARNING` - Warning messages
- `ERROR` - Error messages only

## Usage

### Starting NSR

#### Option 1: Using the Start Script (Recommended for Background Operation)

```bash
./start_NSR.sh
```

This runs NSR in the background using `nohup`, allowing you to close the terminal while NSR continues running.

#### Option 2: Running Directly (Foreground)

```bash
python3 NSR.py
```

This runs NSR in the foreground. Useful for debugging and monitoring real-time logs.

### Stopping NSR

#### Option 1: Using the Close Script

```bash
./close_NSR.sh
```

This script finds the NSR process and sends a graceful termination signal (SIGTERM).

#### Option 2: Manual Termination

If running in foreground, press `Ctrl+C` to stop.

If running in background:

```bash
# Find the process ID
pgrep -f NSR.py

# Send termination signal
kill -15 <PID>
```

### Checking NSR Status

To verify if NSR is running:

```bash
pgrep -f NSR.py
```

If a process ID is returned, NSR is running.

## Output Files

### Recorded Data Location

All recorded data is stored in the `./recorded_info/` directory (created automatically).

### File Naming Convention

Files are named with the following format:
```
YYYY_MM_DD_HH-MM-SS_<datatype>.json
```

After compression:
```
YYYY_MM_DD_HH-MM-SS_<datatype>_json.zip
```

**Data Types:**
- `flowinfo` - Network flow information from NDTwin
- `graphinfo` - Network graph/topology information from NDTwin

### File Structure

Each JSON file contains newline-delimited JSON records with the following structure:

```json
{"timestamp": 1704067200000, ...}
{"timestamp": 1704067205000, ...}
```

If the JSON file is `flowinfo` type, then the JSON formate is as below:

```json
{"timestamp": 1704067200000, "flowinfo":{[...]}}
```

If the JSON file is `flowinfo` type, then the JSON formate is as below:

```json
{"timestamp": 1704067200000, "edges":{[...]}, "nodes":[{...}]}
```

- `timestamp`: Unix timestamp in milliseconds when data was fetched
- `flowinfo`: A specify key to the original NDTwin API response.
- `edges` & `nodes`: The original NDTwin API response.

### Logs Location

**Notice: The log of NSR is immediately written in the `logs` folder. Thus you will not see any log information in you're terminal**

Log files are stored in the `./logs/` directory with daily rotation:
```
logs/NSR_YYYY-MM-DD.log
```

## Troubleshooting

### Common Issues

#### 1. "NDTwin server is not reachable"

**Cause**: NSR cannot connect to the NDTwin server.

**Solutions**:
- Verify NDTwin server is running
- Check the `ndtwin_server` URL in `setting/recorder_setting.yaml`
- Ensure no firewall is blocking the connection
- Test connectivity: `curl http://<your ip>/ndt/get_detected_flow_data`

#### 2. "No Recorder setting found"

**Cause**: Configuration file is missing or malformed.

**Solutions**:
- Ensure `setting/recorder_setting.yaml` exists
- Verify YAML syntax is correct
- Check that the `Recorder` host is properly defined

#### 3. Permission Denied When Running Scripts

**Cause**: Script files don't have execute permissions.

**Solution**:
```bash
chmod +x start_NSR.sh close_NSR.sh
```

#### 4. Cannot Stop NSR with close_NSR.sh

**Cause**: May require sudo privileges.

**Solution**:
```bash
sudo ./close_NSR.sh
```

Or manually:
```bash
sudo kill -15 $(pgrep -f NSR.py)
```

#### 5. High Disk Usage

**Cause**: Data is being recorded faster than it can be compressed, or storage_interval is too long.

**Solutions**:
- Increase `request_interval` to reduce data volume
- Decrease `storage_interval` to compress files more frequently
- Monitor disk space regularly

### Viewing Logs

To monitor NSR activity in real-time:

```bash
tail -f logs/NSR_$(date +%Y-%m-%d).log
```

## API Endpoints Used

NSR fetches data from the following NDTwin API endpoints:

| Endpoint | Description |
|----------|-------------|
| `/ndt/get_detected_flow_data` | Network flow detection data |
| `/ndt/get_graph_data` | Network topology/graph data |
