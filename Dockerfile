FROM python:3.12-alpine
RUN apk add --no-cache clamav clamav-daemon ffmpeg unzip zip tar p7zip wget gcompat
RUN wget -q https://www.rarlab.com/rar/rarlinux-x64-720.tar.gz -O /tmp/rar.tar.gz \
    && tar -xzf /tmp/rar.tar.gz -C /tmp \
    && cp /tmp/rar/unrar /usr/local/bin/unrar \
    && chmod +x /usr/local/bin/unrar \
    && rm -rf /tmp/rar.tar.gz /tmp/rar
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY templates/ templates/
EXPOSE 5060
CMD ["python", "app.py"]
