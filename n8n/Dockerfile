FROM ghcr.io/n8n-io/n8n:2.39.0
USER root
# Reinstall apk-tools
COPY apk-tools-static-2.14.9-r3.apk /tmp
RUN tar -xzf /tmp/apk-tools-static-2.14.9-r3.apk && \
    rm /tmp/apk-tools-static-2.14.9-r3.apk && \
    ls -la sbin/
RUN ./sbin/apk.static add --no-cache python3 make g++ py3-pip
ENV npm_config_python=/usr/bin/python3
RUN npm install gray-matter markdown-it n8n-nodes-fs n8n-nodes-markdown-to-json n8n-nodes-obsidian n8n-nodes-execute-command-plus @n8n/task-runner
RUN pip install structlog pydantic todoist-api-python pyyaml pytz requests --break-system-packages
USER 1000
