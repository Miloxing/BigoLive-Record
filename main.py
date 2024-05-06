#!/usr/bin/env python3
# -*- coding:utf-8 -*-

"""
*--------------------------------------*
 基于 B站直播录播姬 By: Red_lnn 的修改，
 
 适用于BigoLive

 原作者仓库地址：
 https://github.com/Redlnn/blive_record
*--------------------------------------*
"""

# import ffmpy3  # noqa
import logging
import os
import re
import signal
import sys
import threading
import time
import traceback
from json import loads
from logging import handlers
from subprocess import PIPE, Popen, STDOUT

import requests
from regex import match

# 导入配置
from config import *   # noqa
from free_size_config import *

rooms = {}  # 记录各room状态

logging.addLevelName(15, 'FFmpeg')  # 自定义FFmpeg的日志级别
logger = logging.getLogger('Record')
logger.setLevel(logging.DEBUG)

fms = '[%(asctime)s %(levelname)s] %(message)s'
# datefmt = "%Y-%m-%d %H:%M:%S"
datefmt = "%H:%M:%S"

default_handler = logging.StreamHandler(sys.stdout)
if debug:
    default_handler.setLevel(logging.DEBUG)
elif verbose:
    default_handler.setLevel(15)
else:
    default_handler.setLevel(logging.INFO)
default_handler.setFormatter(logging.Formatter(fms, datefmt=datefmt))
logger.addHandler(default_handler)

rstr = r"[\/\\\:\*\?\"\<\>\|\- \n]"

if save_log:
    # file_handler = logging.FileHandler("debug.log", mode='w+', encoding='utf-8')
    if not os.path.exists(os.path.join('logs')):
        os.mkdir(os.path.join('logs'))
    file_handler = handlers.TimedRotatingFileHandler(
        os.path.join('logs', 'debug.log'), 'midnight', encoding='utf-8')
    if debug:
        default_handler.setLevel(logging.DEBUG)
    else:
        default_handler.setLevel(15)
    file_handler.setFormatter(logging.Formatter(fms, datefmt=datefmt))
    logger.addHandler(file_handler)


def get_timestamp() -> int:
    """
    获取当前时间戳
    """
    return int(time.time())


def get_time() -> str:
    """
    获取格式化后的时间
    """
    time_now = get_timestamp()
    time_local = time.localtime(time_now)
    dt = time.strftime("%Y%m%d_%H%M%S", time_local)
    return dt


def record(p, room_id, last_record_time, command=None):
    if command is None:
        command = []
    kill_times = 0
    while True:
        try:
            # 检查FFmpeg进程是否存在
            os.kill(p.pid, 0)
        except OSError:
            # 如果抛出OSError异常，说明进程已不存在
            logger.info(room_id+'FFmpeg进程已结束')
            rooms[room_id]['record_status'] = False
            break
        logger.debug("test")
        if not rooms[room_id]['record'] or rooms[room_id]['wait']:
            logger.info(room_id+'停止录制')
            p.terminate()  # 尝试终止进程
            p.wait(timeout=5)  # 等待进程结束，设置超时避免死锁
            rooms[room_id]['record_status'] = False
            break
        logger.debug("receive line")
        line = p.stdout.readline().decode()
        logger.debug(line)
        if not line:
            # 如果读取到的行为空，可能是进程已经结束
            logger.debug(room_id+'读取到空行，可能是进程已结束')
            rooms[room_id]['record_status'] = False
            break
        if "Exiting" in line or "Error" in line or "404 Not Found" in line:
            # 如果检测到退出或错误信息，假设录制已经结束
            logger.error(f'检测到FFmpeg输出：{line}')
            rooms[room_id]['record_status'] = False
            break

        if "No route to host" in line:
            logger.error('网络连接异常，等待5秒后重试')
            time.sleep(5)
            if command:
                p = Popen(command, stdin=PIPE, stdout=PIPE, stderr=STDOUT, shell=True)
            continue

        # 这里可以添加对line的其他处理逻辑
        # 比如更新last_record_time或者根据输出内容判断录制状态
        if match('video:[0-9kmgB]* audio:[0-9kmgB]* subtitle:[0-9kmgB]*', line) or 'Exiting normally' in line:
            logger.info(f'检测到FFmpeg输出：{line}')
            rooms[room_id]['record_status'] = False  # 如果FFmpeg正常结束录制则退出本循环
            break

        # 检查是否需要终止录制（示例中的逻辑）
        time_diff = time.time() - last_record_time
        if time_diff >= 65:
            logger.error('录制可能已卡住，尝试终止FFmpeg进程')
            p.terminate()  # 尝试终止进程
            p.wait(timeout=5)  # 等待进程结束，设置超时避免死锁
            kill_times += 1
            if kill_times >= 3:
                logger.critical('多次尝试结束FFmpeg进程失败，直接结束子进程')
                rooms[room_id]['record_status'] = False
                break
            last_record_time = time.time()  # 重置最后记录时间
        time.sleep(0.1)


