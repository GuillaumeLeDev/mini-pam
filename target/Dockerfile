FROM alpine:3.19

RUN apk add --no-cache openssh bash python3 sudo

# Create admin user (password will be overwritten by fetch_secret.py at startup)
RUN adduser -D -s /bin/bash admin && \
    echo "admin:placeholder" | chpasswd && \
    echo "admin ALL=(root) NOPASSWD: /usr/sbin/chpasswd" > /etc/sudoers.d/rotation

# Generate SSH host keys
RUN ssh-keygen -A

COPY sshd_config /etc/ssh/sshd_config
COPY fetch_secret.py /app/fetch_secret.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 2222

CMD ["/entrypoint.sh"]
