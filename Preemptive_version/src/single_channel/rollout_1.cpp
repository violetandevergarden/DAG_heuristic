//不知道怎么命名……
#include <set>
#include <vector>
#include <stack>
#include <stdexcept>
#include <algorithm>
#include <iostream>
#include <queue>
#define int64 long long
using namespace std;
const int MAXN = 1000006;
const int64 INF = 2e18;  // 代表 +∞

struct Interval {
    int64 l, r;
    bool operator<(const Interval& other) const {
        if (l == other.l) return r < other.r;
        return l < other.l;
    }
};

class FreeIntervals {
    std::set<Interval> intervals;
    // 历史栈：每次成功 use 的 <删除区间, 新增区间>
    std::stack<std::pair<std::vector<Interval>, std::vector<Interval>>> history;

public:
    // 初始化：只有一个 [0, +∞) 区间，并清空回退历史
    void init() {
        intervals.clear();
        intervals.insert({0, INF});
        while (!history.empty()) history.pop();
    }

    int64 sim_use(int64 x, int64 len) const {
        if (len <= 0) return -1;

        // 定位起始区间
        auto it = intervals.lower_bound({x, 0});
        if (it != intervals.begin()) {
            auto prev_it = std::prev(it);
            if (prev_it->r > x) it = prev_it;
        }

        int64 remaining = len;
        int64 last_right = -1;

        // 模拟遍历，但不修改集合
        while (remaining > 0 && it != intervals.end()) {
            int64 orig_l = it->l;
            int64 r = it->r;
            int64 l = std::max(orig_l, x);

            if (l >= r) { ++it; continue; }

            int64 avail = r - l;
            if (avail <= remaining) {
                // 整个可用部分被消耗
                remaining -= avail;
                last_right = r;            // 分配到这个区间的右边界
                ++it;
            } else {
                // 部分消耗：分配 [l, l + remaining)
                last_right = l + remaining;
                remaining = 0;
                // 注意：这里不推进 it 或修改，只终止循环
            }
        }

        return (remaining == 0) ? last_right : -1;
    }
    // 分配总长度为 len 的空间，所有部分 ≥ x，尽可能靠近 x
    // 成功返回分配的最右侧区间的右端点；失败返回 -1（且不改变任何状态）
    int64 use(int64 x, int64 len) {
        if (len <= 0) return -1;

        // 1. 找到起始区间（覆盖 x 或第一个左端点 ≥ x 的区间）
        auto it = intervals.lower_bound({x, 0});
        if (it != intervals.begin()) {
            auto prev_it = std::prev(it);
            if (prev_it->r > x) it = prev_it;
        }

        // 2. 先检查是否有足够的空闲空间（只读，不修改）
        int64 needed = len;
        auto check_it = it;
        while (needed > 0 && check_it != intervals.end()) {
            int64 l = std::max(check_it->l, x);
            int64 r = check_it->r;
            if (l < r) {
                int64 avail = r - l;
                if (avail >= needed) {
                    needed = 0;
                } else {
                    needed -= avail;
                }
            }
            ++check_it;
        }
        if (needed > 0) return -1;   // 空间不足，安全退出

        // 3. 实际分配（此时肯定成功）
        int64 remaining = len;
        int64 last_right = -1;
        std::vector<Interval> removed;
        std::vector<Interval> added;

        while (remaining > 0 && it != intervals.end()) {
            int64 orig_l = it->l;
            int64 r = it->r;
            int64 l = std::max(orig_l, x);

            if (l >= r) { ++it; continue; }

            int64 avail = r - l;
            removed.push_back(*it);          // 记录将被删除的区间
            it = intervals.erase(it);        // 删除并获取下一迭代器

            if (avail <= remaining) {
                // 整个区间被消耗
                remaining -= avail;
                last_right = r;
                if (orig_l < l) {
                    intervals.insert({orig_l, l});
                    added.push_back({orig_l, l});
                }
            } else {
                // 部分消耗
                int64 use_r = l + remaining;
                last_right = use_r;
                if (use_r < r) {
                    intervals.insert({use_r, r});
                    added.push_back({use_r, r});
                }
                if (orig_l < l) {
                    intervals.insert({orig_l, l});
                    added.push_back({orig_l, l});
                }
                remaining = 0;
            }
        }

        // 记录操作历史
        history.push({removed, added});
        return last_right;
    }

    // 回退最近一次成功的 use
    // 若无历史记录（已回到初始状态），抛出 std::runtime_error
    void undo() {
        if (history.empty()) {
            throw std::runtime_error("No more operations to undo");
        }
        auto _ = history.top();
        auto removed = _.first;
        auto added = _.second;
        history.pop();

        // 撤销新增的区间
        for (const auto& iv : added) {
            intervals.erase(iv);
        }
        // 恢复被删除的区间
        for (const auto& iv : removed) {
            intervals.insert(iv);
        }
    }
};

