import datetime
import os
import sys

import cv2

from config import DEFAULT_THRESHOLD
from image_io import load_image, select_image_path
from marker_detection import detect_and_transform
from measurement import preprocess_backlit
from report import save_files
from ui import run_interactive_measurement


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
    file_name_without_ext = os.path.splitext(file_name_with_ext)[0]
    output_dir = file_name_without_ext
    filename_base = f"measurement_{file_name_without_ext}"

    print(f"{file_name_with_ext}を読み込みました。ARマーカーを検出して測定を実行します。")
    print(f"結果は'{output_dir}'フォルダに保存されます。")

    result = detect_and_transform(frame)

    if not result.success:
        print("\nエラー: 4つのコーナーマーカーが認識されていません。測定できません。")
        cv2.imshow("Bird's Eye View (Measurement Target)", result.bird_eye_view)
        print("\nキーを押すと終了します。")
        cv2.waitKey(0)
        cv2.destroyAllWindows()
        print("\n処理を終了しました。")
        return

    base_bird_eye_view = result.bird_eye_view
    gray_image = cv2.cvtColor(base_bird_eye_view, cv2.COLOR_BGR2GRAY)
    gray_image_masked = preprocess_backlit(gray_image, result.ar_marker_mask)
    timestamp = datetime.datetime.now()

    saved, output_lines, object_data, bird_eye_view_img = run_interactive_measurement(
        gray_image_masked, base_bird_eye_view, result.mm_per_pixel,
        file_name_with_ext, timestamp, DEFAULT_THRESHOLD
    )

    if saved:
        save_files(output_dir, filename_base, output_lines, object_data, bird_eye_view_img)

    cv2.destroyAllWindows()
    print("\n処理を終了しました。")


if __name__ == "__main__":
    main()
