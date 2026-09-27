FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 TIKTOKEN_CACHE_DIR=/app/.tiktoken

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

COPY *.py ./

# `docker run -e API_KEY=... <image>` and `docker run -e API_KEY=... <image> main.py` both work.
ENTRYPOINT ["python"]
CMD ["main.py"]
