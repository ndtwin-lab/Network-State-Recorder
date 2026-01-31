#!/bin/bash

# Set display_on_console to false in recorder_setting.yaml
SETTING_FILE="./setting/recorder_setting.yaml"
if [ -f "$SETTING_FILE" ]; then
    sed -i 's/\(display_on_console:\s*\).*/\1false/' "$SETTING_FILE"
fi

nohup python3 network_state_recorder.py &