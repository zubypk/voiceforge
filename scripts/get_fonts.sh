#!/bin/sh
# Download Noto fonts so slide text renders in more scripts (Arabic, Hindi, Thai, Bengali, ... and Chinese/Japanese/Korean).
# Usage: sh scripts/get_fonts.sh [target_dir]      (default: ./fonts, which the app reads; or set VF_FONT_DIR)
# Safe to re-run; skips files that already exist. Needs internet. CJK adds ~32 MB; pass CJK=0 to skip it.
set -u
DIR="${1:-$(dirname "$0")/../fonts}"
mkdir -p "$DIR"
BASE="https://raw.githubusercontent.com/notofonts/notofonts.github.io/main/fonts"
get() {  # family file-stem
  for w in Regular Bold; do
    out="$DIR/$2-$w.ttf"
    [ -s "$out" ] && continue
    curl -fsSL --retry 2 -o "$out" "$BASE/$1/hinted/ttf/$2-$w.ttf" && echo "ok   $2-$w" || { rm -f "$out"; echo "FAIL $2-$w"; }
  done
}
for f in NotoSans NotoSansArabic NotoNaskhArabic NotoSansHebrew NotoSansDevanagari NotoSansBengali NotoSansThai NotoSansTamil \
         NotoSansGujarati NotoSansTelugu NotoSansKannada NotoSansMalayalam NotoSansSinhala NotoSansKhmer NotoSansLao \
         NotoSansMyanmar NotoSansGeorgian NotoSansEthiopic NotoSansGurmukhi; do
  get "$f" "$f"
done
if [ "${CJK:-1}" = "1" ]; then
  for w in Regular Bold; do
    out="$DIR/NotoSansCJKsc-$w.otf"
    [ -s "$out" ] && continue
    curl -fsSL --retry 2 -o "$out" "https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-$w.otf" \
      && echo "ok   NotoSansCJKsc-$w" || { rm -f "$out"; echo "FAIL NotoSansCJKsc-$w"; }
  done
fi
echo "fonts in $DIR: $(ls "$DIR" | wc -l) files"
