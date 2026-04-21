#!/usr/bin/env python3
import sys
import os

sys.path.insert(0, '/app')

os.execvp("litellm", ["litellm", "--config", "/app/config.yaml", "--port", "4000", "--host", "0.0.0.0"])
