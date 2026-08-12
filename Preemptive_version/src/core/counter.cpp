#include <bits/stdc++.h>
using namespace std;
const int MAXN = 100005;
const int INF = 1e9 + 7;

struct Interval {
    int l, r;
    bool operator<(const Interval& other) const {
        if (l == other.l) return r < other.r;  // 左端点相同，按右端点排序
        return l < other.l;   // 按左端点排序
    }
};

class FreeIntervals {
    std::set<Interval> intervals;
public:
    // 初始化：只有一个 [0, +inf] 区间
    void init() {
        intervals.clear();
        intervals.insert({0, INF});
    }

    // 分配总长度为 len 的若干区间，所有部分 ≥ x，且尽可能靠近 x
    // 返回分配的最右边区间的右端点；若空闲不足则返回 -1
    int use(int x, int len) {
        if (len <= 0) return -1;

        // 1. 找到第一个可能提供空间的区间（覆盖 x 或第一个左端点 ≥ x 的区间）
        auto it = intervals.lower_bound({x, 0});
        if (it != intervals.begin()) {
            auto prev_it = std::prev(it);
            if (prev_it->r > x) {
                it = prev_it;   // 前一个区间覆盖了 x (因为右开，用 > 判断)
            }
        }

        int remaining = len;
        int last_right = -1;

        // 2. 从 it 开始向右取区间（区间为左闭右开 [l, r)）
        while (remaining > 0 && it != intervals.end()) {
            int orig_l = it->l;
            int r = it->r;
            int l = max(orig_l, x);   // 只有第一个区间可能需要截断

            if (l >= r) { ++it; continue; }       // 空区间或越界

            int avail = r - l;         // 该区间可用长度（右开）

            if (avail <= remaining) {
                // 整个区间（或截断后的剩余部分）被完全消耗
                remaining -= avail;
                last_right = r; // 返回被分配的最大索引（闭合结果）
                it = intervals.erase(it);        // 删除原区间，返回下一区间
                if (orig_l < l) {
                    intervals.insert({orig_l, l}); // 留下左边被 x 截断的部分 [orig_l, l)
                }
            } else {
                // 区间部分被消耗
                int use_r = l + remaining; // 分配区间为 [l, use_r)
                last_right = use_r;
                it = intervals.erase(it);
                if (use_r < r) {
                    intervals.insert({use_r, r});  // 保留右侧剩余 [use_r, r)
                }
                if (orig_l < l) {
                    intervals.insert({orig_l, l}); // 保留左侧剩余 [orig_l, l)
                }
                remaining = 0;
            }
        }

        return (remaining == 0) ? last_right : -1;
    }
};

int T = 0,n,n_t,m;
int in[MAXN];
int type[MAXN];
int weight[MAXN];
vector<int> adj[MAXN];

FreeIntervals F;
int ans;
int pri[MAXN];
int res[MAXN];
int sol_time[MAXN];
queue<int> c_q;
priority_queue<pair<int,int>> t_q;

int main(int argc, char* argv[]) {
    cin >> n >> m;
    for (int i = 1; i <= n; ++i) {
        char c;
        cin >> c >> weight[i];
        type[i] = (c == 'c' ? 0 : 1);
        n_t += (type[i] == 1);
    }
    for (int i = 1; i <= m; ++i) {
        int u,v;
        cin >> u >> v;
        adj[u].push_back(v);
        in[v]++;
    }
    F.init();
    ans = 0;
    while(!c_q.empty()) c_q.pop();
    while(!t_q.empty()) t_q.pop();
    for(int i = 1; i <= n; ++i) {
        pri[i] = 0;
        res[i] = in[i];
        sol_time[i] = 0;
    }

    for (int i = 1; i <= n_t; ++i) {
        int x;
        cin >> x;
        pri[x] = i;
    }
    for (int i = 1; i <= n; ++i) {
        if(res[i] == 0) {
            if(type[i] == 0) c_q.push(i);
            else t_q.push({-pri[i], i});
        }
    }
    while(!c_q.empty() || !t_q.empty()) {
        while(!c_q.empty()) {
            int u = c_q.front(); c_q.pop();
            sol_time[u] += weight[u];
            ans = max(ans, sol_time[u]);
            for(int v : adj[u]) {
                res[v]--;
                sol_time[v] = max(sol_time[v], sol_time[u]);
                if(res[v] == 0) {
                    if(type[v] == 0) c_q.push(v);
                    else t_q.push({-pri[v], v});
                }
            }
        }
        if(!t_q.empty()) {
            int u = t_q.top().second; t_q.pop();
            sol_time[u] = F.use(sol_time[u], weight[u]);
            ans = max(ans, sol_time[u]);
            for(int v : adj[u]) {
                res[v]--;
                sol_time[v] = max(sol_time[v], sol_time[u]);
                if(res[v] == 0) {
                    if(type[v] == 0) c_q.push(v);
                    else t_q.push({-pri[v], v});
                }
            }
        }
    }
    cout << ans << '\n';
}