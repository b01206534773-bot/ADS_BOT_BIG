FROM python:3.11-bullseye

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright + Chromium + required system dependencies
RUN python -m playwright install --with-deps chromium

# Copy application code
COPY . .

# Run the bot
CMD ["python", "start.py"]