int n,n_t,m;
int in[MAXN];
int type[MAXN];
int64 weight[MAXN];
vector<int> adj[MAXN];

FreeIntervals F;
int64 max_time;
int res[MAXN];
int64 sol_time[MAXN];
int c_q[MAXN],head,tail;
set< pair<int64,int> > t_q;

stack< pair<int,int64> > his_sol_time;
stack< int > his_res;
stack< pair<int64,int> > his_t_q;

int out[MAXN];
int ltail[MAXN];
pair<int,int> a[MAXN];
vector<int> pre[MAXN];
queue<int> q;

int pri[MAXN];

int ans[MAXN];
int cnt;

int cntF;
int64 sol() {
    // cerr<<"sol\n";
    // cerr<<"! "<<t_q.size()<<' '<<head<<' '<<tail<<'\n';
    while(head < tail || !t_q.empty()) {
        // cerr<<head<<' '<<tail<<' '<<t_q.size()<<'\n';
        while(head < tail) {
            int u = c_q[++head];
            his_sol_time.push({u,sol_time[u]});
            sol_time[u] += weight[u];
            max_time = max(max_time, sol_time[u]);
            for(int v : adj[u]) {
                his_res.push(v);
                res[v]--;
                his_sol_time.push({v,sol_time[v]});
                sol_time[v] = max(sol_time[v], sol_time[u]);
                if(res[v] == 0) {
                    if(type[v] == 0) c_q[++tail] = v;
                    else{
                        his_t_q.push({sol_time[v], v});
                        t_q.insert({sol_time[v], v});
                    }
                }
            }
        }
        if(!t_q.empty()) {
            int u = (*t_q.begin()).second;
            for(auto x:t_q) {
                // cerr<<"! "<<x.first<<' '<<x.second<<' '<<sol_time[x.second]<<'\n';
                if(pri[x.second]<pri[u]) {
                    u = x.second;
                }
            }
            his_t_q.push({sol_time[u], -u});
            t_q.erase({sol_time[u],u});
            ++cntF;
            his_sol_time.push({u,sol_time[u]});
            sol_time[u] = F.use(sol_time[u], weight[u]);
            max_time = max(max_time, sol_time[u]);
            for(int v : adj[u]) {
                his_res.push(v);
                res[v]--;
                his_sol_time.push({v,sol_time[v]});
                sol_time[v] = max(sol_time[v], sol_time[u]);
                if(res[v] == 0) {
                    if(type[v] == 0) c_q[++tail] = v;
                    else{
                        his_t_q.push({sol_time[v], v});
                        t_q.insert({sol_time[v], v});
                    }
                }
            }
        }
    }
    // cerr<<"out,sol\n";
    return max_time;
}

