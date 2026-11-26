# decryptor

받은 리디 책을 복호화해 EPUB과 PDF로 저장합니다.

macOS GUI는 Cocoa(PyObjC), Linux GUI는 Qt(PySide6)를 사용합니다. 복호화 결과는 `epub/<시리즈>/`와 `pdf/<시리즈>/`에 저장하고, 두 파일이 만들어지면 중간 이미지 폴더를 삭제합니다. `!000` 이미지는 표지로 사용합니다.

```bash
uv sync
uv run decryptor
```

macOS 앱을 패키징하려면 실행합니다.

```bash
./scripts/build_macos.sh
```

결과물은 `dist/RidiDecryptor.app`과 `dist/RidiDecryptor-macos-arm64.zip`입니다.
