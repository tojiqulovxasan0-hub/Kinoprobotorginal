# Python 3.12 slim — kichik hajm, tez yuklanadi
FROM python:3.12-slim

# Muhit o'zgaruvchilari
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Ishchi papka
WORKDIR /app

# Avval faqat requirements — Docker cache ishlashi uchun
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Barcha fayllarni ko'chirish
COPY . .

# Bot ma'lumotlar bazasi uchun papka
RUN mkdir -p /app/data

# Botni ishga tushirish
CMD ["python", "main.py"]
