# extract_scenes.py

動画から場面転換ごとにスクリーンショットを自動抽出し、タイムスタンプ付きPDFにまとめて出力するCLIツール。

外部APIやAI課金サービスは一切使用せず、ffmpegによるローカル処理のみで完結する。
(音声文字起こしやNotion転記などの後続工程は本ツールの対象外)

## 必要環境

- Python 3.9 以上
- ffmpeg / ffprobe (シーン検出・フレーム抽出に使用)

### ffmpeg のインストール

```bash
# macOS (Homebrew)
brew install ffmpeg

# Ubuntu / Debian
sudo apt update && sudo apt install -y ffmpeg

# Windows (Chocolatey)
choco install ffmpeg
```

`ffmpeg -version` / `ffprobe -version` が実行できれば準備完了。

### Python依存ライブラリのインストール

```bash
cd scene_extractor
python -m venv venv
source venv/bin/activate  # Windows は venv\Scripts\activate
pip install -r requirements.txt
```

依存ライブラリは PDF生成用の `reportlab` のみ。

## 使い方

```bash
python extract_scenes.py --input video.mp4 --output result.pdf --threshold 0.3
```

### 主な引数

| 引数 | 短縮形 | 必須 | デフォルト | 説明 |
|---|---|---|---|---|
| `--input` | `-i` | ✅ | - | 入力動画ファイルのパス (mp4, mov など ffmpeg対応形式) |
| `--output` | `-o` | - | `scenes.pdf` | 出力PDFのパス |
| `--threshold` | `-t` | - | `0.3` | シーン検出感度 (0.0〜1.0)。小さいほど敏感に検出する |
| `--min-gap` | - | - | `1.0` | 検出結果を重複とみなす最小間隔（秒） |
| `--format` | - | - | `jpg` | 抽出する静止画の形式 (`jpg` / `png`) |
| `--images-per-page` | - | - | `1` | 1ページに配置するシーン数 |
| `--keep-frames` | - | - | (未指定) | 抽出した静止画を保存するディレクトリ。未指定時は処理後に自動削除される一時フォルダを使用 |
| `--verbose` | `-v` | - | - | 詳細ログを出力 |

### サンプル実行コマンド

```bash
# 基本的な使い方（デフォルト閾値0.3）
python extract_scenes.py --input meeting.mp4 --output meeting_scenes.pdf

# 感度を上げてより細かく場面転換を検出
python extract_scenes.py -i tutorial.mov -o tutorial_scenes.pdf -t 0.15

# 抽出画像を残しつつ、1ページに2シーンずつ配置
python extract_scenes.py -i video.mp4 -o out.pdf --images-per-page 2 --keep-frames ./frames

# 詳細ログを見ながら実行
python extract_scenes.py -i video.mp4 -o out.pdf -v
```

## 処理の流れ

1. **シーン検出**: ffmpegの `select='gt(scene,threshold)'` フィルタと `showinfo` を使い、場面転換のタイムスタンプを取得する
2. **シーン数の目安判定**: 動画の長さに対して検出シーン数が少なすぎる/多すぎる場合、閾値調整の目安をログに出力する
3. **フレーム抽出**: 各タイムスタンプのフレームを高速シーク＋精密シークの組み合わせで静止画として保存する（ファイル名に連番とタイムスタンプを含める）
4. **PDF生成**: reportlabで各シーンをページに配置し、シーン番号とタイムスタンプ(hh:mm:ss)をキャプションとして表示する

## threshold（閾値）の目安

- `0.1〜0.2`: カット割りの多い動画、細かい場面転換も拾いたい場合
- `0.3`（デフォルト）: 一般的な会議録画・チュートリアル動画向け
- `0.4〜0.6`: 場面転換が少ない・大きな変化のみ拾いたい場合

実行時のログに「シーン数が少なすぎる/多すぎる可能性があります」という警告が出た場合は、
提示された値を参考に `--threshold` を調整して再実行してください。

## エラーハンドリング

- ffmpeg / ffprobe が未インストールの場合はエラーメッセージを表示して終了する
- 入力動画ファイルが存在しない・ファイルでない場合はエラーメッセージを表示して終了する
- フレーム抽出やPDF生成に失敗した場合も、原因を含むエラーメッセージを表示して終了する（終了コード1）

## 制限事項

- シーン検出・フレーム抽出の精度は ffmpeg のシーン検出フィルタの特性に依存する（フェード等では検出が甘くなる場合がある）
- 非常に長い動画では、フレーム抽出（シーン数分のffmpeg呼び出し）に時間がかかる場合がある
