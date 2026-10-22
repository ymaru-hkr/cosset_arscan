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

普段は **`main.py` だけを起動しておきます**。並べる → 撮影 → 測定 → 保存を1つの画面で繰り返します。

```sh
uv run python main.py
```

```
[ライブプレビュー] ──SHOT──▶ [測定画面（しきい値の調整）] ──SAVE──▶ 保存・Driveへ送信
       ▲                                │
       └────────── 保存後 / BACK ────────┘
```

### 1. ライブプレビューで並べる

カメラ映像に、重なっている箇所をリアルタイムで表示します。

| 表示 | 意味 |
|---|---|
| 赤 + 丸印 | 交差・重なっているコセット（丸印が交差点） |
| 橙 | 交差点は無いが幅が太すぎる物体（横並びに重なっている疑い） |
| `OK: no overlap` | 重なりなし |

赤い部分が無くなるように並べ直してから **SHOT**（またはタクトスイッチ）を押すと、最大解像度の静止画を撮影して測定画面に移ります。

- プレビューは常に表示されますが、4つのARマーカーが読めていない間は **SHOT がグレーになり撮影できません**。
- 撮影した静止画でもマーカーを再確認し、読めなければ測定画面に移りません（画面に `SHOT FAILED` と表示）。

### 2. 測定画面で保存する

**- / +** でしきい値を調整し（ライブプレビューのしきい値が初期値になります）、検出がよければ **SAVE** で保存します。
保存せずに撮り直すときは **BACK** を押します。どちらもライブプレビューに戻ります。

結果は `results/日付/時刻/` に保存されます（例: `results/2026-10-21/130818/`）。

- `capture.jpg`: 撮影した元画像
- `measurement_capture.txt`: レポート（各オブジェクトの寸法と統計量）
- `measurement_capture.csv`: オブジェクトごとの長辺・短辺・面積
- `measurement_capture.png`: 検出結果の画像（赤: 50mm以上、青: 10mm未満、黄色の丸: 交差点）

CSVは、設定すれば Google Drive にも `日付/時刻_measurement_capture.csv` として保存されます（下記）。

### 操作

画面下のボタン（タッチ操作可）またはキーで操作します。

| 画面 | ボタン | キー | 動作 |
|---|---|---|---|
| 共通 | `-` / `+` | `-` / `+` | しきい値を下げる / 上げる |
| ライブ | `SHOT` | `s` / タクトスイッチ | 撮影して測定画面へ |
| ライブ | `QUIT` | `q` | アプリを終了 |
| 測定 | `SAVE` | `s` | 結果を保存してライブへ戻る |
| 測定 | `BACK` | `q` | 保存せずにライブへ戻る |

### タクトスイッチ

スイッチの片側を GPIO17（`CAPTURE_BUTTON_GPIO`、BCM番号）、もう片側を GND につなぎます。内部プルアップを使うので抵抗は不要です。
[gpiozero](https://gpiozero.readthedocs.io/) を使います（Raspberry Pi OS には標準で入っています。無ければ `sudo apt install python3-gpiozero`）。
測定画面を表示している間は、スイッチは無視されます。

### 保存済みの画像を測定する（`measure_image.py`）

過去に撮影した写真の測定し直しや、PC での測定に使います。測定画面と保存先は `main.py` と同じです。

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
