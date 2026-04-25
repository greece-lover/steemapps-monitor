FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monitor.py .

# Run as non-root for defense in depth — the script needs no privileged
# capabilities, only outbound HTTPS.
RUN useradd --create-home --shell /usr/sbin/nologin participant \
    && chown -R participant:participant /app
USER participant

CMD ["python", "-u", "monitor.py"]
