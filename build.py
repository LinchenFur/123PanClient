import os
import subprocess
import PyInstaller.__main__

def build_app():
    # 确保构建目录存在
    build_dir = "build"
    if not os.path.exists(build_dir):
        os.makedirs(build_dir)
    
    # 定义PyInstaller参数
    pyinstaller_args = [
        "gui.py",  # 主入口文件
        "--name=123PanClient",  # 生成的可执行文件名称
        "--onefile",  # 打包成单个可执行文件
        "--windowed",  # 无控制台窗口
        "--add-data=static;static",  # 包含静态文件
        "--add-data=logs;logs",  # 包含日志目录
        "--add-data=downloads;downloads",  # 包含下载目录
        "--icon=static/favicon.ico",  # 应用图标
        "--distpath=dist",  # 输出目录
        "--workpath=build",  # 工作目录
        "--noconfirm",  # 覆盖现有文件不提示
        "--clean"  # 清理临时文件
    ]
    
    # 添加隐藏导入
    hidden_imports = [
        "webview.platforms.winforms",
        "webview.platforms.edgechromium"
    ]
    for imp in hidden_imports:
        pyinstaller_args.append(f"--hidden-import={imp}")
    
    print("开始打包应用...")
    PyInstaller.__main__.run(pyinstaller_args)
    print("打包完成！可在dist目录找到123PanClient.exe")

if __name__ == "__main__":
    build_app()