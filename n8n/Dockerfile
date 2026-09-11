FROM node:24-alpine3.24 AS deps
RUN apk add --no-cache python3 make g++
RUN npm install --prefix /deps \
    gray-matter \
    markdown-it \
    n8n-nodes-fs \
    n8n-nodes-markdown-to-json \
    n8n-nodes-obsidian \
    n8n-nodes-execute-command-plus

FROM ghcr.io/n8n-io/n8n:2.39.4
USER root
COPY --from=deps /deps/node_modules /home/node/node_modules
COPY apk-tools-static-2.14.9-r3.apk /tmp
RUN tar -xzf /tmp/apk-tools-static-2.14.9-r3.apk && \
    rm /tmp/apk-tools-static-2.14.9-r3.apk && \
    ls -la sbin/
RUN ./sbin/apk.static add --no-cache python3 py3-pip
RUN pip install \
    structlog \
    pydantic \
    todoist-api-python \
    pyyaml \
    pytz \
    requests \
    --break-system-packages
USER 1000
