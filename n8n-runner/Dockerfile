FROM ghcr.io/n8n-io/runners:2.17.2
USER root
RUN cd /opt/runners/task-runner-python && uv pip install pytz pyyaml requests
COPY n8n-task-runners.json /etc/n8n-task-runners.json
USER runner
