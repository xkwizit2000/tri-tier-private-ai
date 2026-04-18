#!/usr/bin/env python3
import sys
import os
import asyncio

sys.path.insert(0, '/app')

import litellm
from litellm.proxy.proxy_server import app, initialize

async def startup():
    await initialize(config="/app/config.yaml")

    from router_hook import proxy_handler_instance
    from litellm.integrations.custom_logger import CustomLogger

    # Use the correct registration method
    litellm.logging_callback_manager.add_litellm_callback(proxy_handler_instance)
    print(f"[PrivacyRouter] Registered via logging_callback_manager")
    print(f"[PrivacyRouter] Callbacks: {litellm.callbacks}")

asyncio.run(startup())

import uvicorn
uvicorn.run(app, host="0.0.0.0", port=4000)
