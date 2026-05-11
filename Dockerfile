FROM apify/actor-python-playwright:3.11-1.59.0

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
CMD ["python", "-m", "src.main"]
