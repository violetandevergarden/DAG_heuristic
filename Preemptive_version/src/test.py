import os
import io
import sys
import json
import hashlib
import subprocess
import statistics
import benchmark.loader
from pathlib import Path
from contextlib import redirect_stdout

def process_index(categorys, familys, test_loc):
    # ---------- 硬编码地址（请按实际情况修改） ----------
    INDEX_JSONL_PATH = Path("./benchmark/index.jsonl")
    EXE_2 = Path("./src/core/counter.exe")
    RESULTS_DIR = Path("./benchmark/reference_results")
    # --------------------------------------------------

    # 检查 test_loc 是否以 .exe 结尾
    if not str(test_loc).lower().endswith('.exe'):
        print("错误：test_loc 必须是一个 .exe 文件路径", file=sys.stderr)
        sys.exit(1)

    test_loc = Path(test_loc)
    if not test_loc.is_file():
        print(f"错误：可执行文件 {test_loc} 不存在", file=sys.stderr)
        sys.exit(1)

    # 读取 index.jsonl，筛选条目
    base_dir = INDEX_JSONL_PATH.parent
    selected_entries = []
    with open(INDEX_JSONL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("category") in categorys and entry.get("family") in familys:
                selected_entries.append(entry)

    if not selected_entries:
        print("警告：没有找到符合条件的条目。")
        return None

    count = 0
    C_list = []
    D_list = []
    ratio_list = []

    for entry in selected_entries:
        # 构造 json 文件路径（相对于 index.jsonl 所在目录）
        json_path = base_dir / entry["path"]
        if not json_path.is_file():
            print(f"警告：{json_path} 不存在，跳过")
            continue

        # 验证 SHA256
        sha256_hash = hashlib.sha256()
        with open(json_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256_hash.update(chunk)
        computed_sha = sha256_hash.hexdigest()
        if computed_sha != entry.get("sha256", ""):
            print(f"警告：{json_path} 的 SHA256 不匹配，跳过")
            continue

        # 读取 json 文件内容（作为字典）
        with open(json_path, 'r', encoding='utf-8') as f:
            data_dict = json.load(f)

        # --- 调用 1.py，传入字典（JSON 字符串作为命令行参数） ---

        buf = io.StringIO()
        with redirect_stdout(buf):
            benchmark.loader.print_dag(data_dict)        # 函数内部的 print 会被捕获
        A = buf.getvalue()

        # --- 将 A 输入给 test_loc (.exe) ---

        try:
            proc_test = subprocess.run(
                [str(test_loc)],
                input=A,
                capture_output=True,
                text=True,
                check=True
            )
            B = proc_test.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"错误：运行 {test_loc} 失败：{e.stderr}", file=sys.stderr)
            continue

        # --- 拼接 A 和 B，作为 2.exe 的输入 ---
        AB = A + "\n" + B   # 直接拼接，可根据需要改为 A + "\n" + B
        # print(AB)
        try:
            proc2 = subprocess.run(
                [str(EXE_2)],
                input=AB,
                capture_output=True,
                text=True,
                check=True
            )
            C_str = proc2.stdout.strip()
            C = float(C_str)
        except subprocess.CalledProcessError as e:
            print(f"错误：运行 2.exe 失败：{e.stderr}", file=sys.stderr)
            continue
        except ValueError:
            print(f"错误：2.exe 输出 '{C_str}' 不是有效数值", file=sys.stderr)
            # return
            continue

        # --- 从 results 目录读取对应的 optimal_makespan ---
        result_json_path = RESULTS_DIR / entry["path"]
        try:
            with open(result_json_path, 'r', encoding='utf-8') as f:
                result_data = json.load(f)
            D = float(result_data["optimal_makespan"])
            if computed_sha != result_data.get("benchmark_sha256", ""):
                print(f"警告：{result_json_path} 的 SHA256 不匹配，跳过")
                continue
        except Exception as e:
            print(f"错误：读取 {result_json_path} 失败：{e}", file=sys.stderr)
            continue

        count += 1
        if(C == D):
            continue
        # 保存数据
        C_list.append(C)
        D_list.append(D)
        ratio_list.append(C / D)

    # 统计结果
    if count == 0:
        print("没有成功处理的条目。")
        return None

    if len(C_list) == 0:
        print(f"所有 {count} 个样例均正确")
        return None
    
    def stats(values):
        return {
            "max": max(values),
            "min": min(values),
            "avg": statistics.mean(values)
        }

    result_stats = {
        "C": stats(C_list),
        "D": stats(D_list),
        "C_over_D": stats(ratio_list)
    }

    # 输出到控制台
    print("=== 统计结果 ===")
    print(f"count: {count},err_count: {len(C_list)}")
    print(f"err_ratio: {len(C_list)/count:.6f}")
    print(f"err部分比值 -> 最大值: {result_stats['C_over_D']['max']}, 最小值: {result_stats['C_over_D']['min']}, 平均值: {result_stats['C_over_D']['avg']}")

    return result_stats

process_index(["adversarial","random","real"],["complex_chain","parallel_chain"],"./src/single_channel/rollout_1.exe")