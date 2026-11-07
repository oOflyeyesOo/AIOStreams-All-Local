FROM docker:29-cli
RUN apk add --no-cache python3
COPY docker/controller/controller.py /controller.py
COPY tools/release_manager.py /tools/release_manager.py
ENTRYPOINT ["python3", "-u", "/controller.py"]
