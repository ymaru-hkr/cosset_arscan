# cosset_arscan

ARマーカーを使って、逆光（バックライト）撮影したコセットの長さを画像から測定するツールです。
長辺の分布から K1（加重平均長）・K2（50mm以上の割合）・K3（歪度）・AISw（スウェーデン数）を算出します。

ラズパイ＋カメラモジュール＋小型ディスプレイでの運用を想定しています（Mac / PCでも動作します）。

## 撮影環境

- 発光パネル（ライトボックス）の上にコセットを並べ、真上から撮影します。
- パネルの四隅に ArUco マーカー（`DICT_6X6_250`、ID 0〜3）を貼ります。
  - ID 0: 左上、1: 右上、2: 右下、3: 左下
  - マーカー中心間の距離とマーカー1辺の長さは `config.py` で設定します（下記）。
- コセットはなるべく重ならないように広げて並べてください。重なりは自動で分離しますが、分離の誤りは重なりが多いほど増えます。

## セットアップ

[uv](https://docs.astral.sh/uv/) を使います。

```sh
uv sync
```

### ラズパイの場合

カメラモジュールは Picamera2 経由で使います。Picamera2 は pip ではなくシステムのパッケージで入れ、システムの Python で作った仮想環境から見えるようにします。

```sh
sudo apt install python3-picamera2
uv python pin /usr/bin/python3
uv venv --python /usr/bin/python3 --system-site-packages
uv sync
```

> **注意:** このプロジェクトは Python 3.12 以上が必要です。Raspberry Pi OS Bookworm の Python は 3.11 なので、Python 3.12 以上を搭載した OS（Debian 13 / Trixie ベース）を使ってください。
> ラズパイでのこの手順は未検証です。

### カメラ

ラズパイ用カメラモジュール（CSI）と USB カメラのどちらでも使えます。`CAMERA_BACKEND = "auto"`（初期値）なら自動で選びます。

| つないでいるカメラ | 使われる方式 | 撮影（SHOT）の解像度 |
|---|---|---|
| カメラモジュール | Picamera2 | センサーの最大解像度 |
| USB カメラ | OpenCV | `USB_STILL_SIZE`（初期値 4096×2160。対応していなければ近い解像度） |
| 両方 | カメラモジュールを優先 | |

USB カメラの番号は自動で探します（ラズパイ5では `/dev/video0` が USB カメラとは限らないため）。うまく見つからないときは `LIVE_CAMERA_INDEX` に `/dev/videoN` の N を指定してください。

### 画面

ウィンドウはラズパイのデスクトップに表示します。SSH から起動するときは表示先を指定してください（デスクトップにログインしている必要があります）。

```sh
DISPLAY=:0 uv run python main.py
```

`could not connect to display` と出る場合は、これが原因です。Raspberry Pi OS Lite（デスクトップなし）では表示できません。

## 使い方

普段は **`main.py` だけを起動しておきます**。並べる → 撮影 → 自動で測定・保存 → また並べる、を繰り返します。

```sh
uv run python main.py
```

```
[ライブプレビュー（しきい値を調整）] ──SHOT──▶ 撮影 → 自動で測定・保存 ──▶ ライブプレビューに戻る
                                                              （結果を5秒表示）
```

### 1. ライブプレビューで並べる

カメラ映像に、重なっている箇所をリアルタイムで表示します。

| 表示 | 意味 |
|---|---|
| 赤 + 丸印 | 交差・重なっているコセット（丸印が交差点） |
| 橙 | 交差点は無いが幅が太すぎる物体（横並びに重なっている疑い） |
| `OK: no overlap` | 重なりなし |

しきい値は **- / +** でここで調整します。プレビューの検出結果がそのまま測定結果になります（プレビューも測定も同じ大きさの鳥瞰図で処理しているため）。
4つのARマーカーが読めていない間は **SHOT がグレーになり撮影できません**。

### 2. 撮影する

赤い部分が無くなるように並べ直してから **SHOT**（またはタクトスイッチ）を押します。
最大解像度で撮影し、今のしきい値で自動で測定・保存して、すぐにライブプレビューに戻ります。結果は画面中央に5秒表示されます。

| 表示 | 意味 |
|---|---|
| **撮影しました**（緑） | 保存しました。保存先の「日付/時刻」と測定した物体の数を表示します |
| **撮影しました**（緑）＋「Google Driveに送信中...」→「Google Driveにも保存しました」 | ローカルと Google Drive の両方に保存しました（Drive を設定している場合） |
| **撮影しました**（橙）＋「Google Driveへの送信に失敗しました」 | ローカルには保存済み。Driveへの送信だけ失敗しました |
| **マーカーが読めませんでした**（赤） | 撮影した静止画でマーカーが読めなかったので、保存していません。撮り直してください |

結果は `results/日付/時刻/` に保存されます（例: `results/2026-10-22/110822/`）。

- `capture.jpg`: 撮影した元画像
- `measurement_capture.txt`: レポート（各オブジェクトの寸法と統計量）
- `measurement_capture.csv`: オブジェクトごとの長辺・短辺・面積
- `measurement_capture.png`: 検出結果の画像（赤: 50mm以上、青: 10mm未満、黄色の丸: 交差点）

CSVは、設定すれば Google Drive にも保存されます（下記）。Drive 側はフォルダ分けせず、`2026-10-22_110822_measurement_capture.csv` のように日付と時刻をファイル名に付けて、保存先フォルダの直下に置きます。送信は裏で行うので、その間も撮影を続けられます。

### 操作

画面下のボタン（タッチ操作可）またはキーで操作します。

| ボタン | キー | 動作 |
|---|---|---|
| `-` / `+` | `-` / `+` | しきい値を下げる / 上げる |
| `SHOT` | `s` / タクトスイッチ | 撮影して測定・保存 |
| `QUIT` | `q` | アプリを終了 |

### 日本語の表示

画面のメッセージは日本語フォントで表示します。ラズパイでは次のフォントを入れてください（無い場合は英語で表示されます）。

```sh
sudo apt install fonts-noto-cjk
```

### タクトスイッチ

スイッチの片側を GPIO17（`CAPTURE_BUTTON_GPIO`、BCM番号）、もう片側を GND につなぎます。内部プルアップを使うので抵抗は不要です。
[gpiozero](https://gpiozero.readthedocs.io/) を使います（Raspberry Pi OS には標準で入っています。無ければ `sudo apt install python3-gpiozero`）。
撮影・保存している間は、スイッチは無視されます。

### 保存済みの画像を測定する（`measure_image.py`）

過去に撮影した写真の測定し直しや、PC での測定に使います。測定画面でしきい値を調整してから **SAVE** で保存します（**QUIT** で保存せずに終了）。保存先は `main.py` と同じです。

```sh
uv run python measure_image.py "results/2026-10-21/130818/capture.jpg"
```

画像を指定しないとファイル選択ダイアログが開きます。

## 設定（`config.py`）

主な項目は次のとおりです。

| 項目 | 内容 |
|---|---|
| `MARKER_DISTANCE_X_MM` / `MARKER_DISTANCE_Y_MM` | マーカー中心間の実寸 (mm) |
| `MARKER_SIZE_MM` | マーカー1辺の実寸 (mm) |
| `DEFAULT_THRESHOLD` | 二値化しきい値の初期値 |
| `HYSTERESIS_LOW_RATIO` | 濃い部分につながる薄い部分を、しきい値の何倍まで含めるか |
| `DISPLAY_SIZE` / `DISPLAY_FULLSCREEN` | 画面サイズ・全画面表示（Macで試すときは `False` 推奨） |
| `MESSAGE_SECONDS` | 撮影結果のメッセージを表示する秒数 |
| `MESSAGE_FONT_PATH` | 日本語メッセージ用のフォント（`None` なら自動で探す） |
| `CAMERA_BACKEND` | 使うカメラ: `"auto"` / `"picamera2"` / `"opencv"` |
| `LIVE_CAMERA_INDEX` | USB カメラの番号（`None` なら自動） |
| `LIVE_CAPTURE_SIZE` | ライブプレビューの解像度 |
| `USB_STILL_SIZE` | USB カメラで撮影するときの解像度 |
| `CAPTURE_BUTTON_GPIO` | 撮影用タクトスイッチの GPIO 番号（使わなければ `None`） |
| `OUTPUT_ROOT` | 測定結果の保存先（相対パスはプロジェクトのフォルダ基準） |
| `OUTPUT_DATE_FORMAT` / `OUTPUT_TIME_FORMAT` | 日付・時刻フォルダの名前の形式 |
| `GDRIVE_RCLONE_DEST` / `GDRIVE_LOCAL_DIR` | CSVを保存する Google Drive の場所（下記） |

交差分離のパラメータ（`*_FACTOR`）は、画像から自動推定したコセットの幅に対する倍率です。

## Google Drive への CSV 保存

`config.py` で次のどちらか（または両方）を設定します。どちらも `None` なら Drive には保存しません。
アップロードに失敗しても、ローカルの結果はそのまま残り、警告が表示されるだけです。

### 方法1: rclone（ラズパイ向け）

```sh
sudo apt install rclone          # Mac は brew install rclone
rclone config                    # 「n」→ 名前を gdrive → 種類に drive を選び、画面の指示に従ってGoogleアカウントでログイン
rclone lsd gdrive:               # Driveのフォルダ一覧が出れば設定完了
```

```python
GDRIVE_RCLONE_DEST = "gdrive:cossette/csv"   # 「リモート名:Drive上のフォルダ」
```

ラズパイに画面とブラウザが無い場合は、`rclone config` の途中で表示される `rclone authorize "drive"` を、ブラウザのある PC で実行して得たトークンを貼り付けます。

### 方法2: Driveと同期しているフォルダにコピー（Mac / Windows 向け）

[Google Drive for desktop](https://www.google.com/drive/download/) を入れると、Drive がローカルのフォルダとして見えます。そのフォルダを指定します。

```python
GDRIVE_LOCAL_DIR = "~/Library/CloudStorage/GoogleDrive-xxxx@gmail.com/マイドライブ/cossette"
```

## 処理の流れ

1. **マーカー検出**（`marker_detection.py`）: CLAHE でコントラストを補正してマーカーを検出し、鳥瞰図に射影変換します。マーカー間の距離から mm/pixel を求めます。
2. **前処理**（`measurement.py`）: 背景の明るさを推定して照明ムラを補正し、「背景に対する暗さ」の画像に変換します。
3. **二値化**: ヒステリシスしきい値で、1本の中の濃淡で途切れないように二値化します。
4. **交差の分離**（`crossing.py`）: 骨格線の分岐点を交差点とみなし、向きがまっすぐ続く枝どうしをつなぎ直して1本ずつに分けます。
5. **測定**: 各物体の最小外接矩形から長辺・短辺を求め、統計量を算出します。

## 既知の制限

- 2本の端どうしがL字に接していると、1本として測られます。
- 曲がったコセットが交差点で別のコセットとつながることがあります。
- 交差点で重なった部分の面積は、両方のコセットに含まれます。
