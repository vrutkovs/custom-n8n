FROM ghcr.io/n8n-io/runners:2.16.0
USER root
RUN pip install pytz pyyaml requests
COPY n8n-task-runners.json /etc/n8n-task-runners.json
USER runner
