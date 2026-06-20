#!/bin/bash
# setup.sh — Serverga birinchi marta deploy qilish uchun
# Ishlatish: bash setup.sh

set -e  # Xato bo'lsa to'xta

echo "======================================"
echo "  Kino Bot — Server Setup"
echo "======================================"

# 1. Docker o'rnatilganligini tekshirish
if ! command -v docker &>/dev/null; then
    echo "[1/4] Docker o'rnatilmoqda..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
else
    echo "[1/4] Docker mavjud: $(docker --version)"
fi

# 2. Docker Compose tekshirish
if ! command -v docker compose &>/dev/null; then
    echo "[2/4] Docker Compose o'rnatilmoqda..."
    apt-get install -y docker-compose-plugin 2>/dev/null || \
    curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
         -o /usr/local/bin/docker-compose && chmod +x /usr/local/bin/docker-compose
else
    echo "[2/4] Docker Compose mavjud."
fi

# 3. .env fayli tekshirish
if [ ! -f ".env" ]; then
    echo ""
    echo "[3/4] .env fayli topilmadi!"
    echo "      .env.example faylini ko'rib, .env yarating:"
    echo "      cp .env.example .env && nano .env"
    exit 1
else
    echo "[3/4] .env fayli mavjud ✓"
fi

# 4. Data papkasi
mkdir -p data
echo "[4/4] data/ papkasi tayyor ✓"

# 5. Build va ishga tushirish
echo ""
echo "Bot build qilinmoqda va ishga tushirilmoqda..."
docker compose down 2>/dev/null || true
docker compose build --no-cache
docker compose up -d

echo ""
echo "======================================"
echo "  ✅ Bot muvaffaqiyatli ishga tushdi!"
echo "  Loglarni ko'rish: docker compose logs -f"
echo "  To'xtatish:       docker compose down"
echo "======================================"
