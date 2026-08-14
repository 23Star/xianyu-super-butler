"""项目启动入口：

1. 创建 CookieManager，按配置文件 / 环境变量初始化账号任务
2. 在后台线程启动 FastAPI (reply_server) 提供管理与自动回复接口
3. 主协程保持运行
"""

import os
import sys
import shutil
from pathlib import Path

# 设置标准输出编码为UTF-8（Windows兼容）
def _setup_console_encoding():
    """设置控制台编码为UTF-8，避免Windows GBK编码问题"""
    if sys.platform == 'win32':
        try:
            # 方法1: 设置环境变量
            os.environ['PYTHONIOENCODING'] = 'utf-8'
            
            # 方法2: 尝试设置控制台代码页为UTF-8
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleOutputCP(65001)  # UTF-8代码页
            except Exception:
                pass
            
            # 方法3: 重新包装stdout和stderr
            try:
                if hasattr(sys.stdout, 'buffer'):
                    import io
                    # 只在编码不是UTF-8时重新包装
                    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
                        sys.stdout = io.TextIOWrapper(
                            sys.stdout.buffer, 
                            encoding='utf-8', 
                            errors='replace',
                            line_buffering=True
                        )
                    if sys.stderr.encoding and sys.stderr.encoding.lower() not in ('utf-8', 'utf8'):
                        sys.stderr = io.TextIOWrapper(
                            sys.stderr.buffer, 
                            encoding='utf-8', 
                            errors='replace',
                            line_buffering=True
                        )
            except Exception:
                pass
        except Exception:
            pass

# 在程序启动时设置编码
_setup_console_encoding()

# 定义ASCII安全字符（备用方案）
_OK = '[OK]'
_WARN = '[WARN]'
_ERROR = '[ERROR]'
_INFO = '[INFO]'

# ==================== 在导入任何模块之前先迁移数据库 ====================
def _migrate_database_files_early():
    """在启动前检查并迁移数据库文件到data目录（使用print，因为logger还未初始化）"""
    print("检查数据库文件位置...")
    
    # 确保data目录存在
    data_dir = Path("data")
    if not data_dir.exists():
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"{_OK} 创建 data 目录")
    
    # 定义需要迁移的文件
    files_to_migrate = [
        ("xianyu_data.db", "data/xianyu_data.db", "主数据库"),
    ]
    
    migrated_files = []
    
    # 迁移主数据库和统计数据库
    for old_path, new_path, description in files_to_migrate:
        old_file = Path(old_path)
        new_file = Path(new_path)
        
        if old_file.exists():
            if not new_file.exists():
                # 新位置不存在，移动文件
                try:
                    shutil.move(str(old_file), str(new_file))
                    print(f"{_OK} 迁移{description}: {old_path} -> {new_path}")
                    migrated_files.append(description)
                except Exception as e:
                    print(f"{_WARN} 无法迁移{description}: {e}")
                    print(f"  尝试复制文件...")
                    try:
                        shutil.copy2(str(old_file), str(new_file))
                        print(f"{_OK} 已复制{description}到新位置")
                        print(f"  请在确认数据正常后手动删除: {old_path}")
                        migrated_files.append(f"{description}(已复制)")
                    except Exception as e2:
                        print(f"{_ERROR} 复制{description}失败: {e2}")
            else:
                # 新位置已存在，检查旧文件大小
                try:
                    if old_file.stat().st_size > 0:
                        print(f"{_WARN} 发现旧{description}文件: {old_path}")
                        print(f"  新数据库位于: {new_path}")
                        print(f"  建议备份后删除旧文件")
                except:
                    pass
    
    # 迁移备份文件
    backup_files = list(Path(".").glob("xianyu_data_backup_*.db"))
    if backup_files:
        print(f"发现 {len(backup_files)} 个备份文件")
        backup_migrated = 0
        for backup_file in backup_files:
            new_backup_path = data_dir / backup_file.name
            if not new_backup_path.exists():
                try:
                    shutil.move(str(backup_file), str(new_backup_path))
                    print(f"{_OK} 迁移备份文件: {backup_file.name}")
                    backup_migrated += 1
                except Exception as e:
                    print(f"{_WARN} 无法迁移备份文件 {backup_file.name}: {e}")
        
        if backup_migrated > 0:
            migrated_files.append(f"{backup_migrated}个备份文件")
    
    # 输出迁移总结
    if migrated_files:
        print(f"{_OK} 数据库迁移完成，已迁移: {', '.join(migrated_files)}")
    else:
        print(f"{_OK} 数据库文件检查完成")
    
    return True

