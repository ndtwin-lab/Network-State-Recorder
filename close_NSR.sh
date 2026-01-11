#!/bin/bash
echo $(pgrep -f NSR.py)
sudo kill -15 $(pgrep -f NSR.py)