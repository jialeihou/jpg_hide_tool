# JPG 文件隐藏工具

## 功能

1. 将任意类型文件隐藏到 JPG/JPEG 图片中；
2. 支持一次隐藏多个文件；
3. 隐藏后的 JPG 仍可正常打开；
4. 可释放隐藏文件，并恢复原文件名和后缀；
5. 提供 HTML 前台页面；
6. 支持一键清理系统生成的导入缓存和导出结果；
7. 仅使用 Python 标准库，无需安装第三方依赖；
8. 适配麒麟 Linux、macOS，以及其他安装 Python 3 的系统。

## 运行方法

### macOS

双击：

```bash
start_mac.command
```

如果提示无权限，可在终端执行：

```bash
chmod +x start_mac.command
./start_mac.command
```

### 麒麟 Linux / 其他 Linux

```bash
chmod +x start_linux.sh
./start_linux.sh
```

或者直接：

```bash
python3 app.py
```

启动后浏览器打开：

```text
http://127.0.0.1:8765/
```

## 目录说明

- `app.py`：主程序；
- `uploads/`：临时上传文件目录；
- `output/`：生成的隐藏 JPG、释放结果 ZIP；
- `extracted/`：释放出的原始文件目录；
- `start_mac.command`：macOS 启动脚本；
- `start_linux.sh`：麒麟/Linux 启动脚本。

页面中的“清理导入/导出文件”按钮会删除 `uploads/`、`output/`、`extracted/` 三个目录中的内容，包括上传缓存、生成的隐藏 JPG/ZIP、释放出的文件目录；按钮只保留这三个目录本身，方便继续使用。

## 重要说明

- 本工具采用“在 JPG 文件尾部追加隐藏数据”的方式，图片查看器一般会忽略 JPG 结束标记后的数据，所以图片仍可打开。
- 请不要对生成后的 JPG 进行压缩、裁剪、转格式或用图片编辑器重新保存，否则隐藏数据可能丢失。
- 本工具不是加密工具。如有保密要求，建议先把待隐藏文件压缩并加密，再隐藏到 JPG 中。
- “清理导入/导出文件”只作用于本工具目录下的 `uploads/`、`output/`、`extracted/`，不会删除用户电脑其他位置的文件。
- 其他平台“解压即可运行”的前提是系统已安装 Python 3。若完全没有 Python，需要用 PyInstaller 等工具分别在对应平台打包二进制程序。由于 macOS 与麒麟 Linux 架构不同，不能用一个二进制文件同时兼容全部平台。

## 可选：自行打包成可执行程序

如果某个平台没有 Python 运行环境，可在有外网或已准备离线包的同类系统上安装 PyInstaller 后执行：

```bash
pyinstaller --onefile app.py
```

注意：macOS、麒麟 Linux 需要分别在各自系统上打包。
