FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# build-essential to compile pyswisseph; curl to fetch ephemeris files
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Chiron ephemeris BEFORE COPY (separate layer — cached between builds).
# seas_18.se1 covers asteroids (incl. Chiron) for years 1800-2400 (~223 KB).
RUN mkdir -p /app/ephe && \
    curl -fL "https://github.com/aloistr/swisseph/raw/master/ephe/seas_18.se1" \
         -o /app/ephe/seas_18.se1 && \
    echo "seas_18.se1: $(stat -c%s /app/ephe/seas_18.se1) bytes"

COPY . .

RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
