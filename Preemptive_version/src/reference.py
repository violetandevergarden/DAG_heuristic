#!/usr/bin/env python3
import json
import io
import sys
import hashlib
import subprocess
from pathlib import Path
from contextlib import redirect_stdout

# ---------- 1. 导入你的函数 ----------
import benchmark.loader

# ---------- 2. 配置 ----------
INPUT_DIR = Path("./benchmark/single_channel")          # 存放 JSON 文件的目录
ANSWER_DIR = Path("./benchmark/reference_results/single_channel")       # 存放输出的目录
CPP_EXECUTABLE = "./src/core/oracle"      # C++ 编译的可执行文件

def main():
    # 确保答案目录存在
    ANSWER_DIR.mkdir(parents=True, exist_ok=True)

    err_list = []

    # 遍历输入目录中的所有 .json 文件
    json_files = sorted(INPUT_DIR.rglob("*.json"))
    if not json_files:
        print(f"在 {INPUT_DIR} 及其子目录中没有找到 .json 文件", file=sys.stderr)
        sys.exit(1)

    for json_path in json_files:
        rel_path = json_path.relative_to(INPUT_DIR)
        print(f"处理: {rel_path}")

        # 1. 计算输入文件的 SHA-256
        try:
            file_bytes = json_path.read_bytes()
            sha256_hash = hashlib.sha256(file_bytes).hexdigest()
        except Exception as e:
            err_list.append(f"错误: 无法计算 {json_path} 的 SHA-256: {e}")
            print(f"错误: 无法计算 {json_path} 的 SHA-256: {e}", file=sys.stderr)
            continue

        # 2. 读取 JSON 内容为字典
        try:
            data = json.loads(file_bytes)
        except Exception as e:
            err_list.append(f"错误: {json_path} 不是合法的 JSON 文件: {e}")
            print(f"错误: {json_path} 不是合法的 JSON 文件: {e}", file=sys.stderr)
            continue

        # 3. 调用 Python 函数，捕获其打印输出
        buf = io.StringIO()
        with redirect_stdout(buf):
            benchmark.loader.print_dag(data)        # 函数内部的 print 会被捕获
        python_output = buf.getvalue()

        # 4. 将捕获的输出作为标准输入传给 C++ 程序，并捕获其输出
        try:
            result = subprocess.run(
                [CPP_EXECUTABLE],
                input=python_output,
                capture_output=True,
                text=True,
                check=True
            )
            cpp_output = result.stdout
        except subprocess.CalledProcessError as e:
            err_list.append(f"错误: C++ 程序处理 {rel_path} 失败")
            print(f"错误: C++ 程序处理 {rel_path} 失败", file=sys.stderr)
            # print(python_output)
            print(e.stderr, file=sys.stderr)
            continue
        except FileNotFoundError:
            err_list.append(f"错误: 找不到 C++ 可执行文件 '{CPP_EXECUTABLE}'")
            print(f"错误: 找不到 C++ 可执行文件 '{CPP_EXECUTABLE}'", file=sys.stderr)
            sys.exit(1)

        # 5. 解析 C++ 输出为整数（optimal makespan）
        try:
            optimal_makespan = int(cpp_output.strip())
        except ValueError:
            err_list.append(f"错误: C++ 输出无法解析为整数: {cpp_output.strip()}")
            print(f"错误: C++ 输出无法解析为整数: {cpp_output.strip()}", file=sys.stderr)
            continue

        # 6. 构造输出 JSON 对象
        result_dict = {
            "benchmark_id": json_path.stem,          # 文件名（不含扩展名）
            "benchmark_sha256": sha256_hash,
            "optimal_makespan": optimal_makespan,
            "oracle": "",                            # 留空
            "schema_version": "1.0"
        }

        # 7. 在答案目录中重建相同的子目录结构并保存
        out_dir = ANSWER_DIR / rel_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        out_name = json_path.stem + ".json"          # 输出文件扩展名为 .json
        out_path = out_dir / out_name

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, indent=2, ensure_ascii=False)
            f.write('\n')   # 末尾换行

        print(f"  -> 已保存 {out_path}")

    for s in err_list:
        print(s,file=sys.stderr)

if __name__ == "__main__":
    main()