import os
import uuid
import hashlib
from PIL import Image
from typing import Optional
from loguru import logger

class ImageManager:
    """图片管理器，负责图片的保存、压缩和访问"""
    
    def __init__(self, upload_dir: str = "static/uploads/images"):
        """初始化图片管理器
        
        Args:
            upload_dir: 图片上传目录
        """
        self.upload_dir = upload_dir
        self.max_size = 5 * 1024 * 1024  # 5MB
        self.max_width = 1920
        self.max_height = 1080
        self.allowed_formats = {'JPEG', 'PNG', 'GIF', 'WEBP'}
        
        # 确保上传目录存在
        self._ensure_upload_dir()
    
    def _ensure_upload_dir(self):
        """确保上传目录存在"""
        try:
            os.makedirs(self.upload_dir, exist_ok=True)
            logger.info(f"图片上传目录已准备: {self.upload_dir}")
        except Exception as e:
            logger.error(f"创建图片上传目录失败: {e}")
            raise
    
    def save_image(self, image_data: bytes, original_filename: str = None) -> Optional[str]:
        """保存图片文件
        
        Args:
            image_data: 图片二进制数据
            original_filename: 原始文件名（可选）
            
        Returns:
            保存成功返回相对路径，失败返回None
        """
        try:
            logger.info(f"开始保存图片，数据大小: {len(image_data)} bytes")

            # 验证图片数据
            if not self._validate_image_data(image_data):
                logger.error("图片数据验证失败")
                return None
            
            # 生成唯一文件名
            file_hash = hashlib.md5(image_data).hexdigest()
            file_extension = self._get_image_extension(image_data)
            filename = f"{file_hash}_{uuid.uuid4().hex[:8]}.{file_extension}"
            
            # 完整文件路径
            file_path = os.path.join(self.upload_dir, filename)
            
            # 检查文件是否已存在
            if os.path.exists(file_path):
                logger.info(f"图片文件已存在，跳过保存: {filename}")
                return self._get_relative_path(file_path)
            
            # 处理和保存图片
            processed_image_data = self._process_image(image_data)
            
            with open(file_path, 'wb') as f:
                f.write(processed_image_data)
            
            logger.info(f"图片保存成功: {filename}")
            return self._get_relative_path(file_path)
            
        except Exception as e:
            logger.error(f"保存图片失败: {e}")
            return None
    
    def _validate_image_data(self, image_data: bytes) -> bool:
        """验证图片数据"""
        try:
            # 检查文件大小
            if len(image_data) > self.max_size:
                logger.warning(f"图片文件过大: {len(image_data)} bytes > {self.max_size} bytes")
                return False
            
            # 尝试打开图片验证格式
            from io import BytesIO
            with Image.open(BytesIO(image_data)) as img:
                if img.format not in self.allowed_formats:
                    logger.warning(f"不支持的图片格式: {img.format}")
                    return False
                
                # 检查图片尺寸（允许更大的尺寸，特别是手机长截图）
                width, height = img.size
                max_dimension = 4096  # 最大边长4096像素
                if width > max_dimension or height > max_dimension:
                    logger.warning(f"图片尺寸过大: {width}x{height}，最大允许: {max_dimension}x{max_dimension}")
                    return False

                # 检查图片像素总数（防止过大的图片占用太多内存）
                total_pixels = width * height
                max_pixels = 8 * 1024 * 1024  # 8M像素
                if total_pixels > max_pixels:
                    logger.warning(f"图片像素总数过大: {total_pixels}，最大允许: {max_pixels}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"图片验证失败: {e}")
            return False
    
    def _get_image_extension(self, image_data: bytes) -> str:
        """获取图片扩展名"""
        try:
            from io import BytesIO
            with Image.open(BytesIO(image_data)) as img:
                format_to_ext = {
                    'JPEG': 'jpg',
                    'PNG': 'png',
                    'GIF': 'gif',
                    'WEBP': 'webp'
                }
                return format_to_ext.get(img.format, 'jpg')
        except:
            return 'jpg'
    
    def _process_image(self, image_data: bytes) -> bytes:
        """处理图片（压缩、调整尺寸等）"""
        try:
            from io import BytesIO
            
            with Image.open(BytesIO(image_data)) as img:
                # 转换为RGB模式（如果需要）
                if img.mode in ('RGBA', 'LA', 'P'):
                    # 创建白色背景
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # 调整尺寸（如果需要）- 允许更大的尺寸
                width, height = img.size
                max_output_dimension = 2048  # 输出最大边长2048像素

                if width > max_output_dimension or height > max_output_dimension:
                    # 计算缩放比例，保持宽高比
                    ratio = min(max_output_dimension / width, max_output_dimension / height)
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    logger.info(f"图片已调整尺寸: {width}x{height} -> {new_width}x{new_height}")
                else:
                    logger.info(f"图片尺寸合适，无需调整: {width}x{height}")
                
                # 保存为JPEG格式，适度压缩
                output = BytesIO()
                img.save(output, format='JPEG', quality=85, optimize=True)
                return output.getvalue()
                
        except Exception as e:
            logger.error(f"图片处理失败: {e}")
            # 如果处理失败，返回原始数据
            return image_data
    
    def _get_relative_path(self, file_path: str) -> str:
        """获取相对于项目根目录的路径"""
        # 将绝对路径转换为相对路径
        rel_path = os.path.relpath(file_path)
        # 统一使用正斜杠
        return rel_path.replace('\\', '/')
    
    def delete_image(self, image_path: str) -> bool:
        """删除图片文件
        
        Args:
            image_path: 图片相对路径
            
        Returns:
            删除成功返回True，失败返回False
        """
        try:
            # 构建完整路径
            if not image_path.startswith(self.upload_dir):
                full_path = os.path.join(os.getcwd(), image_path)
            else:
                full_path = image_path
            
            if os.path.exists(full_path):
                os.remove(full_path)
                logger.info(f"图片删除成功: {image_path}")
                return True
            else:
                logger.warning(f"图片文件不存在: {image_path}")
                return False
                
        except Exception as e:
            logger.error(f"删除图片失败: {e}")
            return False
    
    def get_image_info(self, image_path: str) -> Optional[dict]:
        """获取图片信息
        
        Args:
            image_path: 图片相对路径
            
        Returns:
            图片信息字典或None
        """
        try:
            # 构建完整路径
            if not image_path.startswith(self.upload_dir):
                full_path = os.path.join(os.getcwd(), image_path)
            else:
                full_path = image_path
            
            if not os.path.exists(full_path):
                return None
            
            with Image.open(full_path) as img:
                return {
                    'width': img.width,
                    'height': img.height,
                    'format': img.format,
                    'mode': img.mode,
                    'size': os.path.getsize(full_path)
                }
                
        except Exception as e:
            logger.error(f"获取图片信息失败: {e}")
            return None

    def get_image_size(self, image_path: str) -> tuple:
        """获取图片尺寸

        Args:
            image_path: 图片相对路径

        Returns:
            (width, height) 或 (None, None)
        """
        try:
            info = self.get_image_info(image_path)
            if info:
                return info['width'], info['height']
            return None, None
        except Exception as e:
            logger.error(f"获取图片尺寸失败: {e}")
            return None, None

# 创建全局图片管理器实例
image_manager = ImageManager()
