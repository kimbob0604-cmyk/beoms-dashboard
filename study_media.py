"""
Beom's Study 공개 이미지 정리: study_src/media_raw/<키>/raw.* → study/media/<키>.png

  python3 study_media.py          # manifest 에 있는 것 중 원본이 있는 것만 정리

- study/media/manifest.json 에 이미지마다 출처(source·page·url)·저작자·라이선스를 손으로 적어 둔다.
  위키미디어·RCSB PDB 처럼 재사용이 허용된 이미지만 쓴다(퍼블릭 도메인·CC0·CC BY). CC BY 는 저작자 표기가 조건이다.
- "kind": "photo" 이면 JPEG(품질 86), 아니면 PNG.
- 정리: 흰 여백 자르기 → 폭 1000px 미만이면 2배 확대(Lanczos) → 약한 선명화. manifest 의 w·h·mods 를 채운다.
- 받은 파일은 데이터로만 다룬다(이미지 디코딩만, 실행 없음). 원본 폴더는 study_src(커밋 안 함), 정리본은 study/media(커밋).
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'study_src' / 'media_raw'
OUT = ROOT / 'study' / 'media'


def tidy(src: Path, dst: Path, photo=False):
    im = Image.open(src)
    im.load()
    im = im.convert('RGB')
    mods = []
    bg = Image.new('RGB', im.size, (255, 255, 255))
    box = ImageChops.difference(im, bg).convert('L').point(lambda v: 255 if v > 14 else 0).getbbox()
    if box and (box[2] - box[0]) * (box[3] - box[1]) < im.width * im.height * 0.97:
        pad = 10
        im = im.crop((max(box[0] - pad, 0), max(box[1] - pad, 0), min(box[2] + pad, im.width), min(box[3] + pad, im.height)))
        mods.append('여백 자름')
    if im.width < 1000:
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.2, percent=50, threshold=2))
        mods.append('2배 확대')
    elif im.width > 1800:
        im = im.resize((1800, round(im.height * 1800 / im.width)), Image.LANCZOS)
        mods.append('축소')
    if photo:     # 현미경·조직 사진은 JPEG 가 훨씬 가볍다
        im.save(dst, quality=86, optimize=True, progressive=True)
    else:
        im.save(dst, optimize=True)
    return im.size, mods


def main():
    for mf in sorted(OUT.glob('manifest*.json')):     # manifest.json + 섹터별 manifest-<섹터>.json
        tidy_manifest(mf)
    return 0


def tidy_manifest(mf: Path):
    man = json.loads(mf.read_text(encoding='utf-8'))
    for key, m in man.items():
        if key.startswith('_'):
            continue
        raws = sorted((RAW / key).glob('raw*')) if (RAW / key).exists() else []
        if not raws:
            print(f'{key}: 원본 없음 (study_src/media_raw/{key}/raw.*)')
            continue
        photo = m.get('kind') == 'photo'
        m['file'] = f'{key}.{"jpg" if photo else "png"}'
        for old in OUT.glob(f'{key}.*'):
            if old.name != m['file']:
                old.unlink()
        (w, h), mods = tidy(raws[0], OUT / m['file'], photo)
        m.update({'w': w, 'h': h, 'mods': ' · '.join(mods)})
        print(f'{key}: {w}x{h} ({m["mods"] or "그대로"}) · {m["license"]}')
    mf.write_text(json.dumps(man, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    sys.exit(main())
