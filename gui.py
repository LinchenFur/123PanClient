import webview
from flask import Flask, jsonify, request, send_file, redirect, session
from android import Pan123
import os
import threading
import requests
import time
import logging
import datetime

# 确保日志目录存在
log_dir = 'logs'
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# 配置日志系统
def setup_logging():
    # 创建按日期命名的日志文件
    log_filename = f"operation_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_filepath = os.path.join(log_dir, log_filename)
    
    # 配置日志格式和级别
    logging.basicConfig(
        filename=log_filepath,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 同时输出到控制台
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logging.getLogger().addHandler(console_handler)
    
    logging.info("日志系统初始化完成")

app = Flask(__name__, static_folder='static')
app.secret_key = '123pan_secret_key'  # 设置session密钥
pan = None
download_path = 'downloads'
download_progress = {}  # 存储下载进度信息

# 确保下载目录存在
if not os.path.exists(download_path):
    os.makedirs(download_path)

def progress_callback(filename, downloaded, total, speed):
    """下载进度回调函数"""
    global download_progress
    percentage = int((downloaded / total) * 100) if total > 0 else 0
    download_progress[filename] = {
        'downloaded': downloaded,
        'total': total,
        'percentage': percentage,
        'speed': speed
    }
    # 记录下载进度到日志
    logging.info(f"文件下载进度: {filename} - {percentage}% ({downloaded}/{total} bytes) 速度: {speed}")

@app.route('/')
def index():
    # 检查是否已初始化
    if pan is None:
        return redirect('/login')
    return send_file('static/index.html')

@app.route('/login')
def login_page():
    return send_file('static/login.html')

@app.route('/api/init', methods=['POST'])
def init_app():
    global pan
    data = request.json
    try:
        # 优先尝试使用保存的凭据自动登录
        try:
            logging.info("尝试自动登录...")
            pan = Pan123(
                readfile=True,  # 启用文件读取
                user_name="",    # 不提供用户名
                pass_word="",    # 不提供密码
                input_pwd=False
            )
            logging.info(f"自动登录: 用户名={pan.user_name}, 授权={pan.authorization is not None}")
            
            # 检查凭据是否有效
            if pan.authorization:
                # 尝试获取文件列表验证凭据
                result = pan.get_dir()
                logging.info(f"自动登录获取文件列表结果: {result}")
                if result == 0:
                    # 设置session
                    session['username'] = pan.user_name
                    logging.info(f"自动登录成功: {pan.user_name}")
                    return jsonify({
                        "status": "initialized",
                        "loggedIn": True
                    })
        except Exception as e:
            logging.error(f"自动登录失败: {str(e)}")
            # 继续尝试使用传入的凭据
        
        # 如果自动登录失败或未提供保存的凭据，使用传入的凭据
        if data.get('username') and data.get('password'):
            logging.info(f"尝试手动登录: {data.get('username')}")
            pan = Pan123(
                readfile=False,
                user_name=data.get('username'),
                pass_word=data.get('password'),
                input_pwd=False
            )
            # 尝试登录
            result = pan.login()
            logging.info(f"手动登录结果: {result}")
            if result == 0 or result == 200:
                session['username'] = data.get('username')
                logging.info(f"手动登录成功: {data.get('username')}")
                return jsonify({
                    "status": "initialized",
                    "loggedIn": True
                })
        
        logging.warning("登录失败")
        return jsonify({
            "status": "initialized",
            "loggedIn": False
        })
    except Exception as e:
        logging.error(f"初始化失败: {str(e)}")
        return jsonify({
            "error": "初始化失败",
            "details": str(e)
        }), 500

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if pan is None:
        return jsonify({"error": "App not initialized"}), 400
    
    # 实际登录逻辑
    try:
        logging.info(f"尝试登录账号: {data.get('username', '未提供用户名')}")
        result = pan.login()
        
        # 登录成功返回0，但服务器实际返回200表示成功
        # 所以我们检查是否返回0或200都视为成功
        if result == 0 or result == 200:
            pan.get_dir()
            logging.info(f"登录成功，获取到 {len(pan.list)} 个文件")
            # 设置登录状态
            session['username'] = data.get('username')
            return jsonify({
                "status": "success"
            })
        else:
            error_msg = f"登录失败，错误代码: {result}"
            logging.error(error_msg)
            return jsonify({
                "error": "Login failed",
                "code": result,
                "message": error_msg
            }), 401
    except Exception as e:
        error_msg = f"登录异常: {str(e)}"
        logging.error(error_msg)
        return jsonify({
            "error": "Login exception",
            "details": error_msg
        }), 500

@app.route('/api/check_login', methods=['GET'])
def check_login():
    if pan is not None and pan.authorization:  # 使用authorization替代token
        return jsonify({"loggedIn": True})
    return jsonify({"loggedIn": False})

@app.route('/api/files', methods=['GET'])
def list_files():
    if pan is None:
        logging.error("文件列表错误: 应用未初始化")
        return jsonify({"error": "App not initialized"}), 400
    
    try:
        result = pan.get_dir()
        
        if result != 0:
            error_msg = f"获取文件列表失败，错误代码: {result}"
            logging.error(error_msg)
            return jsonify({
                "error": error_msg,
                "code": result
            }), 500
        
        
        # 构建可序列化的文件列表
        file_list = []
        for item in pan.list:
            file_list.append({
                "FileId": item.get("FileId"),
                "FileName": item.get("FileName"),
                "Type": item.get("Type"),
                "Size": item.get("Size"),
                "CreateAt": str(item.get("CreateAt")) if item.get("CreateAt") else "",
                "UpdateAt": str(item.get("UpdateAt")) if item.get("UpdateAt") else "",
                "FileNum": item.get("FileNum")
            })
            
        logging.info(f"返回文件列表: {len(file_list)} 项")
        return jsonify({
            "files": file_list,
            "currentPath": pan.parent_file_id
        })
    except Exception as e:
        error_msg = f"文件列表异常: {str(e)}"
        logging.error(error_msg)
        return jsonify({
            "error": "文件列表错误",
            "details": error_msg
        }), 500

def download_file_task(file_id):
    try:
        # 获取文件详情
        file_info = next((f for f in pan.list if f["FileNum"] == file_id), None)
        if not file_info:
            logging.error(f"下载错误: 找不到文件ID {file_id}")
            return
            
        filename = file_info["FileName"]
        if file_info["Type"] == 1:  # 文件夹
            filename += ".zip"
            
        file_path = os.path.join(download_path, filename)
        
        # 检查文件是否已存在
        if os.path.exists(file_path):
            # 在GUI环境中直接覆盖
            logging.warning(f"覆盖已存在文件: {filename}")
        
        # 确保下载目录存在
        if not os.path.exists(download_path):
            os.makedirs(download_path)
            
        # 根据file_id获取文件索引
        file_index = next((idx for idx, f in enumerate(pan.list) if f["FileNum"] == file_id), None)
        if file_index is None:
            logging.error(f"无法找到文件ID {file_id} 对应的文件")
            return
            
        # 获取下载链接
        try:
            down_load_url = pan.link(file_index, showlink=False)
            logging.debug(f"获取下载链接: {down_load_url}")  # 调试信息
        except Exception as e:
            logging.error(f"获取下载链接失败: {str(e)}")
            progress_callback(filename, -1, -1, f"获取链接失败: {str(e)}")
            return
            
        # 确保获取到有效的下载链接
        if down_load_url is None:
            progress_callback(filename, -1, -1, "获取下载链接失败")
            return
            
        # 添加必要的请求头
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://www.123pan.com/",
        }
        
        # 使用优化后的下载逻辑
        down = requests.get(down_load_url, headers=headers, stream=True, timeout=30)
        file_size = int(down.headers.get("Content-Length", 0))
        data_count = 0
        time1 = time.time()
        time_temp = time1
        data_count_temp = 0
        
        with open(file_path, "wb") as f:
            # 使用64KB分块提高效率
            for chunk in down.iter_content(64*1024):  # 64KB chunks
                if not chunk:
                    continue
                    
                f.write(chunk)
                data_count += len(chunk)
                
                # 实时更新进度
                now_jd = (data_count / file_size) * 100 if file_size > 0 else 0
                
                # 计算下载速度（每100ms更新一次）
                current_time = time.time()
                elapsed = current_time - time_temp
                if elapsed > 0.1:  # 至少100ms更新一次
                    speed = (data_count - data_count_temp) / elapsed
                    data_count_temp = data_count
                    time_temp = current_time
                    
                    if speed > 1048576:  # >1MB/s
                        speed_print = f"{speed/1048576:.2f}M/S"
                    else:
                        speed_print = f"{speed/1024:.2f}K/S"
                        
                    # 调用进度回调
                    progress_callback(
                        filename,
                        data_count,
                        file_size,
                        speed_print
                    )
        
        # 下载完成后检查
        if file_size > 0 and data_count == file_size:
            progress_callback(filename, file_size, file_size, "下载完成")
        else:
            # 下载不完整
            progress_callback(filename, data_count, file_size, "下载不完整")
            
        # 延迟删除进度信息
        time.sleep(5)
        if filename in download_progress:
            del download_progress[filename]
            
    except Exception as e:
        logging.error(f"下载失败: {str(e)}")
        # 标记失败状态
        progress_callback(filename, -1, -1, f"失败: {str(e)}")