# 在导入 db_manager 之前先执行数据库迁移
try:
    _migrate_database_files_early()
except Exception as e:
    print(f"{_WARN} 数据库迁移检查失败: {e}")
    # 继续启动，因为可能是首次运行

# ==================== 检查并安装Playwright浏览器 ====================
def _check_and_install_playwright():
    """检查Playwright浏览器是否存在，如果不存在则自动安装"""
    print("检查Playwright浏览器...")
    
    # 检查是否安装了playwright模块
    try:
        import playwright
    except ImportError:
        print(f"{_WARN} Playwright模块未安装，跳过浏览器检查")
        return False
    
    # 检查Playwright浏览器是否存在
    playwright_installed = False
    possible_paths = []
    
    # 如果是打包后的exe，优先检查exe同目录
    if getattr(sys, 'frozen', False):
        exe_dir = Path(sys.executable).parent
        playwright_dir = exe_dir / 'playwright'
        possible_paths.insert(0, playwright_dir)  # 插入到最前面，优先检查
        
        # 检查exe同目录的浏览器是否完整
        if playwright_dir.exists():
            chromium_dirs = list(playwright_dir.glob('chromium-*'))
            if chromium_dirs:
                chromium_dir = chromium_dirs[0]
                chrome_exe = chromium_dir / 'chrome-win' / 'chrome.exe'
                if chrome_exe.exists() and chrome_exe.stat().st_size > 0:
                    print(f"{_OK} 找到已提取的Playwright浏览器: {chrome_exe}")
                    print(f"{_INFO} 浏览器版本: {chromium_dir.name}")
                    # 清除可能存在的旧环境变量，使用实际存在的浏览器
                    if 'PLAYWRIGHT_BROWSERS_PATH' in os.environ:
                        old_path = os.environ['PLAYWRIGHT_BROWSERS_PATH']
                        if old_path != str(playwright_dir):
                            print(f"{_INFO} 清除旧的环境变量: {old_path}")
                            del os.environ['PLAYWRIGHT_BROWSERS_PATH']
                    # 确保环境变量已设置
                    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(playwright_dir)
                    print(f"{_INFO} 已设置PLAYWRIGHT_BROWSERS_PATH: {playwright_dir}")
                    playwright_installed = True
                    return True
    
    # 镜像和自定义安装都靠这个环境变量指定浏览器位置（容器里是 /ms-playwright）。
    # 不先看它就会一路找不到，最后靠"真的启动一次浏览器"来判断有没有装，
    # 在低配设备上这一次多余的冷启动就够把内存顶到 OOM。
    env_browsers_path = os.getenv('PLAYWRIGHT_BROWSERS_PATH')
    if env_browsers_path and env_browsers_path not in ('0', 'false'):
        possible_paths.append(Path(env_browsers_path))

    # Windows上的常见位置
    if sys.platform == 'win32':
        # 用户缓存目录
        user_cache = Path.home() / '.cache' / 'ms-playwright'
        possible_paths.append(user_cache)

        # LocalAppData目录
        local_appdata = os.getenv('LOCALAPPDATA')
        if local_appdata:
            possible_paths.append(Path(local_appdata) / 'ms-playwright')

        # AppData目录
        appdata = os.getenv('APPDATA')
        if appdata:
            possible_paths.append(Path(appdata) / 'ms-playwright')
    elif sys.platform == 'darwin':
        possible_paths.append(Path.home() / 'Library' / 'Caches' / 'ms-playwright')
    else:
        possible_paths.append(Path.home() / '.cache' / 'ms-playwright')

    # 各平台的浏览器可执行文件相对路径。
    # 新版 Playwright 在 macOS 上改用 Chrome for Testing，旧版是 Chromium。
    browser_exe_candidates = (
        Path('chrome-win') / 'chrome.exe',
        Path('chrome-mac') / 'Chromium.app' / 'Contents' / 'MacOS' / 'Chromium',
        Path('chrome-mac-arm64') / 'Chromium.app' / 'Contents' / 'MacOS' / 'Chromium',
        Path('chrome-mac') / 'Google Chrome for Testing.app' / 'Contents' / 'MacOS' / 'Google Chrome for Testing',
        Path('chrome-mac-arm64') / 'Google Chrome for Testing.app' / 'Contents' / 'MacOS' / 'Google Chrome for Testing',
        Path('chrome-linux') / 'chrome',
    )

    # 检查是否存在chromium浏览器
    for path in possible_paths:
        if path.exists():
            # 查找chromium目录
            chromium_dirs = list(path.glob('chromium-*'))
            if chromium_dirs:
                for chromium_dir in chromium_dirs:
                    for relative_exe in browser_exe_candidates:
                        browser_exe = chromium_dir / relative_exe
                        if browser_exe.exists():
                            print(f"{_OK} 找到Playwright浏览器: {browser_exe}")
                            # 设置环境变量
                            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(path)
                            playwright_installed = True
                            break
                    if playwright_installed:
                        break
                if playwright_installed:
                    break
    
    # 如果没找到，尝试使用playwright命令检查
    if not playwright_installed:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                try:
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                    print(f"{_OK} Playwright浏览器已安装（通过API检测）")
                    playwright_installed = True
                except Exception:
                    pass
        except Exception:
            pass
    
    # 如果没找到，先尝试从临时目录提取（如果是打包的exe）
    if not playwright_installed and getattr(sys, 'frozen', False):
        try:
            exe_dir = Path(sys.executable).parent
            playwright_dir = exe_dir / 'playwright'
            
            if hasattr(sys, '_MEIPASS'):
                temp_dir = Path(sys._MEIPASS)
                temp_playwright = temp_dir / 'playwright'
                
                if temp_playwright.exists():
                    # 查找所有 chromium 相关目录（包括 chromium-* 和 chromium_headless_shell-*）
                    temp_chromium_dirs = list(temp_playwright.glob('chromium*'))
                    if temp_chromium_dirs:
                        print(f"{_INFO} 检测到打包的浏览器文件，正在提取...")
                        playwright_dir.mkdir(parents=True, exist_ok=True)
                        extracted_count = 0
                        
                        for temp_chromium_dir in temp_chromium_dirs:
                            temp_chrome_win = temp_chromium_dir / 'chrome-win'
                            
                            # 检查完整版或 headless_shell 版
                            temp_chrome_exe = temp_chrome_win / 'chrome.exe'
                            temp_headless_exe = temp_chrome_win / 'headless_shell.exe'
                            
                            # 验证文件是否存在
                            is_valid = False
                            if temp_chromium_dir.name.startswith('chromium_headless_shell'):
                                is_valid = temp_headless_exe.exists() and temp_headless_exe.stat().st_size > 0
                            else:
                                is_valid = temp_chrome_exe.exists() and temp_chrome_exe.stat().st_size > 0
                            
                            if is_valid:
                                target_chromium_dir = playwright_dir / temp_chromium_dir.name
                                
                                if not target_chromium_dir.exists():
                                    try:
                                        shutil.copytree(temp_chromium_dir, target_chromium_dir, dirs_exist_ok=True)
                                        
                                        # 验证提取的文件
                                        if temp_chromium_dir.name.startswith('chromium_headless_shell'):
                                            target_exe = target_chromium_dir / 'chrome-win' / 'headless_shell.exe'
                                        else:
                                            target_exe = target_chromium_dir / 'chrome-win' / 'chrome.exe'
                                        
                                        if target_exe.exists() and target_exe.stat().st_size > 0:
                                            print(f"{_OK} 浏览器文件提取成功: {target_exe}")
                                            print(f"{_INFO} 浏览器版本: {temp_chromium_dir.name}")
                                            extracted_count += 1
                                    except Exception as e:
                                        print(f"{_WARN} 提取 {temp_chromium_dir.name} 失败: {e}")
                        
                        if extracted_count > 0:
                            # 清除可能存在的旧环境变量
                            if 'PLAYWRIGHT_BROWSERS_PATH' in os.environ:
                                old_path = os.environ['PLAYWRIGHT_BROWSERS_PATH']
                                print(f"{_INFO} 清除旧的环境变量: {old_path}")
                                del os.environ['PLAYWRIGHT_BROWSERS_PATH']
                            # 设置新的环境变量
                            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(playwright_dir)
                            print(f"{_INFO} 已提取 {extracted_count} 个浏览器版本")
                            print(f"{_INFO} 已设置PLAYWRIGHT_BROWSERS_PATH: {playwright_dir}")
                            playwright_installed = True
                            return True
        except Exception as e:
            print(f"{_WARN} 提取浏览器文件时出错: {e}")

    # 运行时支持通过 executable_path 回退到系统浏览器，无需阻塞启动下载 Chromium。
    if not playwright_installed and sys.platform == 'win32':
        system_browser_candidates = [
            Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Google/Chrome/Application/chrome.exe',
            Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Google/Chrome/Application/chrome.exe',
            Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Microsoft/Edge/Application/msedge.exe',
            Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
        ]
        for browser_path in system_browser_candidates:
            if browser_path.is_file():
                print(f"{_OK} Playwright Chromium未安装，将使用系统浏览器: {browser_path}")
                return True
    
    # 如果没找到，尝试安装
    if not playwright_installed:
        print(f"{_WARN} 未找到Playwright浏览器，正在自动安装...")
        print("   这可能需要几分钟时间，请耐心等待...")
        
        try:
            # 方法1: 尝试使用playwright的Python API安装（推荐，适用于打包后的exe）
            try:
                # 直接调用playwright的安装函数
                from playwright._impl._driver import install_driver, install_browsers
                print("   正在安装Playwright驱动...")
                install_driver()
                print("   正在安装Chromium浏览器...")
                install_browsers(['chromium'])
                print(f"{_OK} Playwright浏览器安装成功（通过API）")
                playwright_installed = True
            except ImportError:
                # 如果API不可用，使用命令行方式
                print("   使用命令行方式安装...")
                import subprocess
                
                # 尝试使用playwright的安装命令
                # 对于打包后的exe，playwright模块应该已经包含
                creation_flags = 0
                if sys.platform == 'win32' and hasattr(subprocess, 'CREATE_NO_WINDOW'):
                    creation_flags = subprocess.CREATE_NO_WINDOW
                
                result = subprocess.run(
                    [sys.executable, '-m', 'playwright', 'install', 'chromium'],
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10分钟超时
                    creationflags=creation_flags
                )
                
                if result.returncode == 0:
                    print(f"{_OK} Playwright浏览器安装成功")
                    playwright_installed = True
                else:
                    print(f"{_WARN} Playwright浏览器安装失败")
                    if result.stdout:
                        print(f"   输出: {result.stdout[-500:]}")  # 只显示最后500字符
                    if result.stderr:
                        print(f"   错误: {result.stderr[-500:]}")
                    print("   您可以稍后手动运行: playwright install chromium")
                    return False
            except Exception as api_error:
                # API安装失败，尝试命令行方式
                print(f"   API安装失败，尝试命令行方式: {api_error}")
                import subprocess
                
                creation_flags = 0
                if sys.platform == 'win32' and hasattr(subprocess, 'CREATE_NO_WINDOW'):
                    creation_flags = subprocess.CREATE_NO_WINDOW
                
                result = subprocess.run(
                    [sys.executable, '-m', 'playwright', 'install', 'chromium'],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    creationflags=creation_flags
                )
                
                if result.returncode == 0:
                    print(f"{_OK} Playwright浏览器安装成功（通过命令行）")
                    playwright_installed = True
                else:
                    print(f"{_WARN} Playwright浏览器安装失败")
                    if result.stdout:
                        print(f"   输出: {result.stdout[-500:]}")
                    if result.stderr:
                        print(f"   错误: {result.stderr[-500:]}")
                    print("   您可以稍后手动运行: playwright install chromium")
                    return False
            except ImportError:
                # 如果playwright模块不可用，尝试使用subprocess
                import subprocess
                result = subprocess.run(
                    [sys.executable, '-m', 'playwright', 'install', 'chromium'],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' and hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                )
                
                if result.returncode == 0:
                    print(f"{_OK} Playwright浏览器安装成功")
                    playwright_installed = True
                else:
                    print(f"{_WARN} Playwright浏览器安装失败")
                    if result.stdout:
                        print(f"   输出: {result.stdout}")
                    if result.stderr:
                        print(f"   错误: {result.stderr}")
                    print("   您可以稍后手动运行: playwright install chromium")
                    return False
                
        except subprocess.TimeoutExpired:
            print(f"{_WARN} Playwright浏览器安装超时（超过10分钟）")
            print("   您可以稍后手动运行: playwright install chromium")
            return False
        except Exception as e:
            print(f"{_WARN} Playwright浏览器安装失败: {e}")
            import traceback
            print(f"   详细错误: {traceback.format_exc()}")
            print("   您可以稍后手动运行: playwright install chromium")
            return False
    
    return playwright_installed

# 检查并安装Playwright浏览器
try:
    _check_and_install_playwright()
except Exception as e:
    print(f"{_WARN} Playwright浏览器检查失败: {e}")
    print("   程序将继续启动，但Playwright功能可能不可用")
    # 继续启动，不影响主程序运行


def _verify_browser_launchable():
    """启动时实际拉起一次浏览器，确认版本匹配。

    仅检查目录存在是不够的：playwright 与 Chromium revision 强绑定，
    版本不匹配时 launch 会报 "Executable doesn't exist"。此时滑块验证、
    扫码登录、账号资料抓取会全部静默失效 —— 滑块处理在 0.3 秒内就崩掉，
    看日志只会看到"验证失败"，很难联想到是浏览器问题。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"{_WARN} 未安装 playwright，滑块验证与扫码登录将不可用")
        return False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        print(f"{_OK} 浏览器自检通过，滑块验证与扫码登录可用")
        return True
    except Exception as exc:
        detail = str(exc)
        print(f"{_ERROR} 浏览器无法启动，滑块验证与扫码登录将失效！")
        if "Executable doesn't exist" in detail:
            print("   原因：playwright 版本与已安装的 Chromium 不匹配")
            print("   修复：python -m playwright install chromium")
        else:
            print(f"   详情：{detail[:200]}")
        print("   注意：验证码处理失效会导致 Token 刷新持续失败并加剧平台风控")
        return False


try:
    _verify_browser_launchable()
except Exception as e:
    print(f"{_WARN} 浏览器自检异常: {e}")

# ==================== 自动构建前端 ====================
def _build_frontend():
    """自动安装依赖并构建前端"""
    frontend_dir = Path("frontend")
    static_dir = Path("static")

    # 容器镜像在构建阶段就已经把前端产物放进 static/，运行时既没有 npm 也没有
    # node_modules。这里再走一遍只会白等一次 npm 失败，低配设备上还要多花几十秒，
    # 所以直接跳过。
    if os.getenv('DOCKER_ENV', '').lower() in ('1', 'true', 'yes'):
        print(f"{_INFO} 容器环境，前端已在镜像构建阶段生成，跳过构建")
        return True

    if not frontend_dir.exists():
        print(f"{_WARN} frontend 目录不存在，跳过前端构建")
        return False

    build_dir = frontend_dir
    print(f"{_INFO} 使用 frontend 目录作为前端源")
    print("检查前端构建状态...")

    need_build = False
    index_html = static_dir / "index.html"

    if not index_html.exists():
        need_build = True
        print(f"{_INFO} static/index.html 不存在，需要构建前端")
    else:
        # 必须在进入目录前剪枝：node_modules 动辄几万个文件，rglob 会先把它们
        # 全部走一遍再过滤，在 NAS 的机械盘或 overlay 文件系统上能卡住好几分钟，
        # 看起来就像"启动卡死、资源打满"。
        ignored_dirs = {"node_modules", "dist", ".vite"}
        latest_source_mtime = 0.0
        for root, dirs, files in os.walk(build_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for name in files:
                try:
                    mtime = os.stat(os.path.join(root, name)).st_mtime
                except OSError:
                    continue
                if mtime > latest_source_mtime:
                    latest_source_mtime = mtime

        if latest_source_mtime > index_html.stat().st_mtime:
            need_build = True
            print(f"{_INFO} 前端源码比构建产物新，需要重新构建")
        else:
            print(f"{_OK} 前端构建产物是最新的，跳过")

    # 如果不需要构建，直接返回
    if not need_build:
        return True

    # 开始构建前端
    print(f"{_INFO} 开始构建前端...")
    print(f"   源目录: {build_dir}")
    print(f"   1. 安装 npm 依赖...")

    try:
        import subprocess

        # 设置 Windows 下的 subprocess 参数
        creation_flags = 0
        if sys.platform == 'win32' and hasattr(subprocess, 'CREATE_NO_WINDOW'):
            creation_flags = subprocess.CREATE_NO_WINDOW

        install_command = ['npm', 'ci'] if (build_dir / 'package-lock.json').exists() else ['npm', 'install']
        install_label = ' '.join(install_command)

        try:
            result = subprocess.run(
                install_command,
                cwd=str(build_dir),
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                creationflags=creation_flags
            )

            if result.returncode == 0:
                print(f"{_OK} npm 依赖安装成功")
            else:
                print(f"{_WARN} {install_label} 失败")
                if result.stdout:
                    print(f"   输出: {result.stdout[-500:]}")
                if result.stderr:
                    print(f"   错误: {result.stderr[-500:]}")
                return False
        except subprocess.TimeoutExpired:
            print(f"{_WARN} {install_label} 超时（超过5分钟）")
            return False
        except FileNotFoundError:
            print(f"{_WARN} 未找到 npm，请确保已安装 Node.js 和 npm")
            print(f"   你可以手动运行: cd {build_dir} && npm install && npm run build")
            return False
        except Exception as e:
            print(f"{_WARN} {install_label} 失败: {e}")
            return False

        # 2. npm run build
        print(f"   2. 构建前端...")
        try:
            result = subprocess.run(
                ['npm', 'run', 'build'],
                cwd=str(build_dir),
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                creationflags=creation_flags
            )

            if result.returncode == 0:
                print(f"{_OK} 前端构建成功")
                return True
            else:
                print(f"{_WARN} npm run build 失败")
                if result.stdout:
                    print(f"   输出: {result.stdout[-500:]}")
                if result.stderr:
                    print(f"   错误: {result.stderr[-500:]}")
                return False
        except subprocess.TimeoutExpired:
            print(f"{_WARN} npm run build 超时（超过5分钟）")
            return False
        except Exception as e:
            print(f"{_WARN} npm run build 失败: {e}")
            return False

    except Exception as e:
        print(f"{_WARN} 前端构建过程出错: {e}")
        return False


# 尝试构建前端
try:
    build_success = _build_frontend()
    if not build_success:
        print(f"{_WARN} 前端构建失败，程序将继续启动但前端可能不可用")
except Exception as e:
    print(f"{_WARN} 前端构建检查失败: {e}")
    print("   程序将继续启动，但前端可能不可用")

# ==================== 现在可以安全地导入其他模块 ====================
import asyncio
import threading
import uvicorn
from urllib.parse import urlparse
from loguru import logger

# 修复Linux环境下的asyncio子进程问题
if sys.platform.startswith('linux'):
    try:
        # 在程序启动时就设置正确的事件循环策略
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        logger.debug("已设置事件循环策略以支持子进程")
    except Exception as e:
        logger.debug(f"设置事件循环策略失败: {e}")

from app.config import AUTO_REPLY, COOKIES_LIST
from app import cookie_manager as cm
from app.db_manager import db_manager
from app.file_log_collector import setup_file_logging


def _start_api_server():
    """后台线程启动 FastAPI 服务"""
    loop = None
    api_conf = AUTO_REPLY.get('api', {})

    # 优先使用环境变量配置
    host = os.getenv('API_HOST', '0.0.0.0')  # 默认绑定所有接口
    port = int(os.getenv('API_PORT', '8080'))  # 默认端口8080

    # 如果配置文件中有特定配置，则使用配置文件
    if 'host' in api_conf and 'API_HOST' not in os.environ:
        host = api_conf['host']
    if 'port' in api_conf and 'API_PORT' not in os.environ:
        port = api_conf['port']

    # 兼容旧的URL配置方式
    if (
        'url' in api_conf
        and 'host' not in api_conf
        and 'port' not in api_conf
        and 'API_HOST' not in os.environ
        and 'API_PORT' not in os.environ
    ):
        url = api_conf.get('url', 'http://0.0.0.0:8080/xianyu/reply')
        parsed = urlparse(url)
        if parsed.hostname and parsed.hostname != 'localhost':
            host = parsed.hostname
        port = parsed.port or 8080

    logger.info(f"启动Web服务器: http://{host}:{port}")
    # 在后台线程中创建独立事件循环并直接运行 server.serve()
    import uvicorn
    try:
        config = uvicorn.Config("app.reply_server:app", host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())
    except Exception as e:
        logger.error(f"uvicorn服务器启动失败: {e}")
    finally:
        if loop is not None:
            if loop.is_running():
                loop.stop()
            loop.close()
        asyncio.set_event_loop(None)




def load_keywords_file(path: str):
    """从文件读取关键字 -> [(keyword, reply)]"""
    kw_list = []
    p = Path(path)
    if not p.exists():
        return kw_list
    with p.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '\t' in line:
                k, r = line.split('\t', 1)
            elif ' ' in line:
                k, r = line.split(' ', 1)
            elif ':' in line:
                k, r = line.split(':', 1)
            else:
                continue
            kw_list.append((k.strip(), r.strip()))
    return kw_list


async def main():
    print("开始启动主程序...")

    # 初始化文件日志收集器
    print("初始化文件日志收集器...")
    setup_file_logging()
    logger.info("文件日志收集器已启动，开始收集实时日志")

    loop = asyncio.get_running_loop()

    # 创建 CookieManager 并在全局暴露
    print("创建 CookieManager...")
    cm.manager = cm.CookieManager(loop)
    manager = cm.manager
    print("CookieManager 创建完成")

    # 1) 从数据库加载的 Cookie 已经在 CookieManager 初始化时完成
    # 为每个启用的 Cookie 启动任务
    for cid, val in manager.cookies.items():
        # 检查账号是否启用
        if not manager.get_cookie_status(cid):
            logger.info(f"跳过禁用的 Cookie: {cid}")
            continue

        try:
            await manager._ensure_cookie_task_async(cid, val)
        except Exception as e:
            logger.error(f"启动 Cookie 任务失败: {cid}, {e}")
            import traceback
            logger.error(f"详细错误信息: {traceback.format_exc()}")
    
    # 2) 如果配置文件中有新的 Cookie，也加载它们
    for entry in COOKIES_LIST:
        cid = entry.get('id')
        val = entry.get('value')
        if not cid or not val or cid in manager.cookies:
            continue
        
        kw_file = entry.get('keywords_file')
        kw_list = load_keywords_file(kw_file) if kw_file else None
        manager.add_cookie(cid, val, kw_list)
        logger.info(f"从配置文件加载 Cookie: {cid}")

    # 3) 若老环境变量仍提供单账号 Cookie，则作为 default 账号
    env_cookie = os.getenv('COOKIES_STR')
    if env_cookie and 'default' not in manager.list_cookies():
        manager.add_cookie('default', env_cookie)
        logger.info("从环境变量加载 default Cookie")

    # 启动 API 服务线程
    print("启动 API 服务线程...")
    threading.Thread(target=_start_api_server, daemon=True).start()
    print("API 服务线程已启动")

    # 启动数据库自动备份：全局一份，不随账号数量重复
    print("启动数据库自动备份任务...")
    asyncio.create_task(_db_backup_loop())

    # 阻塞保持运行
    print("主程序启动完成，保持运行...")
    await asyncio.Event().wait()


async def _db_backup_loop():
    """数据库定时备份。

    SQLite 是单文件存储，损坏或误删就全部丢失，因此默认开启。
    间隔和保留份数可在系统设置里调整。
    """
    from app.db_manager import db_manager
    from utils.db_backup import create_backup

    while True:
        try:
            enabled_str = db_manager.get_system_setting('db_backup_enabled')
            interval_str = db_manager.get_system_setting('db_backup_interval')
            keep_str = db_manager.get_system_setting('db_backup_keep')

            # 默认开启：备份没有副作用，出问题时能救命
            enabled = str(enabled_str or '').strip().lower() != 'false'
            try:
                interval = int(interval_str) if interval_str else 86400
            except (TypeError, ValueError):
                interval = 86400
            interval = max(3600, interval)
            try:
                keep = int(keep_str) if keep_str else 7
            except (TypeError, ValueError):
                keep = 7

            if not enabled:
                await asyncio.sleep(600)
                continue

            result = create_backup(keep=max(1, keep))
            if not result['success']:
                logger.warning(f"数据库自动备份失败: {result['message']}")

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("数据库自动备份任务已取消")
            raise
        except Exception as e:
            logger.error(f"数据库自动备份异常: {e}")
            await asyncio.sleep(600)


if __name__ == '__main__':
    asyncio.run(main())
