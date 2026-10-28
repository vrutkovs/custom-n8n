FROM ghcr.io/n8n-io/runners:3.0.1
USER root
RUN cd /opt/runners/task-runner-python && uv pip install pytz pyyaml requests
COPY n8n-task-runners.json /etc/n8n-task-runners.json
USER runner
