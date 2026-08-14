FROM alpine:3.20

COPY cleanup.sh /usr/local/bin/cleanup.sh
RUN chmod +x /usr/local/bin/cleanup.sh

ENTRYPOINT ["/usr/local/bin/cleanup.sh"]
