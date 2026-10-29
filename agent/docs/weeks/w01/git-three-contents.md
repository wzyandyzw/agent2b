# 三份内容实验（1.4）实录

可丢弃仓库里跑的真实命令与输出。问题：改成 A 并 add，再改成 B 不 add，commit 里是 A 还是 B？

```
$ 改成 A 并 add
$ 再改成 B，不 add
$ git status --short
MM tools.md
$ git diff            # 工作区 vs 暂存区
@@ -1 +1 @@
-get_product_spec: 按型号查规格（A：含挂牌价）
+get_product_spec: 按型号查规格（B：含挂牌价与交期天数）
$ git diff --cached   # 暂存区 vs HEAD
@@ -1 +1 @@
-get_product_spec: 按型号查规格
+get_product_spec: 按型号查规格（A：含挂牌价）
$ git commit -m "改工具描述"
$ git show --stat HEAD | tail -2
 tools.md | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
$ git show HEAD:tools.md   # 提交里是哪一版？
get_product_spec: 按型号查规格（A：含挂牌价）
$ cat tools.md             # 工作区还是 B
get_product_spec: 按型号查规格（B：含挂牌价与交期天数）
$ git status --short
 M tools.md
```

结论：commit 里是 A（暂存区那一版），工作区仍是 B，`status` 显示 ` M`。所以 AI 不能只看文件就说"已提交"：要看 `diff --cached`。
