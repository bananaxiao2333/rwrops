import colorlog
import logging


def init_color_logger():
    log_format = (
        "%(log_color)s%(asctime)s [%(levelname)s] [%(name)s] %(message)s%(reset)s"
    )

    log_colors = {
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }

    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        log_format, log_colors=log_colors))

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.addHandler(handler)

    logger.info('logger inited')
    return logger
