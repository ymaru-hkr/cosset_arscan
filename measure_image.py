"""保存済みの画像ファイル（静止画）を測定する補助ツール。

過去に撮影した写真の測定し直しや、PCでの測定に使う。普段は main.py（カメラ）を使う。
測定画面でしきい値を調整してから保存する。自動測定 (measure_and_save) は main.py から使う。

使い方: uv run python measure_image.py [画像ファイル]
  画像ファイルを省略するとファイル選択ダイアログが開く。
"""
import datetime
import os
import sys

import cv2

from config import DEFAULT_THRESHOLD, OUTPUT_DATE_FORMAT, OUTPUT_ROOT, OUTPUT_TIME_FORMAT
from gdrive import save_csv_to_gdrive
from image_io import load_image, select_image_path
from marker_detection import detect_and_transform
from measurement import preprocess_backlit, process_frame
from report import save_files
from screen import wait_for_button
from ui import run_interactive_measurement


def make_output_dir(timestamp):
    """出力先 OUTPUT_ROOT/日付/時刻 のパスを返す。相対パスはこのプロジェクトのフォルダ基準。"""
    root = os.path.expanduser(OUTPUT_ROOT)
    if not os.path.isabs(root):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), root)
    return os.path.join(root, timestamp.strftime(OUTPUT_DATE_FORMAT), timestamp.strftime(OUTPUT_TIME_FORMAT))


def _prepare(frame):
    """マーカーを検出して鳥瞰図と前処理済み画像を作る。マーカーが読めなければ None。"""
    result = detect_and_transform(frame)
    if not result.success:
        return None
    gray_image = cv2.cvtColor(result.bird_eye_view, cv2.COLOR_BGR2GRAY)
    return result, preprocess_backlit(gray_image, result.ar_marker_mask)


def _save(output_dir, file_name, output_lines, object_data, bird_eye_view_img, original):
    """結果を output_dir に保存する。original があれば元画像も file_name で保存する。戻り値: CSVのパス"""
    print(f"結果を'{output_dir}'フォルダに保存します。")
    filename_base = f"measurement_{os.path.splitext(file_name)[0]}"
    csv_path = save_files(output_dir, filename_base, output_lines, object_data, bird_eye_view_img)
    if original is not None:
        original_path = os.path.join(output_dir, file_name)
        # 日本語パスにも対応するためエンコードしてから書き込む
        cv2.imencode(".jpg", original)[1].tofile(original_path)
        print(f"元画像を '{original_path}' として保存しました。")
    return csv_path


def measure_and_save(frame, file_name, threshold_val):
    """指定したしきい値で自動で測定し、元画像とともに保存する（カメラで撮影した画像用）。

    CSVのGoogle Driveへの保存は時間がかかることがあるので、呼び出し側で行う。
    戻り値: (保存先フォルダ, 測定した物体の数, CSVのパス, タイムスタンプ)。マーカーが読めなければ None
    """
    original = frame.copy()
    prepared = _prepare(frame)
    if prepared is None:
        return None
    result, gray_image_masked = prepared

    timestamp = datetime.datetime.now()
    output_lines, object_data, bird_eye_view_img = process_frame(
        gray_image_masked, result.bird_eye_view, result.mm_per_pixel,
        threshold_val, file_name, timestamp
    )
    output_dir = make_output_dir(timestamp)
    csv_path = _save(output_dir, file_name, output_lines, object_data, bird_eye_view_img, original)
    return output_dir, len(object_data), csv_path, timestamp


def measure_frame(frame, file_name):
    """画像を測定し、測定画面でしきい値を調整する。SAVEが押されたら結果を保存する。

    結果は OUTPUT_ROOT/日付/時刻/ に保存し、CSVは設定に応じてGoogle Driveにも保存する。
    file_name はレポートに記録する入力ファイル名（出力ファイル名にも使う）。
    戻り値: 保存したフォルダのパス。保存しなかった場合は None
    """
    prepared = _prepare(frame)
    if prepared is None:
        print("\nエラー: 4つのコーナーマーカーが認識されていません。測定できません。")
        wait_for_button(frame, "MARKERS NOT FOUND", (0, 0, 255), "cannot measure this image", ["QUIT"])
        return None
    result, gray_image_masked = prepared

    timestamp = datetime.datetime.now()
    saved, output_lines, object_data, bird_eye_view_img = run_interactive_measurement(
        gray_image_masked, result.bird_eye_view, result.mm_per_pixel,
        file_name, timestamp, DEFAULT_THRESHOLD
    )
    if not saved:
        return None

    output_dir = make_output_dir(timestamp)
    csv_path = _save(output_dir, file_name, output_lines, object_data, bird_eye_view_img, None)
    if csv_path:
        save_csv_to_gdrive(csv_path, timestamp)
    return output_dir


def main():
    # 引数で画像パスが指定されればそれを使い、無ければファイルダイアログで選ぶ
    image_path = sys.argv[1] if len(sys.argv) > 1 else select_image_path()
    if not image_path:
        print("ファイルが選択されませんでした。処理を終了します。")
        return

    try:
        frame = load_image(image_path)
    except Exception as e:
        print(f"エラー: 画像ファイル '{os.path.basename(image_path)}' の読み込み中に問題が発生しました。\n詳細: {e}")
        return

    file_name_with_ext = os.path.basename(image_path)
    print(f"{file_name_with_ext}を読み込みました。ARマーカーを検出して測定を実行します。")
    measure_frame(frame, file_name_with_ext)

    cv2.destroyAllWindows()
    print("\n処理を終了しました。")


if __name__ == "__main__":
    main()
