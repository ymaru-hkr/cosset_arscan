"""測定結果のCSVをGoogle Driveにも保存する。

rclone でアップロードする方法と、Driveと同期しているローカルフォルダへコピーする方法に対応する。
失敗してもローカルの保存結果は残るので、警告を表示するだけで処理は続ける。
"""
import os
import shutil
import subprocess

from config import (
    GDRIVE_LOCAL_DIR,
    GDRIVE_RCLONE_DEST,
    GDRIVE_UPLOAD_TIMEOUT_SEC,
    OUTPUT_DATE_FORMAT,
    OUTPUT_TIME_FORMAT,
)


def _upload_with_rclone(csv_path, remote_path):
    try:
        proc = subprocess.run(
            ["rclone", "copyto", csv_path, remote_path],
            capture_output=True, text=True, timeout=GDRIVE_UPLOAD_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return "rclone が見つかりません。インストールしてください。"
    except subprocess.TimeoutExpired:
        return f"{GDRIVE_UPLOAD_TIMEOUT_SEC}秒以内に完了しませんでした (ネットワークを確認してください)。"
    if proc.returncode != 0:
        return proc.stderr.strip() or f"rclone が終了コード {proc.returncode} で失敗しました。"
    return None


def save_csv_to_gdrive(csv_path, timestamp):
    """CSVを設定されたGoogle Driveの保存先に「日付/時刻_ファイル名」で保存する。

    戻り値: 保存先が未設定なら None、すべて成功なら True、1つでも失敗したら False
    """
    if not GDRIVE_LOCAL_DIR and not GDRIVE_RCLONE_DEST:
        return None
    ok = True
    date_dir = timestamp.strftime(OUTPUT_DATE_FORMAT)
    file_name = f"{timestamp.strftime(OUTPUT_TIME_FORMAT)}_{os.path.basename(csv_path)}"

    if GDRIVE_LOCAL_DIR:
        dest_dir = os.path.join(os.path.expanduser(GDRIVE_LOCAL_DIR), date_dir)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(csv_path, os.path.join(dest_dir, file_name))
            print(f"CSVをGoogle Driveフォルダ '{dest_dir}' にも保存しました。")
        except OSError as e:
            print(f"警告: Google DriveフォルダへのCSV保存に失敗しました: {e}")
            ok = False

    if GDRIVE_RCLONE_DEST:
        remote_path = f"{GDRIVE_RCLONE_DEST.rstrip('/')}/{date_dir}/{file_name}"
        error = _upload_with_rclone(csv_path, remote_path)
        if error:
            print(f"警告: Google DriveへのCSVアップロードに失敗しました ({remote_path}): {error}")
            ok = False
        else:
            print(f"CSVをGoogle Drive '{remote_path}' にアップロードしました。")
    return ok
