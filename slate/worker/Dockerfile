# SLATE worker image: Playwright + Chromium + the worker script. Nothing else.
# No API keys, no model, no shell tools for the agent: it only speaks the JSON action channel.
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
RUN pip install --no-cache-dir playwright==1.58.0
COPY agent_worker.py /opt/slate/agent_worker.py
USER pwuser
ENTRYPOINT ["python3", "-u", "/opt/slate/agent_worker.py"]
