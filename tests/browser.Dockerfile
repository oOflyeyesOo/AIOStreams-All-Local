FROM python:3.11-slim AS media
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /media && ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=320x180:rate=24 -f lavfi -i sine=frequency=440:sample_rate=44100 -t 12 -c:v libvpx -b:v 300k -c:a libvorbis /media/fixture.webm
COPY tests/media_fixture.py /fixture.py
CMD ["python3", "/fixture.py"]

FROM mcr.microsoft.com/playwright:v1.64.1-noble AS browser
WORKDIR /runner
RUN npm install --ignore-scripts --no-audit --no-fund playwright@1.64.1
COPY tests/browser-playback.acceptance.cjs /runner/check.cjs
CMD ["node", "/runner/check.cjs"]
