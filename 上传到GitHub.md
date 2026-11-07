上传到 GitHub 的两种方法
========================

要上传的目录是：

    E:\小工具开发\WatermarkTool\GitHub仓库

这个目录里已经放好了 README.md、.gitignore 和源码文件。
不要上传 `发布`、`libs`、`_internal`、`批量水印工具.exe`，这些是打包产物和本地依赖，
体积很大，GitHub 也不需要它们；.gitignore 已经排除了。


方法一：网页上传（最简单，不用安装 Git）
----------------------------------------

1. 打开 https://github.com 并登录。
2. 右上角 “+” → “New repository”。
3. 填写：
   - Repository name：例如 `batch-watermark-tool`
   - Description：可填“Windows 批量去水印/加水印工具”
   - 选择 Public 或 Private
   - 不要勾选 “Add a README file”
4. 点 “Create repository”。
5. 在新仓库页面点 “uploading an existing file” 或 “Add file” → “Upload files”。
6. 打开本地 `E:\小工具开发\WatermarkTool\GitHub仓库`，
   把里面的所有文件和文件夹一起拖进网页上传区域。
   注意：是拖里面的内容，不是拖整个 `GitHub仓库` 文件夹。
7. 在下方 Commit changes 里填一句说明，例如：
   `Initial commit: batch watermark tool`
8. 点 “Commit changes”。

上传完成后刷新仓库页面，应该能看到 README.md、app.py、core.py 等文件。


方法二：用 Git 命令行
--------------------

前提：已安装 Git for Windows，并能使用 `git` 命令。

1. 先在 GitHub 网页上创建一个空仓库（不要勾选 Add a README file）。
2. 打开 PowerShell 或 CMD，执行：

    cd /d E:\小工具开发\WatermarkTool\GitHub仓库

    git init
    git config user.name "你的名字"
    git config user.email "你的邮箱"

    git add .
    git commit -m "Initial commit: batch watermark tool"
    git branch -M main

    git remote add origin https://github.com/你的用户名/你的仓库名.git
    git push -u origin main

3. 推送时如果弹出登录窗口，按提示登录 GitHub。
   GitHub 已经不支持直接输入账号密码，推荐：
   - 使用浏览器登录（Git Credential Manager），或
   - 使用 Personal Access Token 作为密码，或
   - 使用 GitHub Desktop / SSH。

4. 如果仓库创建时勾选了 README，第一次 push 可能提示拒绝：
   `failed to push some refs`
   先执行：

    git pull --rebase origin main
    git push -u origin main

5. 如果提示 `remote origin already exists`：

    git remote set-url origin https://github.com/你的用户名/你的仓库名.git

6. 如果中文文件名显示成转义形式，可执行：

    git config --global core.quotepath false


方法三：GitHub Desktop（图形界面）
----------------------------------

1. 安装 GitHub Desktop 并登录。
2. File → Add local repository，选择：
   `E:\小工具开发\WatermarkTool\GitHub仓库`
3. 如果提示 not a Git repository，选择 “create a repository”。
4. 在左下角填写 Summary，点 “Commit to main”。
5. 点右上角 “Publish repository”，选择 Public/Private，发布即可。


注意事项
--------

- 不要上传 `发布`、`libs`、`_internal`、`*.exe`、`*.zip`。
  这些文件很大，GitHub 单文件超过 100MB 会被拒绝。
- 如果只想发布可执行文件，建议用 GitHub 的 Releases 功能，
  单独上传打包好的 zip，而不是直接塞进源码仓库。
- 源码里没有账号、密码、Token 等敏感信息，可以安全上传。
- 如果没有开源协议，别人默认不能随意使用；需要的话可以在仓库里
  添加 LICENSE（例如 MIT）。
