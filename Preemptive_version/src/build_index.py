import os
import json
import hashlib
import sys
from pathlib import Path
def generate_index(root_dir, output_file="index.jsonl"):
    """
    遍历 root_dir 下所有 .json 文件，生成 index.jsonl。
    每行包含 category, family, id, path, scenario, sha256。
    假设文件路径结构为：<scenario>/<family>/<category>/<id>.json
    """
    json_files = []
    # 递归收集所有 .json 文件
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            if fname.lower().endswith(".json"):
                json_files.append(os.path.join(dirpath, fname))

    # 按路径排序，保证输出稳定
    json_files.sort()

    with open(output_file, "w", encoding="utf-8") as out:
        for full_path in json_files:
            # 获取相对于根目录的路径，统一使用正斜杠
            rel_path = os.path.relpath(full_path, root_dir).replace("\\", "/")
            parts = rel_path.split("/")

            # 期望至少 4 层：scenario/family/category/file.json
            if len(parts) != 4:
                print(f"警告：路径层级，跳过 -> {rel_path}")
                continue

            scenario = parts[0]
            family = parts[1]
            category = parts[2]
            file_name = parts[3]
            file_id, _ = os.path.splitext(file_name)

            # 计算文件内容的 SHA-256
            file_path = Path(root_dir) / rel_path
            try:
                file_bytes = file_path.read_bytes()
                sha256_hash = hashlib.sha256(file_bytes).hexdigest()
            except Exception as e:
                print(f"错误: 无法计算 {file_path} 的 SHA-256: {e}", file=sys.stderr)
                continue

            entry = {
                "category": category,
                "family": family,
                "id": file_id,
                "path": rel_path,
                "scenario": scenario,
                "sha256": sha256_hash,
            }

            out.write(json.dumps(entry, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    # 可通过命令行参数指定文件夹，默认当前目录
    target_dir = sys.argv[1] if len(sys.argv) > 2 else "./benchmark"
    result_dir = sys.argv[2] if len(sys.argv) > 2 else "./benchmark/index.jsonl"
    generate_index(target_dir,result_dir)
    print("index.jsonl 生成完毕。")