FROM alpine:3.20

RUN apk add --no-cache ffmpeg

COPY stream.sh /usr/local/bin/stream.sh
RUN chmod +x /usr/local/bin/stream.sh

ENTRYPOINT ["/usr/local/bin/stream.sh"]
