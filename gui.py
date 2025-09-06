import webview
from flask import Flask, jsonify, request, send_file, redirect, session
from android import Pan123, folder_pause_flags
import os
import threading
import requests
import time
import logging
import datetime
import json

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
download_queue = []  # 下载队列
active_downloads = 0  # 当前活跃的下载任务数
max_concurrent_downloads = 2  # 最大并发下载数（默认值，会被配置覆盖）
download_lock = threading.Lock()  # 下载状态锁
pause_flags = {}  # file_id: bool, True if paused

# 加载配置文件
def load_config():
    global max_concurrent_downloads
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                max_concurrent_downloads = config.get('max_concurrent_downloads', 2)
                logging.info(f"从配置文件加载并发下载数: {max_concurrent_downloads}")
        else:
            logging.warning("配置文件不存在，使用默认并发下载数: 2")
    except Exception as e:
        logging.error(f"加载配置文件失败: {str(e)}")
        max_concurrent_downloads = 2

# 保存配置文件
def save_config():
    try:
        config = {}
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
        
        config['max_concurrent_downloads'] = max_concurrent_downloads
        
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        logging.info(f"配置文件已保存，并发下载数: {max_concurrent_downloads}")
    except Exception as e:
        logging.error(f"保存配置文件失败: {str(e)}")

# 确保下载目录存在
if not os.path.exists(download_path):
    os.makedirs(download_path)

def progress_callback(filename, downloaded, total, speed, file_id=None, status='downloading'):
    """下载进度回调函数"""
    global download_progress
    percentage = int((downloaded / total) * 100) if total > 0 else 0
    
    if filename in download_progress:
        download_progress[filename]['downloaded'] = downloaded
        download_progress[filename]['total'] = total
        download_progress[filename]['percentage'] = percentage
        download_progress[filename]['speed'] = speed
        if file_id:
            download_progress[filename]['file_id'] = file_id
        download_progress[filename]['status'] = status
    else:
        download_progress[filename] = {
            'downloaded': downloaded,
            'total': total,
            'percentage': percentage,
            'speed': speed,
            'file_id': file_id,
            'status': status
        }
    # 记录下载进度到日志
    logging.info(f"文件下载进度: {filename} - {percentage}% ({downloaded}/{total} bytes) 速度: {speed} 状态: {status}")

@app.route('/')
def index():
    # 检查是否已初始化
    if pan is None:
        return redirect('/login')
    response = send_file('static/index.html')
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

@app.route('/login')
def login_page():
    response = send_file('static/login.html')
    response.headers['Content-Type'] = 'text/html; charset=utf-8'
    return response

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

