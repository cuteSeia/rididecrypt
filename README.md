# decryptor

받은 리디 책을 복호화해 EPUB과 PDF로 저장합니다.

GUI에서 복호화를 실행하면 저장 폴더에 `epub/<시리즈>/`와 `pdf/<시리즈>/`를 만들고, 각 시리즈 폴더에 권별 파일을 저장합니다. EPUB과 PDF가 모두 생성되면 중간 이미지 폴더를 삭제합니다. 파일 이름이 `!000`인 이미지는 표지로 지정하고 PDF 첫 페이지에도 배치합니다.

EPUB은 WebP 원본 이미지를 그대로 담습니다. PDF는 WebP 이미지를 JPEG 품질 95로 변환한 뒤 넣어 생성 시간을 줄입니다.

```bash
uv sync
uv run decryptor
```

macOS 앱과 배포용 ZIP을 만들려면 프로젝트 루트에서 실행합니다.

```bash
./scripts/build_macos.sh
```

결과물은 `dist/RidiDecryptor.app`과 `dist/RidiDecryptor-macos-arm64.zip`입니다.
앱 아이콘 원본은 `packaging/rididecryptor.svg`이며 빌드할 때 `.icns`로 자동 변환합니다.
