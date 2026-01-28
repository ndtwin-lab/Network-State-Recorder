# Network State Recorder － Installation Manual

## Table of Contents

- [Rquirements](#requirements)
- [Installation](#installation)

## Requirements

- **Python**: 3.8 or higher
- **NDTwin Server**: Running and accessible
- **Ryu**: For setting flow rule to switches
- **Python Dependencies**:
  - `nornir` - Network automation framework
  - `loguru` - Logging library
  - `orjson` - Fast JSON library
  - `requests` - HTTP library
  
## Installation

### Step 1: Install Python Dependencies

```bash
pip install nornir loguru orjson requests
```

### Step 2: Make Scripts Executable

```bash
chmod +x start_network_state_recorder.sh stop_network_state_recorder.sh
```

### Step 3: Verify Installation

Ensure NDTwin server is running, then test the configuration:

```bash
python3 network_state_recorder.py
```

Press `Ctrl+C` to stop if running successfully.

