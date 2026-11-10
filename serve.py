"""
대시보드 로컬 서버: public/ 을 http://127.0.0.1:8765 로 연다.
수집 데이터는 재배포 금지라 이 컴퓨터에서만 접속되게 127.0.0.1 에만 붙는다.

  python3 serve.py            # 기본 포트 8765
  python3 serve.py 9000
"""

import functools
import os
import http.server
import sys
from pathlib import Path

ROOT = Path(__file__).parent / 'public'


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get('PORT') or 8765)   # PORT: 미리보기 도구가 정해 주는 포트
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(('127.0.0.1', port), handler) as httpd:
        print(f'http://127.0.0.1:{port}  (종료: Ctrl+C)', flush=True)
        httpd.serve_forever()


if __name__ == '__main__':
    main()
