#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试日志模块"""

from logger import logger

def test_logger():
    logger.info("日志模块测试 - INFO级别")
    logger.debug("日志模块测试 - DEBUG级别")
    logger.warning("日志模块测试 - WARNING级别")
    logger.error("日志模块测试 - ERROR级别")
    
    print("\n日志测试完成，请检查 logs/ 目录下的日志文件")

if __name__ == "__main__":
    test_logger()