void dfs()
{
    // cerr<<"dfs\n";
    // cerr<<"! "<<t_q.size()<<' '<<head<<' '<<tail<<'\n';
    while(head < tail) {
        int u = c_q[++head];
        his_sol_time.push({u,sol_time[u]});
        sol_time[u] += weight[u];
        max_time = max(max_time, sol_time[u]);
        for(int v : adj[u]) {
            his_res.push(v);
            res[v]--;
            his_sol_time.push({v,sol_time[v]});
            sol_time[v] = max(sol_time[v], sol_time[u]);
            if(res[v] == 0) {
                if(type[v] == 0) c_q[++tail] = v;
                else{
                    // his_t_q.push({sol_time[v], v});
                    t_q.insert({sol_time[v], v});
                }
            }
        }
    }

    if(t_q.empty()) {
        for(int i=1;i<=cnt;i++) cout<<ans[i]<<' ';
        cout<<'\n';
        return;
    }

    pair<int64,int> chosen = {-1,-1};
    int64 val = INF;

    int his_head = head , his_tail = tail, his_cntF = cntF;
    int64 his_max_time = max_time;
    his_sol_time.push({-1,-1});
    his_res.push({-1});

    pair<int64,int> nx = *t_q.begin(),nxt = {-1,-1};
    chosen = nx;

    int64 time1 = F.sim_use(nx.first,weight[nx.second]);
    // cerr<< nx.first<<' '<<nx.second<<' '<< nx.second<<' '<<time1<<'\n';
    while(nx.first < time1)
    {
        t_q.erase(nx);   
        int u = nx.second;
        // cerr<<u<<' '<<adj[u].size()<<"#\n";
        his_sol_time.push({u,sol_time[u]});
        ++cntF;
        sol_time[u] = F.use(nx.first,weight[nx.second]);
        max_time = max(max_time, sol_time[u]);
        for(int v : adj[u]) {
            // cerr<<u<<' '<<v<<' '<<res[v]<<'\n';
            his_res.push(v);
            res[v]--;
            his_sol_time.push({v,sol_time[v]});
            sol_time[v] = max(sol_time[v], sol_time[u]);
            if(res[v] == 0) {
                if(type[v] == 0) c_q[++tail] = v;
                else{
                    his_t_q.push({sol_time[v], v});
                    t_q.insert({sol_time[v], v});
                }
            }
        }

        int64 result = sol();
        if(result < val) {
            val = result;
            chosen = nx;
        }

        while(cntF > his_cntF) {
            --cntF;
            F.undo();
        }
        head = his_head, tail = his_tail, max_time = his_max_time;
        while(his_res.top()!=-1) {
            res[his_res.top()]++;
            his_res.pop();
        }
        // cerr<<"%";
        while(his_sol_time.top().first != -1) {
            // if(his_sol_time.size()<=1)
            // {
            //     cerr<<"$$$$$$$$$$$$$$$$\n";
            //     exit(1);
            // }
            auto x = his_sol_time.top();
            // cerr<<"& "<<x.first<<' '<<x.second<<'\n';
            sol_time[x.first] = x.second;
            his_sol_time.pop();
        }
        // cerr<<"%";
        while(!his_t_q.empty()) {
            // if(his_t_q.size()<=1)
            // {
            //     cerr<<"$$$$$$$$$$$$$$$$\n";
            //     exit(1);
            // }
            auto x = his_t_q.top();
            // cerr<<"$"<<x.first<<' '<<x.second<<' '<<t_q.size()<<'\n';
            if(x.second > 0) {
                t_q.erase(x);
            }
            else {
                t_q.insert({x.first,-x.second});
            }
            his_t_q.pop();
        }
        // cerr<<"%\n";
        auto it=(t_q.insert(nx)).first;
        ++it;

        if(it == t_q.end()) {
            break;
        }
        nx = *it;
    }
    his_sol_time.pop();
    his_res.pop();

    ans[++cnt] = chosen.second;
    nx = chosen;
    t_q.erase(nx);   
    int u = nx.second;
    ++cntF;
    sol_time[u] = F.use(nx.first,weight[nx.second]);
    max_time = max(max_time, sol_time[u]);
    for(int v : adj[u]) {
        // cerr<<u<<' '<<v<<' '<<res[v]<<'\n';
        res[v]--;
        sol_time[v] = max(sol_time[v], sol_time[u]);
        if(res[v] == 0) {
            if(type[v] == 0) c_q[++tail] = v;
            else{
                t_q.insert({sol_time[v], v});
            }
        }
    }
    dfs();
    // cerr<<"@ \n";
}

int main(int argc, char* argv[]) {
    // ios::sync_with_stdio(false);
    // cin.tie(nullptr);
    F.init();

    // cerr<< max_count<<'\n';
    cin >> n >> m;
    for (int i = 1; i <= n; ++i) {
        char c;
        cin >> c >> weight[i];
        type[i] = (c == 'c' ? 0 : 1);
        if(weight[i] == 0)  type[i] = 0;
    }
    for (int i = 1; i <= m; ++i) {
        int u,v;
        cin >> u >> v;
        adj[u].push_back(v);
        pre[v].push_back(u);
        in[v]++;
        out[u]++;
        res[v] = in[v];
    }
    for(int i=1;i<=n;i++)
    {
        if(out[i]==0)
            q.push(i);
    }
    while(!q.empty())
    {
        int u=q.front();
        q.pop();
        if(type[u]==1)
        {
            a[++n_t]={-ltail[u],u};
        }
        ltail[u]+=weight[u];
        for(int v:pre[u])
        {
            if(ltail[v]<ltail[u])
                ltail[v]=ltail[u];
            out[v]--;
            if(out[v]==0)
                q.push(v);
        }
    }
    sort(a+1,a+n_t+1);
    for(int i=1;i<=n_t;i++)
        pri[a[i].second]=i;

    for(int i = 1; i <= n; ++i) {
        if(in[i] == 0) {
            if(type[i] == 0) {
                c_q[++tail] = i;
            }
            else {
                t_q.insert({0,i});
            }
        }
    }
    
    dfs();

    // for(int i=1;i<=cnt;i++) {
    //     cout<<ans[i]<<' ';
    // }
    // cout<<'\n';

    return 0;
}
/*
8 6
t 2
c 3
t 1
c 1
t 1
c 2
t 2
c 1
1 2
2 3
3 4
5 6
6 7
7 8
*/