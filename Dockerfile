FROM python:3.11-slim

# Install system dependencies required by Playwright
RUN apt-get update && apt-get install -y \
    # X11 and graphics libraries
    libxcb1 \
    libx11-6 \
    libxrandr2 \
    libxinerama1 \
    libxi6 \
    libxext6 \
    libxcursor1 \
    libxkbcommon0 \
    libxkbraw1 \
    libxkbfile1 \
    # Graphics rendering
    libglib2.0-0 \
    libdrm2 \
    libgbm1 \
    libcairo2 \
    libpango-1.0-0 \
    # Font rendering
    fontconfig \
    fonts-dejavu \
    # System libraries
    dbus \
    libnss3 \
    libnssutil3 \
    libsmime3 \
    libnspr4 \
    libgdk-pixbuf2.0-0 \
    libgtk-3-0 \
    # Audio
    libasound2 \
    # X11 extras
    xvfb \
    # Build tools
    build-essential \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

COPY . .

CMD ["python", "start.py"]

