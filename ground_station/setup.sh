#!/bin/bash
# RC Ucak Yer Istasyonu - Steam Deck Kurulum

set -e

echo "=== RC Ucak Yer Istasyonu Kurulumu ==="

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Python kontrolu
if ! command -v python3 &> /dev/null; then
    echo "HATA: Python3 bulunamadi"
    echo "Steam Deck'te: sudo pacman -S python python-pip"
    exit 1
fi

# Sanal ortam olustur
if [ ! -d "venv" ]; then
    echo "Sanal ortam olusturuluyor..."
    python3 -m venv venv
fi

# Bagimliliklari yukle
echo "Bagimliliklar yukleniyor..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Seri port izni
echo ""
echo "=== NOT: Seri port izni icin ==="
echo "  sudo usermod -aG uucp \$USER"
echo "  (veya) sudo usermod -aG dialout \$USER"
echo "  Ardinden oturumu kapatip acin."
echo ""

echo "=== Kurulum tamamlandi ==="
echo "Baslatmak icin: ./run.sh"
