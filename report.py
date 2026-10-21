import csv
import os

import cv2


def save_files(output_dir, filename_base, output_lines, object_data, bird_eye_view_img):
    """測定結果をTXT/PNG/CSVとしてoutput_dir配下に保存する。"""
    os.makedirs(output_dir, exist_ok=True)

    if not object_data:
        output_lines = output_lines + ["\n測定可能なオブジェクトは見つかりませんでした。"]
    output_lines = output_lines + ["--- 測定終了 ---"]

    report_text = "\n".join(output_lines)
    print("\n" + report_text)

    txt_filename = os.path.join(output_dir, f"{filename_base}.txt")
    try:
        with open(txt_filename, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"レポートを '{txt_filename}' として保存しました。")
    except IOError as e:
        print(f"エラー: レポートファイル '{txt_filename}' の書き込みに失敗しました: {e}")

    if not object_data:
        return

    img_filename = os.path.join(output_dir, f"{filename_base}.png")
    cv2.imwrite(img_filename, bird_eye_view_img)
    print(f"結果画像を '{img_filename}' として保存しました。")

    csv_filename = os.path.join(output_dir, f"{filename_base}.csv")
    try:
        with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['ID', 'Major_Axis_mm', 'Minor_Axis_mm', 'Area_mm2']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(object_data)
        print(f"測定データを '{csv_filename}' として保存しました。")
    except IOError as e:
        print(f"エラー: CSVファイル '{csv_filename}' の書き込みに失敗しました: {e}")
