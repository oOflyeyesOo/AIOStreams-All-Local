FROM docker:29-cli
RUN apk add --no-cache python3 py3-yaml
COPY tools/release_manager.py /opt/aio/release_manager.py
WORKDIR /workspace
ENTRYPOINT ["python3", "/opt/aio/release_manager.py"]
