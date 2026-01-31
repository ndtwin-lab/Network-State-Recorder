#!/bin/bash
echo $(pgrep -f network_state_recorder.py)
sudo kill -15 $(pgrep -f network_state_recorder.py)

# Set display_on_console to true in recorder_setting.yaml
SETTING_FILE="./setting/recorder_setting.yaml"
if [ -f "$SETTING_FILE" ]; then
    sed -i 's/\(display_on_console:\s*\).*/\1true/' "$SETTING_FILE"
fi