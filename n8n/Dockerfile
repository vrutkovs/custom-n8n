FROM docker.n8n.io/n8nio/n8n:2.17.2
RUN npm install gray-matter markdown-it n8n-nodes-fs n8n-nodes-markdown-to-json n8n-nodes-obsidian n8n-nodes-execute-command-plus @n8n/task-runner
USER 0
# Reinstall apk-tools
COPY apk-tools-static-2.14.9-r3.apk /tmp
RUN tar -xzf /tmp/apk-tools-static-2.14.9-r3.apk && \
    rm /tmp/apk-tools-static-2.14.9-r3.apk && \
    ls -la sbin/
RUN ./sbin/apk.static add py3-pip && pip install structlog pydantic todoist-api-python pyyaml pytz requests --break-system-packages
USER 1000
