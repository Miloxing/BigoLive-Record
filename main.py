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


def record(p, last_record_time):
    """
    录制过程中要执行的检测与判断
    """
    # global p, record_status, last_record_time, kill_times  # noqa
    kill_times = 0
    while True:
        if not rooms[room_id]['record'] or rooms[room_id]['wait']:
            p.send_signal(signal.SIGTERM)
            time.sleep(0.5)
        line = p.stdout.readline().decode()
        p.stdout.flush()
        logger.log(15, line.rstrip())
        if match('video:[0-9kmgB]* audio:[0-9kmgB]* subtitle:[0-9kmgB]*', line) or 'Exiting normally' in line:
            rooms[room_id]['record_status'] = False  # 如果FFmpeg正常结束录制则退出本循环
            break
        elif match('frame=[0-9]', line) or 'Opening' in line:
            last_record_time = get_timestamp()  # 获取最后录制的时间
        elif 'Failed to read handshake response' in line:
            time.sleep(5)  # FFmpeg读取m3u8流失败，等个5s康康会不会恢复
            continue
        time_diff = get_timestamp() - last_record_time  # 计算上次录制到目前的时间差
        if time_diff >= 65:
            logger.error('最后一次录制到目前已超65s，将尝试发送终止信号')
            logger.debug(f'间隔时间：{time_diff}s')
            kill_times += 1
            # 若最后一次录制到目前已超过65s，则认为FFmpeg卡死，尝试发送终止信号
            p.send_signal(signal.SIGTERM)
            time.sleep(0.5)
            if kill_times >= 3:
                logger.critical('由于无法结束FFmpeg进程，将尝试自我了结')
                sys.exit(1)
        if 'Immediate exit requested' in line:
            logger.info('FFmpeg已被强制结束')
            break
        p_poll = p.poll()
        if p_poll is not None and p_poll != -15:  # 如果FFmpeg已退出但没有被上一个判断和本循环第一个判断捕捉到，则当作异常退出
            logger.error('ffmpeg未正常退出，请检查日志文件！')
            rooms[room_id]['record_status'] = False
            break
        #print(line,p.poll())


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
        command = ['ffmpeg', '-rw_timeout', '10000000', '-timeout', '10000000', '-listen_timeout', '10000000',
                   '-headers',
                   '"Accept: */*? Accept-Encoding: gzip, deflate, br? Accept-Language: zh,zh-TW;q=0.9,en-US;q=0.8,en;'
                   f'q=0.7,zh-CN;q=0.6,ru;q=0.5? Origin: https://www.bigo.tv '
                   'User-Agent: Mozilla/5.0 (Windows NT 10.0;Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.106 Safari/537.36?"', '-i',
                   f"{m3u8_address}", '-c:v', 'copy', '-c:a', 'copy', '-bsf:a', 'aac_adtstoasc',
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
        # p = Popen(command, stdin=PIPE, stdout=PIPE, stderr=STDOUT)
        rooms[room_id]['record_status'] = True
        start_time = last_record_time = get_timestamp()
        try:
            t = threading.Thread(target=record, args=(p, last_record_time,))
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