def download_file_task(file_id, recursive=False):
    global active_downloads, download_queue
    paused = False  # Initialize paused variable
    
    try:
        # 获取文件详情
        file_info = next((f for f in pan.list if f["FileNum"] == file_id), None)
        if not file_info:
            logging.error(f"下载错误: 找不到文件ID {file_id}")
            return
            
        if file_info["Type"] == 1 and recursive:
            # 递归下载文件夹
            folder_name = file_info["FileName"]
            logging.info(f"开始递归下载文件夹: {folder_name}")
            
            # 根据file_id获取文件索引
            file_index = next((idx for idx, f in enumerate(pan.list) if f["FileNum"] == file_id), None)
            if file_index is None:
                logging.error(f"无法找到文件ID {file_id} 对应的文件")
                return
                
            # 使用新的递归下载功能
            def folder_progress_callback(progress_info):
                """文件夹下载进度回调"""
                global download_progress
                filename = progress_info['filename']
                
                # 检查暂停状态
                status = 'paused' if pause_flags.get(file_id, False) else 'downloading'
                
                download_progress[filename] = {
                    'downloaded': progress_info['downloaded'],
                    'total': progress_info['total'],
                    'percentage': progress_info['percentage'],
                    'speed': progress_info['speed'],
                    'type': 'folder' if '文件夹:' in filename else 'file',
                    'file_id': file_id,
                    'status': status
                }
                # 记录下载进度到日志
                logging.info(f"文件下载进度: {filename} - {progress_info['percentage']}% ({progress_info['downloaded']}/{progress_info['total']}) 速度: {progress_info['speed']} 状态: {status}")
            
            # 添加暂停检查循环
            def download_with_pause_check():
                nonlocal file_index, folder_progress_callback
                while pause_flags.get(file_id, False):
                    time.sleep(0.5)
                    # 更新状态为暂停
                    folder_key = f"文件夹: {folder_name}"
                    if folder_key in download_progress:
                        download_progress[folder_key]['status'] = 'paused'
                
                success = pan.download(file_index, download_path, folder_progress_callback, recursive=True)
                return success
            
            success = download_with_pause_check()
            
            if success:
                logging.info(f"文件夹递归下载完成: {folder_name}")
                # 延迟删除进度信息
                time.sleep(2)
                folder_key = f"文件夹: {folder_name}"
                if folder_key in download_progress:
                    del download_progress[folder_key]
            else:
                logging.error(f"文件夹递归下载失败: {folder_name}")
                folder_key = f"文件夹: {folder_name}"
                if folder_key in download_progress:
                    download_progress[folder_key]['speed'] = "下载失败"
            
        else:
            # 单个文件或ZIP打包的文件夹下载
            filename = file_info["FileName"]
            if file_info["Type"] == 1:  # 文件夹
                filename += ".zip"
                
            # Initialize progress with file_id and type
            if filename not in download_progress:
                download_progress[filename] = {}
            download_progress[filename]['file_id'] = file_id
            download_progress[filename]['type'] = 'file' if file_info["Type"] == 0 else 'folder'
                
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
                progress_callback(filename, -1, -1, f"获取链接失败: {str(e)}", file_id, 'error')
                return
                
            # 确保获取到有效的下载链接
            if down_load_url is None:
                progress_callback(filename, -1, -1, "获取下载链接失败", file_id, 'error')
                return

            # 检查文件是否存在并获取当前大小用于恢复下载
            if os.path.exists(file_path):
                current_size = os.path.getsize(file_path)
            else:
                current_size = 0

            # 添加必要的请求头，支持断点续传
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Referer": "https://www.123pan.com/",
            }
            if current_size > 0:
                headers["Range"] = f"bytes={current_size}-"
            
            # 使用优化后的下载逻辑
            down = requests.get(down_load_url, headers=headers, stream=True, timeout=30)
            file_size = file_info["Size"]  # 使用文件信息中的总大小
            data_count = current_size  # 从当前大小开始计数
            time1 = time.time()
            time_temp = time1
            data_count_temp = data_count
            
            paused = False
            with open(file_path, "ab") as f:  # 使用追加模式支持断点续传
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
                            speed_print,
                            file_id,
                            'downloading'
                        )

                    # 检查暂停标志
                    if pause_flags.get(file_id, False):
                        paused = True
                        progress_callback(filename, data_count, file_size, "Paused", file_id, 'paused')
                        # 等待直到继续下载
                        while pause_flags.get(file_id, False):
                            time.sleep(0.5)
                        # 继续下载后更新状态
                        progress_callback(filename, data_count, file_size, "继续中", file_id, 'downloading')
                        paused = False
            
            # 下载完成后检查
            if file_size > 0 and data_count == file_size:
                progress_callback(filename, file_size, file_size, "下载完成", file_id, 'completed')
            else:
                # 下载不完整
                progress_callback(filename, data_count, file_size, "下载不完整", file_id, 'error')
                
            # 延迟删除进度信息
            time.sleep(5)
            if filename in download_progress:
                del download_progress[filename]
                
    except Exception as e:
        logging.error(f"下载失败: {str(e)}")
        # 标记失败状态
        if 'file_info' in locals():
            filename = file_info["FileName"]
            if file_info["Type"] == 1:
                filename += ".zip"
            progress_callback(filename, -1, -1, f"失败: {str(e)}", file_id, 'error')
    finally:
        # 只在下载真正完成时才减少活跃下载计数并处理队列
        # 如果是暂停状态，线程会继续运行，不减少计数
        if not paused:
            global active_downloads, download_queue
            with download_lock:
                active_downloads -= 1
                logging.info(f"下载任务完成，当前活跃下载数: {active_downloads}")
                # 检查队列中是否有等待的任务
                if download_queue and active_downloads < max_concurrent_downloads:
                    next_file_id, next_recursive = download_queue.pop(0)
                    active_downloads += 1
                    threading.Thread(target=download_file_task, args=(next_file_id, next_recursive)).start()
                    logging.info(f"从队列启动下载任务: {next_file_id}, 递归: {next_recursive}")

