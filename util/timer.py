import time
from functools import wraps
import logging

logger = logging.getLogger(__name__)


def timer(func, desc: str = ""):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()  # 记录开始时间
        result = func(*args, **kwargs)  # 执行被装饰的函数
        end_time = time.time()  # 记录结束时间
        elapsed_time = end_time - start_time  # 计算耗时
        if not desc:
            logger.info(
                f"'{func.__name__}' executed in {elapsed_time:.4f} s")
        else:
            logger.info(
                f"'{func.__name__}'[{desc}] executed in {elapsed_time:.4f} s")

        return result  # 返回被装饰函数的执行结果
    return wrapper