@app.route('/api/download/<int:file_id>', methods=['GET'])
def download_file(file_id):
    if pan is None:
        return jsonify({"error": "App not initialized"}), 400
    
    logging.info(f"收到下载请求: file_id={file_id}")
    
    # 查找文件信息
    file_info = next((f for f in pan.list if f["FileNum"] == file_id), None)
    if not file_info:
        logging.error(f"找不到文件ID: {file_id}")
        return jsonify({"error": "File not found"}), 404
    
    # 直接启动下载任务
    logging.info(f"开始下载文件: file_id={file_id}, 文件名={file_info['FileName']}")
    thread = threading.Thread(target=download_file_task, args=(file_id,))
    thread.start()
    
    return jsonify({
        "status": "started",
        "file": file_info
    })

@app.route('/api/cd/<int:dir_id>', methods=['POST'])
def change_dir(dir_id):
    if pan is None:
        return jsonify({"error": "App not initialized"}), 400
    
    pan.cdById(dir_id)
    pan.get_dir()
    return jsonify({
        "files": pan.list,
        "currentPath": pan.parent_file_id
    })

@app.route('/api/progress', methods=['GET'])
def get_download_progress():
    """获取所有下载进度信息"""
    return jsonify(download_progress)


def auto_login():
    global pan
    try:
        logging.info("尝试自动登录...")
        pan = Pan123(
            readfile=True,
            user_name="",
            pass_word="",
            input_pwd=False
        )
        logging.info(f"自动登录: 用户名={pan.user_name}, 授权={pan.authorization is not None}")
        
        if pan.authorization:
            result = pan.get_dir()
            logging.info(f"自动登录获取文件列表结果: {len(pan.list)} 个文件")
            if result == 0:
                logging.info(f"自动登录成功: {pan.user_name}")
                return True
    except Exception as e:
        logging.error(f"自动登录失败: {str(e)}")
    return False

if __name__ == '__main__':
    # 初始化日志系统
    setup_logging()
    
    # 应用启动时尝试自动登录
    auto_login()
    
    # 添加日志记录配置迁移完成
    logging.info("用户配置已迁移到config.json文件")
    
    window = webview.create_window(
        '123云盘客户端',
        app,
        width=1200,
        height=800
    )
    webview.start()