@app.route('/api/download/<int:file_id>', methods=['GET'])
def download_file(file_id):
    global active_downloads, download_queue
    
    if pan is None:
        return jsonify({"error": "App not initialized"}), 400
    
    # 获取查询参数，是否递归下载文件夹
    recursive = request.args.get('recursive', 'false').lower() == 'true'
    
    logging.info(f"收到下载请求: file_id={file_id}, recursive={recursive}")
    
    # 查找文件信息
    file_info = next((f for f in pan.list if f["FileNum"] == file_id), None)
    if not file_info:
        logging.error(f"找不到文件ID: {file_id}")
        return jsonify({"error": "File not found"}), 404
    
    # 使用锁控制并发下载
    with download_lock:
        if active_downloads < max_concurrent_downloads:
            # 直接启动下载任务
            active_downloads += 1
            logging.info(f"直接启动下载任务: file_id={file_id}, 递归={recursive}, 当前活跃下载数: {active_downloads}")
            threading.Thread(target=download_file_task, args=(file_id, recursive)).start()
        else:
            # 加入下载队列
            download_queue.append((file_id, recursive))
            logging.info(f"下载任务加入队列: file_id={file_id}, 递归={recursive}, 队列长度: {len(download_queue)}")
    
    return jsonify({
        "status": "started" if active_downloads <= max_concurrent_downloads else "queued",
        "file": file_info,
        "recursive": recursive,
        "queue_position": len(download_queue) if active_downloads >= max_concurrent_downloads else 0
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

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """获取当前设置"""
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                config = json.load(f)
                return jsonify(config)
        else:
            return jsonify({"max_concurrent_downloads": 2})
    except Exception as e:
        logging.error(f"获取设置失败: {str(e)}")
        return jsonify({"error": "获取设置失败"}), 500

@app.route('/api/settings', methods=['POST'])
def save_settings():
    """保存设置"""
    try:
        data = request.json
        global max_concurrent_downloads
        
        # 更新全局变量
        max_concurrent_downloads = data.get('max_concurrent_downloads', 2)
        
        # 保存到配置文件
        save_config()
        
        logging.info(f"设置已保存: 并发下载数 = {max_concurrent_downloads}")
        return jsonify({"status": "success"})
    except Exception as e:
        logging.error(f"保存设置失败: {str(e)}")
        return jsonify({"error": "保存设置失败"}), 500

@app.route('/api/pause/<int:file_id>', methods=['POST'])
def pause_download(file_id):
    # 检查是否为文件夹下载
    is_folder = False
    for filename, progress in download_progress.items():
        if progress.get('file_id') == file_id and progress.get('type') == 'folder':
            is_folder = True
            break
    
    if is_folder:
        folder_pause_flags[file_id] = True
        logging.info(f"暂停文件夹下载请求: file_id={file_id}, 设置folder_pause_flags[{file_id}]={folder_pause_flags[file_id]}")
    else:
        pause_flags[file_id] = True
        logging.info(f"暂停文件下载请求: file_id={file_id}, 设置pause_flags[{file_id}]={pause_flags[file_id]}")
    
    # 更新进度状态为暂停
    for filename, progress in download_progress.items():
        if progress.get('file_id') == file_id:
            progress['status'] = 'paused'
    
    return jsonify({"status": "paused"})

@app.route('/api/resume/<int:file_id>', methods=['POST'])
def resume_download(file_id):
    # 检查是否为文件夹下载
    is_folder = False
    for filename, progress in download_progress.items():
        if progress.get('file_id') == file_id and progress.get('type') == 'folder':
            is_folder = True
            break
    
    if is_folder:
        folder_pause_flags[file_id] = False
        logging.info(f"继续文件夹下载请求: file_id={file_id}, 设置folder_pause_flags[{file_id}]={folder_pause_flags[file_id]}")
    else:
        pause_flags[file_id] = False
        logging.info(f"继续文件下载请求: file_id={file_id}, 设置pause_flags[{file_id}]={pause_flags[file_id]}")
    
    # 更新进度状态为下载中
    for filename, progress in download_progress.items():
        if progress.get('file_id') == file_id:
            progress['status'] = 'downloading'
    
    return jsonify({"status": "resumed"})


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
    
    # 加载配置文件设置
    load_config()
    
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