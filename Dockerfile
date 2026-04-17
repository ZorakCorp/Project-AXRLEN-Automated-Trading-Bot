FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libsqlite3-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Optional: add Swiss Ephemeris .se1 files under /ephe and set SWISSEPH_EPHE_PATH=/ephe for DE421-class precision.
CMD ["python", "main.py", "run"]
