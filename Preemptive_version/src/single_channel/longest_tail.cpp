//按照尾链长度（包括当前任务），长的优先
#include<bits/stdc++.h>
using namespace std;
const int MAXN=1e5+5;

int n,n_t,m;
pair<int,int> a[MAXN];
int type[MAXN];
int weight[MAXN];
int out[MAXN];
int ans[MAXN];
vector<int> pre[MAXN];

queue<int> q;
string G_loc,out_loc;

int main(int argc,char* argv[])
{
    // ios::sync_with_stdio(false);
    // cin.tie(nullptr);
    // if(argc<3)
    // {
    //     cerr<<"Usage: "<<argv[0]<<" <G_file> <output_file>"<<endl;
    //     return 1;
    // }
    // G_loc=argv[1];
    // out_loc=argv[2];
    // freopen(G_loc.c_str(),"r",stdin);
    // freopen(out_loc.c_str(),"w",stdout);

    cin>>n>>m;
    for(int i=1;i<=n;i++)
    {
        char c;
        cin>>c>>weight[i];
        type[i]=(c=='c'?0:1);
    }
    for(int i=1;i<=m;i++)
    {
        int u,v;
        cin>>u>>v;
        out[u]++;
        pre[v].push_back(u);
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
        ans[u]+=weight[u];
        if(type[u]==1)
        {
            a[++n_t]={-ans[u],u};
        }
        for(int v:pre[u])
        {
            if(ans[v]<ans[u])
                ans[v]=ans[u];
            out[v]--;
            if(out[v]==0)
                q.push(v);
        }
    }
    sort(a+1,a+n_t+1);
    for(int i=1;i<=n_t;i++)
        cout<<a[i].second<<" ";
}