from benchmark.loader import convert_simple_to_json
from pathlib import Path
import json


simple = """75 73
c 412
t 915
c 917
c 870
t 25
c 591
c 196
t 997
c 907
c 283
t 736
c 824
c 803
t 659
c 639
c 987
t 880
c 645
c 554
t 922
c 936
c 972
t 699
c 538
c 543
t 218
c 861
c 423
t 212
c 745
c 805
t 536
c 302
c 844
t 499
c 775
c 231
t 355
c 360
c 824
t 678
c 221
c 572
t 76
c 922
c 71
t 367
c 247
c 405
t 294
c 81
c 532
t 91
c 130
c 539
t 854
c 549
c 871
t 590
c 930
c 503
t 294
c 772
c 334
t 215
c 933
c 946
t 656
c 367
c 177
t 626
c 960
c 826
t 863
c 536
6 37
6 46
9 22
12 34
15 70
18 61
18 64
21 22
21 46
21 61
24 46
24 49
24 67
27 58
30 73
33 34
39 49
42 43
42 61
48 73
51 61
57 70
60 70
1 2
2 3
4 5
5 6
7 8
8 9
10 11
11 12
13 14
14 15
16 17
17 18
19 20
20 21
22 23
23 24
25 26
26 27
28 29
29 30
31 32
32 33
34 35
35 36
37 38
38 39
40 41
41 42
43 44
44 45
46 47
47 48
49 50
50 51
52 53
53 54
55 56
56 57
58 59
59 60
61 62
62 63
64 65
65 66
67 68
68 69
70 71
71 72
73 74
74 75
"""

id = "test_oracle_limit"

category = "adversarial"

family = "complex_chain"

result = convert_simple_to_json(simple_str = simple, id= id, category= category, family= family)

path = Path("./benchmark/single_channel/" + family + "/" + category + "/" + id +".json")

with open(path, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
    f.write('\n')   # 末尾换行

# print(result)