def main(room_id):
    global rooms
    # global p, room_id, record_status, last_record_time, kill_times  # noqa
    while True:
        rooms[room_id]['record_status'] = False
        while True:
            logger.info('------------------------------')
            logger.info(f'正在检测直播间：{room_id}')
            try:
                room_info = requests.post(f'https://ta.bigo.tv/official_website/studio/getInternalStudioInfo',
                                         timeout=5,
                                         data={'siteId': room_id})
            except (requests.exceptions.ReadTimeout, requests.exceptions.Timeout, requests.exceptions.ConnectTimeout):
                logger.error(f'无法连接至B站API，等待{check_time}s后重新开始检测')
                time.sleep(check_time)
                continue
            room_info = loads(room_info.text)['data']
            live_status = room_info['hls_src']
            if live_status:
                break
            else:
                logger.info(f'没有开播，等待{check_time}s重新开始检测\033[F\f')
            time.sleep(check_time)
        if not os.path.exists(os.path.join('download')):
            try:
                os.mkdir(os.path.join('download'))
            except:  # noqa
                logger.error(f'无法创建下载文件夹 ↓\n{traceback.format_exc()}')
                sys.exit(1)
        if os.path.isfile(os.path.join('download')):
            logger.error('存在与下载文件夹同名的文件')
            sys.exit(1)
        logger.info('正在直播，准备开始录制')
        m3u8_address = live_status
        nick_name = re.sub(rstr, "_", room_info['nick_name'])
        room_topic = re.sub(rstr, "_", room_info['roomTopic'])
        # 下面命令中的timeout单位为微秒，10000000us为10s（https://www.cnblogs.com/zhifa/p/12345376.html）
        command = ['ffmpeg', '-timeout', '10000000', '-listen_timeout', '10000000',
                   '-i',
                   f"{m3u8_address}", '-c:v', 'copy', '-c:a', 'copy',
                   '-f', 'segment', '-segment_time', str(
                       segment_time), '-segment_start_number', '1',
                   os.path.join('download', f'{nick_name}_{room_id}-{get_time()}-{room_topic}_part%03d.{file_extensions}'), '-y']
        command_str = ''
        for _ in command:
            command_str += _ + ' '
        if debug:
            logger.debug('FFmpeg命令如下 ↓')
            logger.debug(command_str)
        p = Popen(command_str, stdin=PIPE, stdout=PIPE, stderr=STDOUT, shell=True)
        #p = Popen(command, stdin=PIPE, stdout=PIPE, stderr=STDOUT)
        rooms[room_id]['record_status'] = True
        start_time = last_record_time = get_timestamp()
        try:
            t = threading.Thread(target=record, args=(p, room_id, last_record_time,command_str))
            t.start()
            while True:
                if not rooms[room_id]['record_status']:
                    break
                if verbose or debug:
                    time.sleep(20)
                    logger.info(
                        f'\033[K--==>>> {nick_name} 已录制 {round((get_timestamp() - start_time) / 60, 2)} 分钟 <<<==--\033[F\r')
                else:
                    time.sleep(60)
                    logger.info(
                        f'\033[K--==>>> {nick_name} 已录制 {int((get_timestamp() - start_time) / 60)} 分钟 <<<==--\033[F\r')
                if not rooms[room_id]['record_status']:
                    break
        except KeyboardInterrupt:
            # p.send_signal(signal.CTRL_C_EVENT)
            logger.info('停止录制，等待ffmpeg退出后本程序会自动退出')
            logger.info('若长时间卡住，请再次按下ctrl+c (可能会损坏视频文件)')
            logger.info('Bye!')
            sys.exit(0)
        if wait:
            logger.info(f'空间不足，停止录制 {room_id}')
            break
        logger.info('FFmpeg已退出，重新开始检测直播间')
        # time.sleep(check_time)
    rooms.pop(room_id)


if __name__ == '__main__':
    logger.info('Bigo Live直播录制工具')
    logger.info('如要停止录制并退出，请按键盘 Ctrl+C')
    logger.info('如要修改录制设置，请以纯文本方式打开.py文件')
    logger.info('准备开始录制...')
    time.sleep(0.3)
    while True:
        run()
        try:
            from config import *
            for room_id in room_ids:
                if room_id not in rooms and (not wait or room_id in keep):

                    rooms[room_id] = {"record": True}
                    if room_id in keep:
                        rooms[room_id]['wait'] = False
                    else:
                        rooms[room_id]['wait'] = True
                    t = threading.Thread(target=main, args=(room_id,))
                    t.start()
            for room_id in rooms.keys():
                if room_id not in room_ids:
                    rooms[room_id]['record'] = False
            time.sleep(10)
        except KeyboardInterrupt:
            logger.info('Bye!')
            sys.exit(0)
